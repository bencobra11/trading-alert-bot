import os
import time
import requests
from flask import Flask
from threading import Thread

# --- 1. FLASK WEB SERVER (Agar Render Web Service Tetap Aktif 24/7) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Alert Trading Aktif & Running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- 2. KONFIGURASI DARI ENVIRONMENT VARIABLES ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Pasangan Aset (Default Binance API: BTCUSDT, ETHUSDT, SOLUSDT, dll)
SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
BUY_TARGET = float(os.environ.get("BUY_TARGET", "50000"))   # Target Beli (Support)
SELL_TARGET = float(os.environ.get("SELL_TARGET", "70000"))  # Target Jual (Resistance)
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "60")) # Frekuensi cek harga (detik)

def send_telegram_message(message):
    """Mengirim pesan notifikasi ke Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Telegram Token atau Chat ID belum disetel!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Gagal mengirim pesan Telegram: {e}")

def get_crypto_price(symbol):
    """Mengambil harga real-time gratis dari Binance Public API (Tanpa API Key)"""
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
        res = requests.get(url, timeout=10).json()
        return float(res['price'])
    except Exception as e:
        print(f"Gagal mengambil harga {symbol}: {e}")
        return None

def price_checker_loop():
    """Loop pemonitor harga secara terus-menerus"""
    print("Mulai memantau pasar...")
    send_telegram_message(
        f"🤖 *Bot Trading Alert Aktif!*\n\n"
        f"📊 *Aset:* `{SYMBOL}`\n"
        f"🟢 *Target Beli (<=):* `${BUY_TARGET:,.2f}`\n"
        f"🔴 *Target Jual (>=):* `${SELL_TARGET:,.2f}`\n"
        f"⏱️ *Interval Cek:* `{CHECK_INTERVAL} detik`"
    )
    
    last_alerted_type = None # Menghindari spaming notifikasi berulang kali
    
    while True:
        price = get_crypto_price(SYMBOL)
        if price is not None:
            print(f"[{time.strftime('%H:%M:%S')}] Harga {SYMBOL}: ${price:,.2f}")
            
            # Kondisi ALERT BELI
            if price <= BUY_TARGET and last_alerted_type != "BUY":
                msg = (
                    f"🟢 *ALERT BELI / SUPPORT RECHED!*\n\n"
                    f"Aset: `{SYMBOL}`\n"
                    f"Harga Saat Ini: *${price:,.2f}*\n"
                    f"Target Beli Anda: *${BUY_TARGET:,.2f}*\n\n"
                    f"💡 *Saran:* Cek chart & pertimbangkan open posisi BELI."
                )
                send_telegram_message(msg)
                last_alerted_type = "BUY"
                
            # Kondisi ALERT JUAL
            elif price >= SELL_TARGET and last_alerted_type != "SELL":
                msg = (
                    f"🔴 *ALERT JUAL / RESISTANCE REACHED!*\n\n"
                    f"Aset: `{SYMBOL}`\n"
                    f"Harga Saat Ini: *${price:,.2f}*\n"
                    f"Target Jual Anda: *${SELL_TARGET:,.2f}*\n\n"
                    f"💡 *Saran:* Cek chart & pertimbangkan Take Profit / JUAL."
                )
                send_telegram_message(msg)
                last_alerted_type = "SELL"
                
            # Reset penanda jika harga kembali ke area normal di antara Buy & Sell
            elif BUY_TARGET < price < SELL_TARGET:
                last_alerted_type = None
                
        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    # Jalankan Flask Server di background thread agar Render tidak terputus
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # Jalankan Pemonitor Harga
    price_checker_loop()
