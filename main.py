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
TOP_COINS_COUNT = int(os.environ.get("TOP_COINS_COUNT", "20"))

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
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code != 200:
            print(f"[ERROR Telegram] {res.text}")
    except Exception as e:
        print(f"[ERROR] Gagal mengirim pesan ke Telegram: {e}")

# ---------------------------------------------------------
# 4. FETCH DATA MARKET BINANCE (24h Ticker)
# ---------------------------------------------------------
def get_binance_top_crypto(limit=20):
    """Mengambil top pairs USDT dari Binance berdasarkan Volume 24 Jam"""
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        response = requests.get(url, timeout=15)
        data = response.json()
        
        ignored = ["USDCUSDT", "BUSDUSDT", "FDUSDUSDT", "TUSDUSDT", "DAIUSDT", "EURUSDT"]
        usdt_pairs = [
            item for item in data 
            if item['symbol'].endswith('USDT') and item['symbol'] not in ignored
        ]
        
        usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
        top_pairs = usdt_pairs[:limit]
        
        formatted_summary = []
        for coin in top_pairs:
            symbol = coin['symbol'].replace('USDT', '')
            price = float(coin['lastPrice'])
            price_change = float(coin['priceChangePercent'])
            high = float(coin['highPrice'])
            low = float(coin['lowPrice'])
            vol_usd = float(coin['quoteVolume']) / 1_000_000
            
            formatted_summary.append(
                f"- {symbol}/USDT | Harga: ${price:,.4f} | 24h Change: {price_change:+.2f}% | "
                f"High: ${high:,.4f} | Low: ${low:,.4f} | Vol 24h: ${vol_usd:,.2f}M"
            )
            
        return "\n".join(formatted_summary)
    except Exception as e:
        print(f"[ERROR Binance API] Gagal mengambil data pasar: {e}")
        return None

# ---------------------------------------------------------
# 5. ANALISIS DENGAN GOOGLE GEMINI API (DYNAMIC AUTO-TRY)
# ---------------------------------------------------------
def analyze_crypto_with_gemini(market_data):
    """Mengirim data pasar ke Gemini API dengan pencarian model otomatis"""
    if not GEMINI_API_KEY:
        return "⚠️ *Error*: GEMINI_API_KEY belum dikonfigurasi di Environment Variables!"
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    system_prompt = """
    Anda adalah seorang Senior Crypto Analyst & Quant Trader profesional.
    Tugas Anda adalah memindai data pasar 20 crypto teratas berdasar volume 24 jam dan memilih koin yang paling 'WORTH IT' untuk dibeli/dijual saat ini.

    Kriteria Survei & Evaluasi Anda:
    1. Momentum & Breakout Volume: Koin dengan volume tinggi dan pergerakan harga signifikan.
    2. Area Dip/Retracement: Koin berkualitas yang sedang mengalami koreksi sehat mendekati support 24 jam.
    3. Risk/Reward Ratio: Selalu tentukan titik Beli (Entry Zone), Target Jual (Take Profit), dan Batas Rugi (Stop Loss).

    Format Jawaban (Gunakan Markdown Telegram):
    🚨 *CRYPTO MARKET AI SURVEY REPORT (GEMINI)* 🚨
    📅 *Waktu:* Real-time Analysis

    🟢 *REKOMENDASI BELI (WORTH TO BUY)*
    1. *[NAMA KOIN]*
       - *Alasan:* [Penjelasan teknikal/momentum singkat]
       - 🎯 *Area Beli (Entry):* $X.XX
       - 📈 *Target Jual (TP):* $X.XX (+X%)
       - 🛡️ *Stop Loss (SL):* $X.XX (-X%)

    🔴 *KOIN PERLU DIWASPADAI / DIJUAL (TAKE PROFIT / AVOID)*
    - *[NAMA KOIN]:* [Alasan singkat, misal overbought / penurunan volume]

    💡 *RINGKASAN STRATEGI PASAR:*
    [1-2 kalimat saran kondisi pasar makro saat ini]
    """
    
    # Ambil daftar semua model dari akun Google API secara otomatis
    candidate_models = []
    try:
        listed = list(client.models.list())
        for m in listed:
            name = m.name.replace("models/", "")
            candidate_models.append(name)
    except Exception as e:
        print(f"[WARNING] Gagal mengambil daftar model: {e}")

    # Tambahkan daftar nama cadangan standar dari versi terbaru ke versi lama
    default_candidates = ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-flash-8b']
    for d in default_candidates:
        if d not in candidate_models:
            candidate_models.append(d)

    last_err = None
    # Uji coba setiap model sampai menemukan yang aktif di server Google
    for model_name in candidate_models:
        try:
            print(f"[INFO] Memproses analisis dengan model: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=f"Berikut adalah data 20 crypto teratas saat ini dari Binance:\n\n{market_data}\n\nTolong lakukan survei & analisis mendalam.",
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

# ---------------------------------------------------------
# 6. WORKER LOOP / SCHEDULED SURVEI
# ---------------------------------------------------------
def survey_loop():
    """Loop otomatis untuk menjalankan survei secara berkala"""
    print("🤖 Bot Crypto Gemini AI Survey siap & berjalan...")
    send_telegram_message("🚀 *Bot Crypto Market Screener + Gemini AI Aktif!*\nSistem mulai melakukan survei pasar pertama...")
    
    while True:
        try:
            print("[INFO] Mengambil data Binance & menjalankan survei Gemini...")
            market_data = get_binance_top_crypto(limit=TOP_COINS_COUNT)
            
            if market_data:
                analysis_report = analyze_crypto_with_gemini(market_data)
                send_telegram_message(analysis_report)
            else:
                send_telegram_message("⚠️ *Gagal mengambil data pasar dari Binance.*")
                
        except Exception as e:
            print(f"[ERROR Loop] {e}")
            
        sleep_seconds = int(SURVEY_INTERVAL_HOURS * 3600)
        print(f"[INFO] Survei berikutnya dalam {SURVEY_INTERVAL_HOURS} jam ({sleep_seconds} detik)...")
        time.sleep(sleep_seconds)

# ---------------------------------------------------------
# 7. MAIN ENTRY POINT
# ---------------------------------------------------------
if __name__ == '__main__':
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    survey_loop()
