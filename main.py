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

# Interval survei pasar (dalam jam) - Default: setiap 12 jam
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
# 5. ANALISIS DENGAN GOOGLE GEMINI API
# ---------------------------------------------------------
def analyze_crypto_with_gemini(market_data):
    """Mengirim data pasar ke Gemini API untuk dievaluasi"""
    if not GEMINI_API_KEY:
        return "⚠️ *Error*: GEMINI_API_KEY belum dikonfigurasi di Environment Variables!"
        
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    system_prompt = """ roa-effect-within-stocks.py
12-month-cycle-in-cross-section-of-stocks-returns.py
52-weeks-high-effect-in-stocks.py
accrual-anomaly.py
asset-class-momentum-rotational-system.py
asset-class-trend-following.py
asset-growth-effect.py
betting-against-beta-factor-in-country-equity-indexes.py
betting-against-beta-factor-in-stocks.py
combining-fundamental-fscore-and-equity-short-term-reversals.py
combining-smart-factors-momentum-and-market-portfolio.py
consistent-momentum-strategy.py
crude-oil-predicts-equity-returns.py
currency-momentum-factor.py
currency-value-factor-ppp-strategy.py
dispersion-trading.py
dollar-carry-trade.py
earnings-announcement-premium.py
earnings-announcements-combined-with-stock-repurchases.py
earnings-quality-factor.py
esg-factor-momentum-strategy.py
fed-model.py
fx-carry-trade.py
how-to-use-lexical-density-of-company-filings.py
intraday-seasonality-in-bitcoin.py
january-barometer.py
low-volatility-factor-effect-in-stocks.py
market-sentiment-and-an-overnight-anomaly.py
momentum-and-reversal-combined-with-volatility-effect-in-stocks.py
momentum-effect-in-commodities.py
momentum-factor-and-style-rotation-effect.py
momentum-factor-combined-with-asset-growth-effect.py
momentum-factor-effect-in-stocks.py
momentum-in-mutual-fund-returns.py
option-expiration-week-effect.py
paired-switching.py
pairs-trading-with-country-etfs.py
pairs-trading-with-stocks
payday-anomaly.py
rd-expenditures-and-stock-returns.py
rebalancing-premium-in-cryptocurrencies.py
residual-momentum-factor.py
return-asymmetry-effect-in-commodity-futures.py
reversal-during-earnings-announcements.py
sector-momentum-rotational-system.py
short-interest-effect-long-short-version.py
short-term-reversal-in-stocks.py
short-term-reversal-with-futures.py
skewness-effect-in-commodities.py
small-capitalization-stocks-premium-anomaly.py
soccer-clubs-stocks-arbitrage.py
synthetic-lending-rates-predict-subsequent-market-return.py
term-structure-effect-in-commodities.py
time-series-momentum-effect.py
trading-wti-brent-spread.py
trend-following-effect-in-stocks.py
turn-of-the-month-in-equity-indexes.py
value-and-momentum-factors-across-asset-classes.py
value-book-to-market-factor.py
value-factor-effect-within-countries.py
volatility-risk-premium-effect.py"""
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"Berikut adalah data 20 crypto teratas saat ini dari Binance:\n\n{market_data}\n\nTolong lakukan survei & analisis mendalam.",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
            )
        )
        return response.text
    except Exception as e:
        print(f"[ERROR Gemini API] {e}")
        return f"⚠️ *Gagal melakukan analisis Gemini API:* `{str(e)}`"

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
