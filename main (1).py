import os
import json
import time
import logging
import requests
import pandas as pd
import ta
import datetime
import matplotlib.pyplot as plt
from binance.client import Client
from dotenv import load_dotenv
import telegram
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Load config
with open("config.json") as f:
    config = json.load(f)

symbols = config["symbols"]
settings = config["settings"]

# Replit secret usage
telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
spreadsheet_id = os.getenv("SPREADSHEET_ID")

# Setup clients
client = Client(api_key, api_secret)
bot = telegram.Bot(token=telegram_bot_token)

scope = ["https://www.googleapis.com/auth/spreadsheets"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
gsheet = gspread.authorize(creds)

# Utility functions
def get_klines(symbol, interval='15m', lookback=100):
    try:
        data = client.get_klines(symbol=symbol, interval=interval, limit=lookback)
        df = pd.DataFrame(data, columns=[
            'timestamp','open','high','low','close','volume','close_time',
            'qav','num_trades','taker_base_vol','taker_quote_vol','ignore'
        ])
        df['close'] = pd.to_numeric(df['close'])
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        df['open'] = pd.to_numeric(df['open'])
        df['volume'] = pd.to_numeric(df['volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logger.error(f"Error fetching klines for {symbol}: {e}")
        return None

def send_telegram_message(message):
    try:
        bot.send_message(chat_id=telegram_chat_id, text=message)
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

def add_indicators(df):
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    df['ema'] = ta.trend.EMAIndicator(df['close'], window=20).ema_indicator()
    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_hist'] = macd.macd_diff()
    return df

def check_signal(symbol):
    try:
        df = get_klines(symbol)
        if df is None:
            return
        df = add_indicators(df)

        last_row = df.iloc[-1]
        close_price = last_row["close"]
        rsi = last_row["rsi"]
        ema = last_row["ema"]
        macd_val = last_row["macd"]
        macd_signal = last_row["macd_signal"]
        macd_hist = last_row["macd_hist"]

        signal = None
        if rsi < 30 and macd_hist > 0 and close_price > ema:
            signal = "BUY"
        elif rsi > 70 and macd_hist < 0 and close_price < ema:
            signal = "SELL"

        logger.info(
            f"{symbol} | Price: {close_price} | RSI: {rsi:.2f} | EMA: {ema:.2f} | "
            f"MACD: {macd_val:.4f} | Signal: {macd_signal:.4f} | Histogram: {macd_hist:.4f}"
        )

        # ⬇️ ADDED: Send all logs & indicators to Telegram
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        summary = (
            f"📊 [{symbol}] Signal Summary:\n\n"
            f"• Price: {close_price:.2f}\n"
            f"• RSI: {rsi:.2f}\n"
            f"• EMA: {ema:.2f}\n"
            f"• MACD: {macd_val:.4f}\n"
            f"• Signal: {macd_signal:.4f}\n"
            f"• Histogram: {macd_hist:.4f}\n\n"
            f"💡 {signal if signal else 'No Trade Signal'}\n"
            f"🕒 {now} IST"
        )

        # Plot chart
        plt.figure(figsize=(10, 5))
        plt.plot(df['timestamp'], df['close'], label='Price')
        plt.plot(df['timestamp'], df['ema'], label='EMA20')
        plt.title(f"{symbol} Price & EMA")
        plt.legend()
        plt.grid()
        filename = f"chart_{symbol}.png"
        plt.savefig(filename)
        plt.close()

        # Send chart & message
        with open(filename, 'rb') as photo:
            bot.send_photo(chat_id=telegram_chat_id, photo=photo, caption=summary)

    except Exception as e:
        logger.error(f"Error processing {symbol}: {e}")

# Main loop
while True:
    for symbol in symbols:
        check_signal(symbol)
    time.sleep(settings.get("loop_interval", 60))  # Adjust loop interval from config
