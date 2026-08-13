import os
import time
import requests
from flask import Flask
from threading import Thread
from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. FLASK WEB SERVER (Menjaga Render.com Tetap Live 24/7)
# ---------------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Crypto Market Screener + Gemini AI berjalan aktif 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ---------------------------------------------------------
# 2. KONFIGURASI ENVIRONMENT VARIABLES
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

SURVEY_INTERVAL_HOURS = float(os.environ.get("SURVEY_INTERVAL_HOURS", "12"))
TOP_COINS_COUNT = int(os.environ.get("TOP_COINS_COUNT", "10"))

# ---------------------------------------------------------
# 3. FUNGSI KIRIM TELEGRAM
# ---------------------------------------------------------
def send_telegram_message(message):
    """Mengirim pesan ringkasan/notifikasi ke Telegram"""
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

from tradingview_ta import TA_Handler, Interval, Exchange

# ---------------------------------------------------------
# 4. FETCH DATA MARKET TRADINGVIEW
# ---------------------------------------------------------
# Sesuaikan 'symbol' dan 'exchange' persis seperti yang tertulis di TradingView.
# Contoh: Jika xAAPLUSDT ada di BingX, tulis exchange: "BINGX".
TV_TARGETS = [
    {"symbol": "BTCUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "ETHUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "SOLUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "ZECUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "DOGEUSDT", "screener": "crypto", "exchange": "BINANCE"},
    {"symbol": "GRTUSDT", "screener": "crypto", "exchange": "BINANCE"},
    # Untuk aset emas dan saham sintetis, pastikan exchange-nya benar (misal: BINGX, OANDA, dll)
    {"symbol": "XAUTUSDT", "screener": "crypto", "exchange": "BITFINEX"}, 
    {"symbol": "AAPLUSDT", "screener": "crypto", "exchange": "BINGX"}, 
    {"symbol": "MSFTUSDT", "screener": "crypto", "exchange": "BINGX"},
    {"symbol": "AMDUSDT", "screener": "crypto", "exchange": "BINGX"}
]

def get_tradingview_data():
    """Mengambil harga dan indikator teknikal dari TradingView"""
    formatted_summary = []
    
    for asset in TV_TARGETS:
        try:
            handler = TA_Handler(
                symbol=asset["symbol"],
                screener=asset["screener"],
                exchange=asset["exchange"],
                interval=Interval.INTERVAL_4_HOURS # Bisa diganti: INTERVAL_1_DAY, INTERVAL_1_HOUR
            )
            analysis = handler.get_analysis()
            
            # Mengambil harga dan indikator kunci
            price = analysis.indicators.get("close", 0)
            rsi = analysis.indicators.get("RSI", 0)
            macd = analysis.indicators.get("MACD.macd", 0)
            ema20 = analysis.indicators.get("EMA20", 0)
            tv_recommendation = analysis.summary.get("RECOMMENDATION", "NEUTRAL")
            
            formatted_summary.append(
                f"Aset: {asset['symbol']} | Harga: ${price:,.4f} | "
                f"RSI: {rsi:.2f} | MACD: {macd:.2f} | EMA20: ${ema20:,.4f} | "
                f"Sinyal Internal TradingView: {tv_recommendation}"
            )
        except Exception as e:
            print(f"[ERROR TV] Gagal mengambil data {asset['symbol']}: {e}")
            
    if not formatted_summary:
        return None
        
    return "\n".join(formatted_summary)

