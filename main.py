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
    "Kamu adalah Intelligent Trading Bot, sebuah sistem algoritma trading kuantitatif berbasis Machine Learning. Saya ingin kamu menganalisis aset [BTCUSDT, SOLUSDT, ETHUSDT, DOGEUSDT, GRTUSDT, RENUSDT, ZECUSDT, AAPL, MSFT, AMD] pada hari ini.

Tolong simulasikan alur kerja algoritma prediktifmu dan berikan laporan dalam 4 tahap berikut:

Data Context: Berikan asumsi pergerakan harga historis dan volume dalam beberapa hari terakhir.

Feature Engineering: Evaluasi 3-4 indikator teknikal utama (seperti Moving Averages, RSI, MACD, atau Bollinger Bands) sebagai fitur model prediktifmu.

Model Prediction: Berdasarkan fitur-fitur di atas, simulasikan apa yang kemungkinan besar diprediksi oleh algoritma Machine Learning (misal: probabilitas harga naik vs turun dalam 24 jam ke depan).

Signal Generation: Hasilkan sinyal akhir (BUY, SELL, atau HOLD) beserta level Stop-Loss dan Take-Profit yang direkomendasikan.

Jawablah dengan gaya bahasa seorang Data Scientist yang objektif dan berbasis angka murni. Ini hanya untuk tujuan simulasi dan riset edukasi."
    """
    
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
