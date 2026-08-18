import os
import time
import json
import re
import requests
import ccxt
from flask import Flask, jsonify, request
from threading import Thread
from google import genai
from google.genai import types

# ---------------------------------------------------------
# 1. INISIALISASI WEB SERVER & ENVIRONMENT VARIABLES
# ---------------------------------------------------------
app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
BINANCE_SECRET = os.environ.get("BINANCE_SECRET")

# Daftar target aset untuk CCXT (Binance)
TARGET_ASSETS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]

# Inisialisasi koneksi Binance (Gunakan API Key agar IP Render tidak diblokir/418)
if BINANCE_API_KEY and BINANCE_SECRET:
    exchange = ccxt.binance({
        'apiKey': BINANCE_API_KEY,
        'secret': BINANCE_SECRET,
        'enableRateLimit': True
    })
    print("[INFO] Terhubung ke Binance menggunakan API Key.")
else:
    exchange = ccxt.binance({'enableRateLimit': True})
    print("[WARNING] Terhubung tanpa API Key Binance (Rentan terkena limit IP).")

# ---------------------------------------------------------
# 2. FLASK ROUTES (Trigger Cron-Job & Telegram Webhook)
# ---------------------------------------------------------
@app.route('/')
def home():
    return "Bot Crypto Market Screener + AI SMC aktif 24/7!"

@app.route('/trigger')
def trigger_analysis():
    """Endpoint untuk Cron-Job (Hanya mengirim sinyal BUY/SELL)"""
    print("[INFO] Menerima request /trigger dari Cron-Job eksternal.")
    # Dijalankan di background agar server Flask langsung merespons Cron-Job
    Thread(target=run_market_analysis).start()
    return jsonify({"status": "success", "message": "Analisis berjalan di background."}), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """Endpoint untuk menerima pesan masuk (Chat) dari Telegram"""
    data = request.get_json()
    
    if data and "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        pesan_user = data["message"]["text"].strip().lower()
        
        if pesan_user == "/analisa":
            send_telegram_message("⏳ *Siap Komandan!* Sedang menarik data institusional (Order Flow & VWAP) dan menganalisis via AI. Mohon tunggu...", specific_chat_id=chat_id)
            # Menjalankan laporan lengkap di background
            Thread(target=run_on_demand_analysis, args=(chat_id,)).start()
            
        elif pesan_user == "/start":
            teks_start = "🤖 *Halo! Saya Bot AI Trading SMC Anda.*\n\nKetik perintah **/analisa** kapan saja untuk mendapatkan laporan pergerakan pasar institusional terkini secara instan."
            send_telegram_message(teks_start, specific_chat_id=chat_id)

    return "OK", 200

# ---------------------------------------------------------
# 3. FUNGSI PENGIRIMAN TELEGRAM
# ---------------------------------------------------------
def send_telegram_message(message, specific_chat_id=None):
    """Mengirim pesan ke Telegram. Jika specific_chat_id kosong, gunakan grup default"""
    target_chat = specific_chat_id if specific_chat_id else TELEGRAM_CHAT_ID
    
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print("[ERROR] Token atau Chat ID Telegram belum diatur!")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"[ERROR Telegram] Gagal mengirim pesan: {e}")

