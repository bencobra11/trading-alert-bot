import os
import time
import json
import re
import requests
import ccxt
from flask import Flask, jsonify
from threading import Thread
from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. FLASK WEB SERVER & ENDPOINT TRIGGER
# ---------------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Crypto Market Screener + Gemini AI berjalan aktif 24/7!"

@app.route('/trigger')
def trigger_analysis():
    """Endpoint ini yang akan dipanggil oleh Cron-Job eksternal secara berkala"""
    print("[INFO] Menerima request /trigger dari Cron-Job eksternal.")
    
    # Menjalankan proses analisis di thread terpisah agar Flask langsung merespons Cron-Job
    # dan mencegah request mengalami HTTP Timeout di Render.
    analysis_thread = Thread(target=run_market_analysis)
    analysis_thread.start()
    
    return jsonify({
        "status": "success",
        "message": "Proses analisis pasar sedang berjalan di background."
    }), 200

# ---------------------------------------------------------
# 2. KONFIGURASI ENVIRONMENT VARIABLES
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

# Daftar target aset TradingView beserta Exchange-nya
TV_TARGETS = [
    {"symbol": "BTCUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "ETHUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "SOLUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "ZECUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "DOGEUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "GRTUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "BNBUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "HYPEUSDT", "screener": "crypto", "exchange": "TV_TARGETS"},
    {"symbol": "XRPUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "ADAUSDT", "screener": "crypto", "exchange": "BINANCE"}
]

# ---------------------------------------------------------
# 3. FUNGSI KIRIM TELEGRAM
# ---------------------------------------------------------
def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum diatur!")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code != 200:
            print(f"[ERROR Telegram] {res.text}")
    except Exception as e:
        print(f"[ERROR] Gagal mengirim pesan ke Telegram: {e}")

# Daftar target aset untuk Binance (Gunakan garis miring untuk CCXT)
TARGET_ASSETS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]

# Inisialisasi koneksi ke Binance
exchange = ccxt.binance({'enableRateLimit': True})

# ---------------------------------------------------------
# 4. FETCH ADVANCED DATA (Order Flow, VWAP, Volume Profile)
# ---------------------------------------------------------
def get_institutional_data():
    formatted_summary = []
    
    for symbol in TARGET_ASSETS:
        try:
            print(f"[INFO] Mengambil data institusional untuk {symbol}...")
            
            # 1. Mengambil Klines/Candles (4 Jam terakhir, 100 candle)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=100)
            
            # Variabel untuk VWAP & Volume Profile
            total_vol = 0
            total_vol_price = 0
            volume_by_price = {}
            current_price = ohlcv[-1][4] # Harga penutupan terakhir
            
            for candle in ohlcv:
                high, low, close, volume = candle[2], candle[3], candle[4], candle[5]
                typical_price = (high + low + close) / 3
                
                # Kalkulasi akumulasi VWAP
                total_vol += volume
                total_vol_price += typical_price * volume
                
                # Kalkulasi Volume Profile (Membulatkan harga untuk membuat "zona" profil)
                # Pembulatan dinamis: BTC dibulatkan per $10, Koin kecil per sen.
                round_factor = -1 if close > 1000 else (2 if close < 1 else 4)
                price_zone = round(close, round_factor)
                volume_by_price[price_zone] = volume_by_price.get(price_zone, 0) + volume

            vwap = total_vol_price / total_vol if total_vol > 0 else current_price
            
            # Mendapatkan Point of Control (POC) -> Zona harga dengan volume transaksi TERBESAR
            poc_price = max(volume_by_price, key=volume_by_price.get)
            
            # 2. Mengambil Order Book untuk Order Flow Imbalance
            order_book = exchange.fetch_order_book(symbol, limit=50)
            bids_vol = sum([bid[1] for bid in order_book['bids']]) # Total antrean Beli
            asks_vol = sum([ask[1] for ask in order_book['asks']]) # Total antrean Jual
            
            # Menentukan dominasi Order Flow
            if bids_vol > asks_vol:
                order_flow = f"DOMINASI BUY (Rasio {bids_vol/asks_vol:.1f}x vs Sell)"
            else:
                order_flow = f"DOMINASI SELL (Rasio {asks_vol/bids_vol:.1f}x vs Buy)"

            formatted_summary.append(
                f"Aset: {symbol} | Harga Saat Ini: ${current_price:,.4f}\n"
                f"   - VWAP (Anchored): ${vwap:,.4f}\n"
                f"   - Vol Profile (Point of Control): ${poc_price:,.4f}\n"
                f"   - Order Flow Imbalance: {order_flow}\n"
            )
            
            time.sleep(1) # Jeda agar tidak kena rate limit Binance
            
        except Exception as e:
            print(f"[ERROR Data] Gagal memproses {symbol}: {e}")
            time.sleep(1)
            
    if not formatted_summary:
        return None
        
    return "\n".join(formatted_summary)

# ---------------------------------------------------------
# 5. ANALISIS DENGAN GOOGLE GEMINI API
# ---------------------------------------------------------
def analyze_crypto_with_gemini(market_data):
    if not GEMINI_API_KEY:
        print("[ERROR] GEMINI_API_KEY belum dikonfigurasi!")
        return None
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Prompt dirombak khusus untuk analisis Smart Money Concepts (SMC)
    system_prompt = """Anda adalah analis trading institusional. Tugas Anda membaca data Order Flow, VWAP, dan Volume Profile untuk menghasilkan sinyal trading.

Aturan Logika Smart Money Anda:
1. VWAP: Jika Harga > VWAP, tren naik. Jika Harga < VWAP, tren turun. VWAP sering bertindak sebagai magnet atau support/resistance dinamis.
2. Volume Profile (Point of Control / POC): Ini adalah area harga dengan volume tertinggi. Harga cenderung kembali ke POC. Jika harga menjauh dari POC dengan Order Flow sejalan, itu adalah breakout valid.
3. Order Flow: Konfirmasi sentimen. Jika Order Flow "DOMINASI BUY" dan Harga berada di area support (VWAP/POC), probabilitas BUY sangat tinggi.

Evaluasi dan kembalikan HANYA format JSON valid:
{
    "BTC/USDT": {
        "signal": "BUY",
        "reason": "Harga memantul dari VWAP dan Point of Control didukung Order Flow Dominasi Buy 1.5x",
        "stop_loss": 58000,
        "take_profit": 65000
    }
}
Gunakan signal: "BUY", "HOLD", atau "SELL"."""

    available_models = []
    try:
        listed_models = list(client.models.list())
        for m in listed_models:
            name = m.name.replace("models/", "")
            if "gemini" in name:
                available_models.append(name)
    except Exception as e:
        available_models = ['gemini-2.5-flash', 'gemini-2.0-flash']
    
    for model_name in available_models:
        try:
            print(f"[INFO] Memproses AI SMC dengan: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=f"Berikut adalah data institusional terkini:\n\n{market_data}\n\nBerikan keputusan JSON Anda.",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.1,
                )
            )
            if response and response.text:
                return response.text
        except Exception as e:
            continue
            
    return None