# ---------------------------------------------------------
# 5. ANALISIS DENGAN GOOGLE GEMINI API (DYNAMIC AUTO-TRY)
# ---------------------------------------------------------
def analyze_crypto_with_gemini(market_data):
    """Mengirim data pasar ke Gemini API dengan pencarian model otomatis"""
    if not GEMINI_API_KEY:
        return "⚠️ *Error*: GEMINI_API_KEY belum dikonfigurasi di Environment Variables!"
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    system_prompt = """Anda adalah seorang analis quantitative finance berbasis AI. Tugas Anda adalah membaca indikator teknikal (Harga, RSI, MACD, EMA20, dan Rekomendasi bawaan) lalu memberikan sinyal trading akhir.

Aturan Analisis Anda:
1. RSI < 30 adalah oversold (potensi BUY), RSI > 70 adalah overbought (potensi SELL).
2. Perhatikan posisi harga terhadap EMA20 untuk tren.
3. Pertimbangkan "Sinyal Internal TradingView" sebagai faktor pendukung.

Evaluasi dan kembalikan HANYA dalam format JSON valid tanpa format markdown (```json).
Gunakan struktur JSON Dictionary di mana Symbol koin menjadi Key utamanya:
{
    "BTCUSDT": {
        "signal": "BUY",
        "reason": "Harga di atas EMA20 dan RSI menunjukkan momentum bullish yang kuat",
        "stop_loss": 58000,
        "take_profit": 65000
    },
    "AAPLUSDT": {
        "signal": "HOLD",
        "reason": "Indikator RSI netral dan MACD belum menyilang",
        "stop_loss": 0,
        "take_profit": 0
    }
}
Hanya gunakan signal: "BUY", "HOLD", atau "SELL"."""
    
    candidate_models = []
    try:
        listed = list(client.models.list())
        for m in listed:
            name = m.name.replace("models/", "")
            candidate_models.append(name)
    except Exception as e:
        print(f"[WARNING] Gagal mengambil daftar model: {e}")

    default_candidates = ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash', 'gemini-1.5-flash']
    for d in default_candidates:
        if d not in candidate_models:
            candidate_models.append(d)

    last_err = None
    for model_name in candidate_models:
        try:
            print(f"[INFO] Memproses analisis dengan model: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                # === UBAH ANGKA 20 JADI 10 DI SINI JUGA ===
                contents=f"Berikut adalah data 10 crypto teratas saat ini dari Binance:\n\n{market_data}\n\nTolong lakukan survei & analisis mendalam.",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                )
            )
            if response and response.text:
                return response.text
        except Exception as e:
            print(f"[DEBUG] Model {model_name} gagal: {e}")
            last_err = e
            continue
            
    return f"⚠️ *Gagal melakukan analisis Gemini API:* `{str(last_err)}`"

import re # Tambahkan ini di bagian paling atas skrip Anda (di bawah import json)

# ---------------------------------------------------------
# 6. WORKER LOOP & FILTERING SIGNAL
# ---------------------------------------------------------
def survey_loop():
    """Loop otomatis untuk menjalankan survei secara berkala"""
    print("🤖 Bot Crypto Gemini AI Survey siap & berjalan...")
    send_telegram_message("🚀 *Bot Screener Aktif!*\nMemantau indikator teknikal dari TradingView...")
    
    while True:
        try:
            print("[INFO] Mengambil data indikator dari TradingView...")
            # Memanggil fungsi data TradingView (Blok 4 yang baru)
            market_data = get_tradingview_data()
            
            if market_data:
                print("[INFO] Menjalankan survei Gemini...")
                # Mengirim data TradingView ke Gemini API
                ai_response_text = analyze_crypto_with_gemini(market_data)
                
                if ai_response_text:
                    # Bersihkan teks jika AI membandel membungkusnya dengan ```json ... ```
                    cleaned_json = re.sub(r'```(?:json)?\n?(.*?)\n?```', r'\1', ai_response_text, flags=re.DOTALL).strip()
                    
                    try:
                        signals = json.loads(cleaned_json)
                        
                        # Loop setiap koin dari hasil JSON
                        for coin, data in signals.items():
                            signal_type = data.get("signal", "HOLD").upper()
                            
                            # FILTERING: Hanya kirim pesan jika BUY atau SELL
                            if signal_type in ["BUY", "SELL"]:
                                msg = (
                                    f"🚨 **SIGNAL {signal_type} : {coin}** 🚨\n\n"
                                    f"📝 Alasan: {data.get('reason')}\n"
                                    f"🎯 Take Profit: {data.get('take_profit')}\n"
                                    f"🛑 Stop Loss: {data.get('stop_loss')}"
                                )
                                send_telegram_message(msg)
                                print(f"[ALERT] {coin} -> {signal_type} terkirim!")
                            else:
                                print(f"[HOLD] {coin} - Tidak ada tindakan (Pesan tidak dikirim).")
                                
                    except json.JSONDecodeError:
                        print("[ERROR] AI tidak mengembalikan format JSON yang valid. Teks AI:\n", cleaned_json)
                        
            else:
                print("⚠️ Gagal mengambil data pasar dari TradingView.")
                
        except Exception as e:
            print(f"[ERROR Loop] {e}")
            
        sleep_seconds = int(SURVEY_INTERVAL_HOURS * 3600)
        print(f"[INFO] Survei selesai. Menunggu siklus berikutnya dalam {SURVEY_INTERVAL_HOURS} jam...")
        time.sleep(sleep_seconds)

# ---------------------------------------------------------
# 7. MAIN ENTRY POINT
# ---------------------------------------------------------
if __name__ == '__main__':
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    survey_loop()
