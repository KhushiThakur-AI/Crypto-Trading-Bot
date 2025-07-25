import time
import json
import logging
import gspread
import requests
import pandas as pd
import ta
import datetime
from binance.client import Client
from binance.enums import *
from google.oauth2 import service_account
import os

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Load config ---
# It's good practice to separate sensitive and non-sensitive config.
# For config.json, keep only non-sensitive settings.
# Sensitive settings like API keys will come from environment variables.
try:
    with open("config.json") as f:
        config = json.load(f)
except FileNotFoundError:
    logging.error("config.json not found. Please ensure it exists in your project directory.")
    exit(1)
except json.JSONDecodeError as e:
    logging.error(f"Error decoding config.json: {e}. Please check your JSON syntax.")
    exit(1)

symbols = config["symbols"]
settings = config["settings"]
telegram_config = config["telegram"] # Renamed to avoid conflict with function name

# --- Load environment variables (Replit secrets) ---
# These values MUST be set in your Replit Secrets (lock icon on the left sidebar)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Note: TELEGRAM_CHAT_ID is read from config.json. If you prefer to move it to secrets,
# you would change `telegram_config["chat_id"]` to `os.getenv("TELEGRAM_CHAT_ID")`
# and add a check for it below.

SPREADSHEET_ID = settings["spreadsheet_id"]

# Get Google Sheets credentials from environment variable
# This assumes you saved the ENTIRE JSON content of your service account key file
# into a Replit Secret named 'GOOGLE_SHEETS_CREDENTIALS'.
GOOGLE_SHEETS_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS")

# Check if essential secrets are available
if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    logging.error("Binance API key or secret not found in environment variables. Please set them in Replit Secrets.")
    exit(1)
if not TELEGRAM_BOT_TOKEN:
    logging.error("Telegram bot token not found in environment variables. Please set it in Replit Secrets.")
    exit(1)
if not GOOGLE_SHEETS_CREDENTIALS_JSON:
    logging.error("Google Sheets credentials JSON not found in environment variables. Please set 'GOOGLE_SHEETS_CREDENTIALS' in Replit Secrets.")
    exit(1)


# Initialize Binance client
try:
    client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
    logging.info("Binance client initialized successfully.")
except Exception as e:
    logging.error(f"Failed to initialize Binance client: {e}. Check your API keys and internet connection.")
    exit(1)

