import os
import json
import re
import requests
from flask import Flask, jsonify
from threading import Thread
from google import genai
from google.genai import types
from tradingview_ta import TA_Handler, Interval

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
    {"symbol": "HYPEUSDT", "screener": "crypto", "exchange": "BINANCE"},
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
    }
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code != 200:
            print(f"[ERROR Telegram] {res.text}")
    except Exception as e:
        print(f"[ERROR] Gagal mengirim pesan ke Telegram: {e}")

# ---------------------------------------------------------
# 4. FETCH DATA MARKET TRADINGVIEW
# ---------------------------------------------------------
def get_tradingview_data():
    formatted_summary = []
    for asset in TV_TARGETS:
        try:
            handler = TA_Handler(
                symbol=asset["symbol"],
                screener=asset["screener"],
                exchange=asset["exchange"],
                interval=Interval.INTERVAL_4_HOURS
            )
            analysis = handler.get_analysis()
            
            price = analysis.indicators.get("close", 0)
            rsi = analysis.indicators.get("RSI", 0)
            macd = analysis.indicators.get("MACD.macd", 0)
            ema20 = analysis.indicators.get("EMA20", 0)
            tv_recommendation = analysis.summary.get("RECOMMENDATION", "NEUTRAL")
            
            formatted_summary.append(
                f"Aset: {asset['symbol']} | Harga: ${price:,.4f} | "
                f"RSI: {rsi:.2f} | MACD: {macd:.2f} | EMA20: ${ema20:,.4f} | "
                f"Sinyal TradingView: {tv_recommendation}"
            )
        except Exception as e:
            print(f"[ERROR TV] Gagal mengambil data {asset['symbol']}: {e}")
            
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
    
    system_prompt = """Anda adalah seorang analis quantitative finance berbasis AI. Tugas Anda adalah membaca indikator teknikal (Harga, RSI, MACD, EMA20, dan Rekomendasi bawaan) lalu memberikan sinyal trading akhir.

Aturan Analisis Anda:
1. RSI < 30 adalah oversold (potensi BUY), RSI > 70 adalah overbought (potensi SELL).
2. Perhatikan posisi harga terhadap EMA20 untuk tren.
3. Pertimbangkan "Sinyal TradingView" sebagai faktor pendukung.

Evaluasi dan kembalikan HANYA dalam format JSON valid tanpa format markdown (```json).
Gunakan struktur JSON Dictionary di mana Symbol koin menjadi Key utamanya:
{
    "BTCUSDT": {
        "signal": "BUY",
        "reason": "Harga di atas EMA20 dan RSI menunjukkan momentum bullish yang kuat",
        "stop_loss": 58000,
        "take_profit": 65000
    },
    "XRPUSDT": {
        "signal": "HOLD",
        "reason": "Indikator RSI netral dan MACD belum menyilang",
        "stop_loss": 0,
        "take_profit": 0
    }
}
Hanya gunakan signal: "BUY", "HOLD", atau "SELL"."""

    default_candidates = ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash', 'gemini-1.5-flash']
    
    for model_name in default_candidates:
        try:
            print(f"[INFO] Memproses analisis dengan model: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=f"Berikut adalah data indikator teknikal terkini:\n\n{market_data}\n\nLakukan analisis mendalam dan berikan output JSON.",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.1,
                )
            )
            if response and response.text:
                return response.text
        except Exception as e:
            print(f"[DEBUG] Model {model_name} gagal: {e}")
            continue
            
    return None

# ---------------------------------------------------------
# 6. LOGIKA PEMROSESAN ANALISIS & FILTER NOTIFIKASI
# ---------------------------------------------------------
def run_market_analysis():
    print("🤖 Memulai eksekusi analisis pasar...")
    try:
        market_data = get_tradingview_data()
        
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