# ---------------------------------------------------------
# 6. LOGIKA PEMROSESAN ANALISIS & FILTER NOTIFIKASI
# ---------------------------------------------------------
def run_market_analysis():
    print("🤖 Memulai eksekusi analisis pasar...")
    try:
        market_data = get_institutional_data()
        
        if market_data:
            ai_response_text = analyze_crypto_with_gemini(market_data)
            
            if ai_response_text:
                # Menghapus pembungkus Markdown ```json jika ada
                cleaned_json = re.sub(r'```(?:json)?\n?(.*?)\n?```', r'\1', ai_response_text, flags=re.DOTALL).strip()
                
                try:
                    signals = json.loads(cleaned_json)
                    
                    for coin, data in signals.items():
                        signal_type = str(data.get("signal", "HOLD")).upper()
                        
                        # FITUR UTAMA: HANYA kirim jika sinyal BUY atau SELL
                        if signal_type in ["BUY", "SELL"]:
                            msg = (
                                f"🚨 **SIGNAL {signal_type} : {coin}** 🚨\n\n"
                                f"📝 **Alasan**: {data.get('reason')}\n"
                                f"🎯 **Take Profit**: {data.get('take_profit')}\n"
                                f"🛑 **Stop Loss**: {data.get('stop_loss')}"
                            )
                            send_telegram_message(msg)
                            print(f"[ALERT] Pesan sinyal {signal_type} untuk {coin} berhasil dikirim.")
                        else:
                            print(f"[HOLD] {coin} -> Sinyal HOLD. Mengabaikan notifikasi.")
                            
                except json.JSONDecodeError:
                    print("[ERROR] AI tidak mengembalikan format JSON valid. Respon mentah:\n", cleaned_json)
        else:
            print("[ERROR] Gagal mengambil data pasar dari TradingView.")
            
    except Exception as e:
        print(f"[ERROR Execution] {e}")

# ---------------------------------------------------------
# 7. MAIN ENTRY POINT
# ---------------------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    # Flask berjalan secara langsung sebagai server utama
    app.run(host='0.0.0.0', port=port)