# Send Telegram message
def send_telegram_message(message):
    """Sends a message to the configured Telegram chat."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": telegram_config["chat_id"], # Using chat_id from config.json
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload)
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        logging.info("Telegram message sent successfully.")
    except requests.exceptions.HTTPError as http_err:
        # More specific error handling for HTTP errors from Telegram
        if http_err.response.status_code == 400:
            logging.error(f"Telegram API request failed: 400 Bad Request. This usually means your TELEGRAM_BOT_TOKEN is invalid, or your chat_id ({telegram_config['chat_id']}) is incorrect/the bot hasn't been started in that chat. Error: {http_err.response.text}")
        else:
            logging.error(f"Telegram API HTTP error: {http_err}. Response: {http_err.response.text}")
    except requests.exceptions.ConnectionError as conn_err:
        logging.error(f"Telegram API connection error: {conn_err}. Check your internet connection or Telegram API status.")
    except requests.exceptions.Timeout as timeout_err:
        logging.error(f"Telegram API timeout error: {timeout_err}. The request took too long.")
    except Exception as e:
        logging.error(f"An unexpected error occurred while sending Telegram message: {e}")

# Authenticate Google Sheets
try:
    # Define the scopes explicitly for Google Sheets.
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    # Parse the JSON string from the environment variable into a Python dict
    info_json = json.loads(GOOGLE_SHEETS_CREDENTIALS_JSON)

    credentials = service_account.Credentials.from_service_account_info(
        info_json,
        scopes=SCOPES
    )
    gc = gspread.authorize(credentials)
    sheet_book = gc.open_by_key(SPREADSHEET_ID)
    logging.info("Google Sheets authenticated successfully.")
except Exception as e:
    logging.error(f"Google Sheets authentication failed: {e}")
    logging.error("Make sure:")
    logging.error(f"1. The Google Sheets API is enabled in your Google Cloud Project (project ID: {info_json.get('project_id', 'N/A')}).")
    logging.error(f"2. Your service account ({info_json.get('client_email', 'N/A')}) has the correct permissions (Editor/Owner) AND is shared with the specific Google Sheet (ID: {SPREADSHEET_ID}).")
    logging.error("3. The 'GOOGLE_SHEETS_CREDENTIALS' secret in Replit contains the complete, valid JSON content of your service account key file.")
    logging.error(f"Error details: {e}")
    exit(1)

# Calculate indicators
def calculate_indicators(df):
    """
    Calculates EMA, RSI, MACD, and MACD Signal for the given DataFrame.
    Handles potential non-numeric data and ensures sufficient data for calculations.
    """
    # Ensure 'close' column is numeric and handle potential non-numeric values
    df["close"] = pd.to_numeric(df["close"], errors='coerce')

    # Drop rows where 'close' became NaN after conversion, as these cannot be used for indicators
    df.dropna(subset=['close'], inplace=True) 

    # MACD typically needs more data than RSI/EMA (e.g., 26 periods for the longer EMA in MACD calculation)
    # A safe minimum for MACD to have non-NaN values at the end is around 34 periods.
    min_periods_for_all_indicators = 34 

    if len(df) < min_periods_for_all_indicators:
        logging.warning(f"Not enough clean data points ({len(df)}) to calculate all indicators. Need at least {min_periods_for_all_indicators} periods. Indicators will be NaN for this cycle.")
        # Assign pd.NA (Pandas Not Available) for consistency
        df["EMA"] = pd.NA 
        df["RSI"] = pd.NA
        df["MACD"] = pd.NA
        df["MACD_signal"] = pd.NA
        return df

    # Calculate indicators
    df["EMA"] = ta.trend.ema_indicator(df["close"], window=14)
    df["RSI"] = ta.momentum.rsi(df["close"], window=14)
    df["MACD"] = ta.trend.macd(df["close"]) # Corrected call: this directly returns the MACD line
    df["MACD_signal"] = ta.trend.macd_signal(df["close"]) # Corrected call: this directly returns the MACD Signal line

    # After calculation, drop any rows where the *latest* indicator values are NaN.
    # This is crucial because ta.trend functions will put NaNs at the beginning of the series
    # where there isn't enough historical data to compute them. We only care about the latest values for signals.
    df.dropna(subset=["EMA", "RSI", "MACD", "MACD_signal"], inplace=True)

    return df

# Buy signal
def should_buy(df, rsi_buy_threshold):
    """
    Determines if a buy signal is present based on RSI, MACD, and EMA.
    Checks for NaN values in latest indicators before comparison.
    """
    # Ensure there's at least one row after indicator calculation and NaN dropping
    if df.empty:
        logging.warning("DataFrame is empty after indicator calculation and NaN removal. Cannot check buy signal.")
        return False

    # Explicitly check if the latest indicator values are NaN.
    # If any of the required latest indicator values are NaN, we cannot form a signal.
    if pd.isna(df["RSI"].iloc[-1]) or \
       pd.isna(df["MACD"].iloc[-1]) or \
       pd.isna(df["MACD_signal"].iloc[-1]) or \
       pd.isna(df["EMA"].iloc[-1]):
        logging.warning("Latest indicator values are NaN. Skipping buy signal check.")
        return False

    return (
        df["RSI"].iloc[-1] < rsi_buy_threshold and
        df["MACD"].iloc[-1] > df["MACD_signal"].iloc[-1] and
        df["close"].iloc[-1] > df["EMA"].iloc[-1]
    )

# Sell signal
def should_sell(df, rsi_sell_threshold):
    """
    Determines if a sell signal is present based on RSI, MACD, and EMA.
    Checks for NaN values in latest indicators before comparison.
    """
    # Ensure there's at least one row after indicator calculation and NaN dropping
    if df.empty:
        logging.warning("DataFrame is empty after indicator calculation and NaN removal. Cannot check sell signal.")
        return False

    # Explicitly check if the latest indicator values are NaN.
    if pd.isna(df["RSI"].iloc[-1]) or \
       pd.isna(df["MACD"].iloc[-1]) or \
       pd.isna(df["MACD_signal"].iloc[-1]) or \
       pd.isna(df["EMA"].iloc[-1]):
        logging.warning("Latest indicator values are NaN. Skipping sell signal check.")
        return False

    return (
        df["RSI"].iloc[-1] > rsi_sell_threshold or
        df["MACD"].iloc[-1] < df["MACD_signal"].iloc[-1] or
        df["close"].iloc[-1] < df["EMA"].iloc[-1]
    )

# Place trade (simulated/paper)
def place_trade(symbol, action, price, reason="N/A"):
    """
    Simulates placing a trade and logs it to console, Telegram, and Google Sheet.
    Includes a 'reason' for logging.
    """
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"<b>{action}</b> {symbol} at ${price:.2f} (Reason: {reason})"
    logging.info(message)
    send_telegram_message(message)

    try:
        # Check if worksheet exists, create if not
        try:
            ws = sheet_book.worksheet(symbol)
        except gspread.exceptions.WorksheetNotFound:
            logging.info(f"Creating new worksheet for {symbol} in Google Sheet.")
            ws = sheet_book.add_worksheet(title=symbol, rows=1000, cols=10)
            ws.append_row(["Time", "Symbol", "Action", "Price", "Reason"]) # Added 'Reason' header
        except Exception as e:
            logging.error(f"Error accessing or creating worksheet for {symbol}: {e}")
            return

    except Exception as e:
        logging.error(f"Critical error during worksheet access/creation for {symbol}: {e}")
        return

    try:
        ws.append_row([now, symbol, action, price, reason]) # Added 'reason' to appended row
        logging.info(f"Trade logged to Google Sheet for {symbol}.")
    except Exception as e:
        logging.error(f"Error appending row to Google Sheet for {symbol}: {e}")


# Main bot loop
def run_bot():
    """Main loop for the crypto trading bot."""
    logging.info("Starting crypto bot main loop.")
    while True:
        for symbol_name, symbol_data in symbols.items():
            try:
                logging.info(f"Fetching data for {symbol_name}")
                # Fetch klines data from Binance
                # limit=100 provides enough data for indicators to be non-NaN at the end
                klines = client.get_klines(symbol=symbol_name, interval=Client.KLINE_INTERVAL_15MINUTE, limit=100)

                # Convert klines to DataFrame
                df = pd.DataFrame(klines, columns=[
                    "timestamp", "open", "high", "low", "close", "volume",
                    "close_time", "quote_asset_volume", "number_of_trades",
                    "taker_buy_base", "taker_buy_quote", "ignore"
                ])

                # Calculate indicators
                df = calculate_indicators(df)

                # Get the latest close price. Ensure df is not empty after cleaning.
                if df.empty:
                    logging.warning(f"No valid data remaining for {symbol_name} after cleaning. Skipping signal check.")
                    continue # Skip to next symbol

                price = df["close"].iloc[-1]

                # Get symbol-specific thresholds from config
                rsi_buy_threshold = symbol_data["rsi_buy_threshold"]
                rsi_sell_threshold = symbol_data["rsi_sell_threshold"]

                # Determine signal reasons for logging
                buy_signal_reason = []
                sell_signal_reason = []

                # Check individual buy conditions and add to reason list
                # Ensure indicators are not NaN before checking conditions for reasons
                if not pd.isna(df["RSI"].iloc[-1]) and df["RSI"].iloc[-1] < rsi_buy_threshold:
                    buy_signal_reason.append(f"RSI({df['RSI'].iloc[-1]:.2f}) < {rsi_buy_threshold}")
                if not pd.isna(df["MACD"].iloc[-1]) and not pd.isna(df["MACD_signal"].iloc[-1]) and df["MACD"].iloc[-1] > df["MACD_signal"].iloc[-1]:
                    buy_signal_reason.append(f"MACD({df['MACD'].iloc[-1]:.2f}) > MACD_Signal({df['MACD_signal'].iloc[-1]:.2f})")
                if not pd.isna(df["EMA"].iloc[-1]) and df["close"].iloc[-1] > df["EMA"].iloc[-1]:
                    buy_signal_reason.append(f"Close({df['close'].iloc[-1]:.2f}) > EMA({df['EMA'].iloc[-1]:.2f})")

                # Check individual sell conditions and add to reason list
                if not pd.isna(df["RSI"].iloc[-1]) and df["RSI"].iloc[-1] > rsi_sell_threshold:
                    sell_signal_reason.append(f"RSI({df['RSI'].iloc[-1]:.2f}) > {rsi_sell_threshold}")
                if not pd.isna(df["MACD"].iloc[-1]) and not pd.isna(df["MACD_signal"].iloc[-1]) and df["MACD"].iloc[-1] < df["MACD_signal"].iloc[-1]:
                    sell_signal_reason.append(f"MACD({df['MACD'].iloc[-1]:.2f}) < MACD_Signal({df['MACD_signal'].iloc[-1]:.2f})")
                if not pd.isna(df["EMA"].iloc[-1]) and df["close"].iloc[-1] < df["EMA"].iloc[-1]:
                    sell_signal_reason.append(f"Close({df['close'].iloc[-1]:.2f}) < EMA({df['EMA'].iloc[-1]:.2f})")


                if should_buy(df, rsi_buy_threshold):
                    place_trade(symbol_name, "BUY", price, reason=" & ".join(buy_signal_reason))
                elif should_sell(df, rsi_sell_threshold):
                    place_trade(symbol_name, "SELL", price, reason=" | ".join(sell_signal_reason)) # Use OR for sell reasons
                else:
                    logging.info(f"No valid signal for {symbol_name} at price ${price:.2f}")

            except Exception as e:
                logging.error(f"Error processing {symbol_name}: {e}")

        # Wait for the next interval
        interval_seconds = settings.get("interval", 900)
        logging.info(f"Waiting for {interval_seconds} seconds before next cycle...")
        time.sleep(interval_seconds)

if __name__ == "__main__":
    # Send initial message when the bot starts
    send_telegram_message("✅ Crypto Bot is now running.")
    run_bot()
