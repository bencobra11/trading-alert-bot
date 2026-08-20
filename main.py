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

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

# Mengambil Kunci API OKX
OKX_API_KEY = os.environ.get("OKX_API_KEY")
OKX_SECRET = os.environ.get("OKX_SECRET")
OKX_PASSWORD = os.environ.get("OKX_PASSWORD")

TARGET_ASSETS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "XRP/USDT"]

# Inisialisasi OKX dengan Autentikasi (Jalur VIP Anti-Blokir)
if OKX_API_KEY and OKX_SECRET and OKX_PASSWORD:
    exchange = ccxt.okx({
        'apiKey': OKX_API_KEY,
        'secret': OKX_SECRET,
        'password': OKX_PASSWORD,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })
    print("[INFO] Terhubung ke OKX menggunakan API Key (Jalur VIP Aktif).")
else:
    exchange = ccxt.okx({'enableRateLimit': True})
    print("[WARNING] Terhubung ke OKX TANPA API Key. Harap masukkan API Key OKX Anda.")

def send_telegram_message(message, specific_chat_id=None):
    target_chat = specific_chat_id if specific_chat_id else TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": target_chat, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"[ERROR Telegram] Gagal mengirim pesan: {e}")

def get_institutional_data():
    formatted_summary = []
    for symbol in TARGET_ASSETS:
        try:
            print(f"[INFO] Mengambil data SMC untuk {symbol} dari OKX...")
            # 1. Ambil 50 Candle terakhir (Timeframe 4H)
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=50)
            
            total_vol = 0
            total_vol_price = 0
            volume_by_price = {}
            current_price = ohlcv[-1][4]
            
            for candle in ohlcv:
                high, low, close, volume = candle[2], candle[3], candle[4], candle[5]
                typical_price = (high + low + close) / 3
                
                # VWAP Calculation
                total_vol += volume
                total_vol_price += typical_price * volume
                
                # Volume Profile Calculation (POC)
                round_factor = -1 if close > 1000 else (2 if close < 1 else 4)
                price_zone = round(close, round_factor)
                volume_by_price[price_zone] = volume_by_price.get(price_zone, 0) + volume

            vwap = total_vol_price / total_vol if total_vol > 0 else current_price
            poc_price = max(volume_by_price, key=volume_by_price.get)
            
            # 2. Ambil Order Book untuk Order Flow Imbalance dari OKX
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
            time.sleep(2) # Jeda aman untuk OKX API
        except Exception as e:
            print(f"[ERROR Data] Gagal memproses {symbol}: {e}")
            time.sleep(2)
            
    if not formatted_summary:
        return None
    return "\n".join(formatted_summary)

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

    available_models = []
    try:
        listed_models = list(client.models.list())
        for m in listed_models:
            name = m.name.replace("models/", "")
            if "gemini" in name:
                available_models.append(name)
    except Exception as e:
        available_models = ['gemini-1.5-flash', 'gemini-1.5-pro']
    
    for model_name in available_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"Berikut adalah data SMC terkini:\n\n{market_data}\n\nBerikan keputusan JSON Anda.",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.1,
                    response_mime_type="application/json",
                )
            )
            if response and response.text:
                return response.text
        except Exception as e:
            print(f"[DEBUG] Model {model_name} gagal karena: {e}")
            continue
    return None

def process_signals(ai_response):
    cleaned_json = re.sub(r'```(?:json)?\n?(.*?)\n?```', r'\1', ai_response, flags=re.DOTALL).strip()
    try:
        return json.loads(cleaned_json)
    except json.JSONDecodeError:
        return None

def run_market_analysis():
    market_data = get_institutional_data()
    if market_data:
        ai_response = analyze_crypto_with_gemini(market_data)
        if ai_response:
            signals = process_signals(ai_response)
            if signals:
                for coin, data in signals.items():
                    signal_type = str(data.get("signal", "HOLD")).upper()
                    if signal_type in ["BUY", "SELL"]:
                        msg = (
                            f"🚨 **SIGNAL {signal_type} : {coin}** 🚨\n\n"
                            f"📝 **Alasan**: {data.get('reason')}\n"
                            f"🎯 **Take Profit**: {data.get('take_profit')}\n"
                            f"🛑 **Stop Loss**: {data.get('stop_loss')}"
                        )
                        send_telegram_message(msg)

def run_on_demand_analysis(chat_id):
    market_data = get_institutional_data()
    if market_data:
        ai_response = analyze_crypto_with_gemini(market_data)
        if ai_response:
            signals = process_signals(ai_response)
            if signals:
                balasan = "📊 **HASIL ANALISIS SMC (Data OKX)** 📊\n\n"
                for coin, data in signals.items():
                    balasan += f"🔸 **{coin}** -> *{data.get('signal')}*\n"
                    balasan += f"📝 {data.get('reason')}\n"
                    balasan += f"🎯 TP: {data.get('take_profit')} | 🛑 SL: {data.get('stop_loss')}\n\n"
                send_telegram_message(balasan, specific_chat_id=chat_id)
            else:
                send_telegram_message("⚠️ AI gagal memberikan format JSON yang valid.", specific_chat_id=chat_id)
        else:
            send_telegram_message("⚠️ AI gagal merespons.", specific_chat_id=chat_id)
    else:
        send_telegram_message("⚠️ Gagal mengambil data pasar dari OKX.", specific_chat_id=chat_id)

@app.route('/')
def home():
    return "Bot Crypto Market Screener + AI SMC aktif 24/7!"

@app.route('/trigger')
def trigger_analysis():
    Thread(target=run_market_analysis).start()
    return jsonify({"status": "success", "message": "Analisis berjalan di background."}), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data and "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        pesan_user = data["message"]["text"].strip().lower()
        if pesan_user == "/analisa":
            send_telegram_message("⏳ *Menarik data Order Flow & VWAP dari OKX...*", specific_chat_id=chat_id)
            Thread(target=run_on_demand_analysis, args=(chat_id,)).start()
        elif pesan_user == "/start":
            send_telegram_message("🤖 *Halo! Saya Bot AI Trading SMC Anda.*\nKetik **/analisa** kapan saja.", specific_chat_id=chat_id)
    return "OK", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