# ---------------------------------------------------------
# 4. FETCH DATA INSTITUTIONAL (VWAP, Vol Profile, Order Flow)
# ---------------------------------------------------------
def get_institutional_data():
    formatted_summary = []
    
    for symbol in TARGET_ASSETS:
        try:
            print(f"[INFO] Mengambil data institusional untuk {symbol}...")
            # 1. Ambil 100 Candle terakhir (Timeframe 4H)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=100)
            
            total_vol = 0
            total_vol_price = 0
            volume_by_price = {}
            current_price = ohlcv[-1][4]
            
            for candle in ohlcv:
                high, low, close, volume = candle[2], candle[3], candle[4], candle[5]
                typical_price = (high + low + close) / 3
                
                # Akumulasi VWAP
                total_vol += volume
                total_vol_price += typical_price * volume
                
                # Akumulasi Volume Profile (Pembulatan dinamis sesuai harga koin)
                round_factor = -1 if close > 1000 else (2 if close < 1 else 4)
                price_zone = round(close, round_factor)
                volume_by_price[price_zone] = volume_by_price.get(price_zone, 0) + volume

            vwap = total_vol_price / total_vol if total_vol > 0 else current_price
            poc_price = max(volume_by_price, key=volume_by_price.get) # Point of Control
            
            # 2. Ambil Order Book
            order_book = exchange.fetch_order_book(symbol, limit=50)
            bids_vol = sum([bid[1] for bid in order_book['bids']])
            asks_vol = sum([ask[1] for ask in order_book['asks']])
            
            if bids_vol > asks_vol:
                order_flow = f"DOMINASI BUY (Rasio {bids_vol/asks_vol:.1f}x vs Sell)"
            else:
                order_flow = f"DOMINASI SELL (Rasio {asks_vol/bids_vol:.1f}x vs Buy)"

            formatted_summary.append(
                f"Aset: {symbol} | Harga: ${current_price:,.4f}\n"
                f"   - VWAP (Anchored): ${vwap:,.4f}\n"
                f"   - Vol Profile (POC): ${poc_price:,.4f}\n"
                f"   - Order Flow Imbalance: {order_flow}\n"
            )
            
            # Jeda 5 detik agar IP Render tidak diblokir Binance (Error 418)
            time.sleep(5) 
            
        except Exception as e:
            print(f"[ERROR Data] Gagal memproses {symbol}: {e}")
            time.sleep(5)
            
    if not formatted_summary:
        return None
        
    return "\n".join(formatted_summary)

# ---------------------------------------------------------
# 5. ANALISIS GOOGLE GEMINI API (Smart Money Concepts)
# ---------------------------------------------------------
def analyze_crypto_with_gemini(market_data):
    if not GEMINI_API_KEY:
        print("[ERROR] GEMINI_API_KEY belum dikonfigurasi!")
        return None
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    system_prompt = """Anda adalah analis trading institusional. Tugas Anda membaca data Order Flow, VWAP, dan Volume Profile untuk menghasilkan sinyal trading.

Aturan Logika Smart Money Anda:
1. VWAP: Jika Harga > VWAP, tren naik. Jika Harga < VWAP, tren turun.
2. Point of Control (POC): Area harga dengan volume tertinggi. Jika harga menjauh dari POC dan Order Flow sejalan, itu indikasi breakout yang kuat.
3. Order Flow: Jika Order Flow "DOMINASI BUY" dan Harga dekat dengan area support (VWAP/POC), peluang BUY tinggi.

Evaluasi dan kembalikan HANYA format JSON valid seperti ini:
{
    "BTC/USDT": {
        "signal": "BUY",
        "reason": "Harga memantul dari VWAP didukung Order Flow Dominasi Buy",
        "stop_loss": 58000,
        "take_profit": 65000
    }
}
Hanya gunakan signal: "BUY", "HOLD", atau "SELL"."""

    # Gunakan model yang paling stabil dan memiliki kuota besar
    available_models = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash']
    
    for model_name in available_models:
        try:
            print(f"[INFO] Memproses AI dengan: {model_name}")
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
            print(f"[DEBUG] Model {model_name} gagal, mencoba model lain...")
            continue
            
    print("[ERROR] Semua model Gemini gagal merespons.")
    return None

# ---------------------------------------------------------
# 6. LOGIKA EKSEKUSI BOT (Cron-job vs Telegram Manual)
# ---------------------------------------------------------
def process_signals(ai_response):
    """Fungsi bantuan untuk mengekstrak JSON dari respon Gemini"""
    cleaned_json = re.sub(r'```(?:json)?\n?(.*?)\n?```', r'\1', ai_response, flags=re.DOTALL).strip()
    try:
        return json.loads(cleaned_json)
    except json.JSONDecodeError:
        print(f"[ERROR] AI tidak membalas JSON murni:\n{cleaned_json}")
        return None

# ---------------------------------------------------------
# 7. MAIN ENTRY POINT
# ---------------------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
