import os
import time
import json
import gspread
import requests
import pandas as pd
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from binance.client import Client
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import BollingerBands
import mplfinance as mpf

# === 🔐 Load config.json
with open("config.json") as f:
    config = json.load(f)

SYMBOLS = config["symbols"]
PERCENT_PER_TRADE = config["settings"]["percent_per_trade"]  # not used now, replaced by dynamic allocation
MIN_TRADE_USD = config["settings"]["min_trade_usd"]          # used only as fallback
DAILY_LOSS_LIMIT = config["settings"].get("daily_loss_limit", 20)

# === 🔐 Load credentials from Replit secrets
API_KEY = os.environ["BINANCE_API_KEY"]
API_SECRET = os.environ["BINANCE_API_SECRET"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# === 🔗 Binance Testnet & Sheets Setup
client = Client(API_KEY, API_SECRET)
client.API_URL = 'https://testnet.binance.vision/api'

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("google_credentials.json", scope)
sheet_client = gspread.authorize(creds)
sheet_book = sheet_client.open("CryptoBotLogs")

# === 📁 Ensure Tabs Exist
def ensure_tabs_exist():
    existing = [ws.title for ws in sheet_book.worksheets()]
    for symbol in SYMBOLS:
        if symbol not in existing:
            ws = sheet_book.add_worksheet(title=symbol, rows="1000", cols="10")
            ws.append_row(["Time", "Symbol", "Action", "Price", "Quantity", "Reason", "P&L"])
    if "DailySummary" not in existing:
        ws = sheet_book.add_worksheet(title="DailySummary", rows="100", cols="10")
        ws.append_row(["Coin", "Invested", "Trades", "Profit", "Loss", "Net P&L"])

# === 💰 Get USDT Balance
def get_usdt_balance():
    try:
        balance = client.get_asset_balance(asset='USDT')
        return float(balance['free'])
    except Exception as e:
        print(f"❌ Balance error: {e}")
        return 0

# === 📦 Fetch Klines
def fetch_klines(symbol, interval='15m', lookback=100):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=lookback)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_volume', 'taker_buy_quote_volume', 'ignore'
        ])
        df = df.astype(float)
        return df
    except Exception as e:
        print(f"❌ Kline Error for {symbol}: {e}")
        return None

# === 📈 Check Signal
def check_signal(df):
    try:
        rsi = RSIIndicator(df['close']).rsi().iloc[-1]
        macd = MACD(df['close']).macd().iloc[-1]
        ema = EMAIndicator(df['close'], window=20).ema_indicator().iloc[-1]
        close = df['close'].iloc[-1]
        adx = ADXIndicator(df['high'], df['low'], df['close'], window=14).adx().iloc[-1]
        bb = BollingerBands(df['close'], window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]

        score = 0
        if rsi < 30: score += (30 - rsi)
        if macd > 0: score += macd * 5
        if close > ema: score += 3
        if adx > 20: score += (adx - 20)

        details = f"RSI={rsi:.1f}, MACD={macd:.3f}, EMA={ema:.2f}, ADX={adx:.1f}, Close={close:.2f}"

        if rsi < 30 and close <= bb_lower and macd > 0 and close > ema and adx > 20:
            return "BUY", round(score, 2), details

        score = 0
        if rsi > 70: score += (rsi - 70)
        if macd < 0: score += abs(macd) * 5
        if close < ema: score += 3
        if adx > 20: score += (adx - 20)

        details = f"RSI={rsi:.1f}, MACD={macd:.3f}, EMA={ema:.2f}, ADX={adx:.1f}, Close={close:.2f}"

        if rsi > 70 and close >= bb_upper and macd < 0 and close < ema and adx > 20:
            return "SELL", round(score, 2), details

        return "HOLD", 0, ""
    except Exception as e:
        print(f"❌ Signal error: {e}")
        return "HOLD", 0, ""

# === 📤 Telegram
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        requests.post(url, data=data)
    except Exception as e:
        print(f"❌ Telegram error: {e}")

