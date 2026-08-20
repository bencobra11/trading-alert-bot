import os
import time
import json
import re
import requests
from flask import Flask, jsonify, request
from threading import Thread
from google import genai
from google.genai import types
from tradingview_ta import TA_Handler, Interval

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

# Kita menggunakan pasangan kripto di bursa Binance via TradingView
TARGET_ASSETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"]

def send_telegram_message(message, specific_chat_id=None):
    target_chat = specific_chat_id if specific_chat_id else TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print("[ERROR] Token atau Chat ID Telegram belum diatur!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": target_chat, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"[ERROR Telegram] Gagal mengirim pesan: {e}")

# ---------------------------------------------------------
# FUNGSI BARU: Ambil Data dari TradingView
# ---------------------------------------------------------
def get_tradingview_data():
    formatted_summary = []
    
    for symbol in TARGET_ASSETS:
        try:
            print(f"[INFO] Mengambil data TradingView untuk {symbol}...")
            handler = TA_Handler(
                symbol=symbol,
                screener="crypto",
                exchange="BINANCE",
                interval=Interval.INTERVAL_4_HOURS
            )
            analysis = handler.get_analysis()
            
            # Ekstrak data indikator (Banyak indikator tersedia, kita ambil yang krusial untuk SMC)
            close = analysis.indicators.get("close", 0)
            vwap = analysis.indicators.get("VWAP", 0)
            ema20 = analysis.indicators.get("EMA20", 0)
            volume = analysis.indicators.get("volume", 0)
            
            # Kita buat tiruan "Order Flow" berdasarkan rekomendasi TradingView
            buy_power = analysis.summary.get("BUY", 0)
            sell_power = analysis.summary.get("SELL", 0)
            
            if buy_power > sell_power:
                order_flow = f"DOMINASI BUY (Kekuatan Beli: {buy_power} vs Jual: {sell_power})"
            else:
                order_flow = f"DOMINASI SELL (Kekuatan Jual: {sell_power} vs Beli: {buy_power})"
                
            formatted_summary.append(
                f"Aset: {symbol} | Harga Saat Ini: ${close:,.4f}\n"
                f"   - VWAP: ${vwap:,.4f}\n"
                f"   - EMA 20: ${ema20:,.4f}\n"
                f"   - Volume: {volume:,.0f}\n"
                f"   - Sentimen Pasar (Setara Order Flow): {order_flow}\n"
            )
            time.sleep(2) # Jeda sopan santun untuk TradingView
            
        except Exception as e:
            print(f"[ERROR TV] Gagal mengambil data {symbol}: {e}")
            time.sleep(2)
            
    if not formatted_summary:
        return None
    return "\n".join(formatted_summary)

def analyze_crypto_with_gemini(market_data):
    if not GEMINI_API_KEY:
        print("[ERROR] GEMINI_API_KEY belum dikonfigurasi!")
        return None
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    system_prompt = """Anda adalah analis trading institusional. Anda menggunakan logika Smart Money Concepts (SMC) yang disederhanakan.

Aturan Logika Anda:
1. VWAP & EMA: Jika Harga > VWAP dan Harga > EMA20, tren sangat bullish. VWAP adalah magnet harga.
2. Sentimen / Order Flow: Jika sentimen "DOMINASI BUY", cari peluang konfirmasi BUY.
3. Volume: Volume yang tinggi memvalidasi pergerakan harga.

Evaluasi dan kembalikan HANYA format JSON valid seperti ini:
{
    "BTCUSDT": {
        "signal": "BUY",
        "reason": "Harga memantul dari VWAP didukung Sentimen Dominasi Buy",
        "stop_loss": 58000,
        "take_profit": 65000
    }
}
Hanya gunakan signal: "BUY", "HOLD", atau "SELL"."""

    available_models = []
    try:
        print("[INFO] Mencari daftar model Gemini yang tersedia...")
        listed_models = list(client.models.list())
        for m in listed_models:
            name = m.name.replace("models/", "")
            if "gemini" in name:
                available_models.append(name)
    except Exception as e:
        print(f"[WARNING] Gagal mengambil daftar model: {e}")
        available_models = ['gemini-1.5-flash', 'gemini-1.5-pro']
    
    for model_name in available_models:
        try:
            print(f"[INFO] Mencoba memproses AI dengan: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=f"Berikut adalah data pasar terkini dari TradingView:\n\n{market_data}\n\nBerikan keputusan JSON Anda.",
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
            
    print("[ERROR] Semua model Gemini gagal merespons.")
    return None

def process_signals(ai_response):
    cleaned_json = re.sub(r'```(?:json)?\n?(.*?)\n?```', r'\1', ai_response, flags=re.DOTALL).strip()
    try:
        return json.loads(cleaned_json)
    except json.JSONDecodeError:
        print(f"[ERROR] AI tidak membalas JSON murni:\n{cleaned_json}")
        return None

def run_market_analysis():
    print("🤖 Memulai eksekusi analisis Cron-Job...")
    market_data = get_tradingview_data()
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
    print(f"🤖 Memulai analisis On-Demand untuk chat ID: {chat_id}")
    market_data = get_tradingview_data()
    if market_data:
        ai_response = analyze_crypto_with_gemini(market_data)
        if ai_response:
            signals = process_signals(ai_response)
            if signals:
                balasan = "📊 **HASIL ANALISIS SMC (TradingView)** 📊\n\n"
                for coin, data in signals.items():
                    balasan += f"🔸 **{coin}** -> *{data.get('signal')}*\n"
                    balasan += f"📝 {data.get('reason')}\n"
                    balasan += f"🎯 TP: {data.get('take_profit')} | 🛑 SL: {data.get('stop_loss')}\n\n"
                send_telegram_message(balasan, specific_chat_id=chat_id)
            else:
                send_telegram_message("⚠️ AI gagal memberikan format JSON yang valid.", specific_chat_id=chat_id)
        else:
            send_telegram_message("⚠️ AI gagal merespons permintaan.", specific_chat_id=chat_id)
    else:
        send_telegram_message("⚠️ Gagal mengambil data dari TradingView.", specific_chat_id=chat_id)

@app.route('/')
def home():
    return "Bot Crypto Market Screener + AI SMC aktif 24/7!"

@app.route('/trigger')
def trigger_analysis():
    print("[INFO] Menerima request /trigger dari Cron-Job eksternal.")
    Thread(target=run_market_analysis).start()
    return jsonify({"status": "success", "message": "Analisis berjalan di background."}), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data and "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        pesan_user = data["message"]["text"].strip().lower()
        if pesan_user == "/analisa":
            send_telegram_message("⏳ *Siap Komandan!* Sedang menarik data dari TradingView dan menganalisis via AI. Mohon tunggu...", specific_chat_id=chat_id)
            Thread(target=run_on_demand_analysis, args=(chat_id,)).start()
        elif pesan_user == "/start":
            teks_start = "🤖 *Halo! Saya Bot AI Trading Anda.*\n\nKetik perintah **/analisa** kapan saja untuk mendapatkan laporan instan."
            send_telegram_message(teks_start, specific_chat_id=chat_id)
    return "OK", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