# === ✅ Log Trade
def log_trade(symbol, action, price, qty, reason):
    try:
        ws = sheet_book.worksheet(symbol)
        ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), symbol, action, price, qty, reason, 0])
    except Exception as e:
        print(f"❌ Log error: {e}")

# === 🧮 Daily Loss Guard
def check_daily_loss_guard():
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        total_loss = 0
        for symbol in SYMBOLS:
            ws = sheet_book.worksheet(symbol)
            records = ws.get_all_values()[1:]
            for row in records:
                if len(row) < 7 or not row[0].startswith(today):
                    continue
                pnl = float(row[6]) if row[6] else 0
                if pnl < 0:
                    total_loss += abs(pnl)
        print(f"🔒 Daily Loss So Far: ${total_loss:.2f}")
        return total_loss > DAILY_LOSS_LIMIT
    except Exception as e:
        print(f"❌ Error checking daily loss: {e}")
        return False

# === 🚀 Start Bot
ensure_tabs_exist()

last_trade_time = {}
last_prices = {}
cooldown_minutes = 30

while True:
    if check_daily_loss_guard():
        send_telegram("🚫 Trading halted for today. Daily loss limit exceeded.")
        print("🚫 Max loss reached. Sleeping until next day...")
        time.sleep(3600)
        continue

    usdt_balance = get_usdt_balance()
    signal_candidates = []

    for symbol in SYMBOLS:
        df = fetch_klines(symbol)
        if df is None:
            continue
        signal, score, reason = check_signal(df)
        if signal in ["BUY", "SELL"]:
            signal_candidates.append((symbol, signal, df, score, reason))

    top_signals = sorted(signal_candidates, key=lambda x: x[3], reverse=True)[:3]

    if top_signals:
        num_signals = len(top_signals)
        if num_signals == 1:
            allocation_pct = 0.30
        elif num_signals == 2:
            allocation_pct = 0.25
        else:
            allocation_pct = 0.20

        allocated_per_trade = round(usdt_balance * allocation_pct, 2)

        for symbol, signal, df, score, reason in top_signals:
            now = datetime.now()
            last_time = last_trade_time.get(symbol)
            if last_time and (now - last_time).total_seconds() < cooldown_minutes * 60:
                print(f"⏱ {symbol} cooling down, skipping...")
                continue

            price = df['close'].iloc[-1]
            last_price = last_prices.get(symbol)
            if last_price and abs(price - last_price) < 0.3:
                print(f"⚠️ Duplicate price detected for {symbol}, skipping trade.")
                continue

            qty = round(allocated_per_trade / price, 6)
            if allocated_per_trade >= MIN_TRADE_USD:
                send_telegram(f"{'📈' if signal == 'BUY' else '📉'} {signal} {symbol} @ ${price:.2f} | Qty: {qty}")
                send_telegram(f"📊 Indicators: {reason}")
                log_trade(symbol, signal, price, qty, reason)

                cfg = SYMBOLS[symbol]
                sl_pct = cfg.get("sl", 0.02)
                tp_pct = cfg.get("tp", 0.05)
                tsl_pct = cfg.get("tsl", 0.03)

                stop_loss = round(price * (1 - sl_pct), 2) if signal == "BUY" else round(price * (1 + sl_pct), 2)
                take_profit = round(price * (1 + tp_pct), 2) if signal == "BUY" else round(price * (1 - tp_pct), 2)
                trailing_stop = round(price * (1 - tsl_pct), 2) if signal == "BUY" else round(price * (1 + tsl_pct), 2)

                send_telegram(f"🛡 SL: ${stop_loss} | TP: ${take_profit} | TSL: ${trailing_stop}")
            else:
                print(f"⚠️ Trade too small (${allocated_per_trade}) — skipping {symbol}")
                send_telegram(f"⚠️ Only ${allocated_per_trade} allocated — too small to trade.")

            last_trade_time[symbol] = now
            last_prices[symbol] = price
    else:
        print("🔍 No valid signals this cycle.")

    time.sleep(900)
