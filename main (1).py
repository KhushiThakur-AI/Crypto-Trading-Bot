import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
import time
import logging
import requests
import pandas as pd
import ta
import datetime
import matplotlib.pyplot as plt
import matplotlib.dates as mdates # For better date formatting on charts
from binance.client import Client
from binance.enums import * # Import all enums for Binance constants (SIDE_BUY, ORDER_TYPE_MARKET etc.)
from dotenv import load_dotenv
import telegram
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import math # For math.log10 in get_symbol_info
import tempfile # For creating temporary files for charts

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Load config
CONFIG_FILE = "config.json"
try:
    with open(CONFIG_FILE, "r") as f:
        config_data = json.load(f)
except FileNotFoundError:
    logger.error(f"Error: {CONFIG_FILE} not found. Please create it.")
    exit(1)
except json.JSONDecodeError as e:
    logger.error(f"Error: Could not decode JSON from {CONFIG_FILE}: {e}. Please check its format.")
    exit(1)

SYMBOLS_CONFIG = config_data.get("symbols", {})
SETTINGS = config_data.get("settings", {})
INDICATORS_SETTINGS = SETTINGS.get("indicators", {})

ACTIVE_SYMBOLS = list(SYMBOLS_CONFIG.keys())
logger.info(f"Active Symbols configured: {ACTIVE_SYMBOLS}")

# Replit secret usage
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
# Using SPREADSHEET_ID from config.json settings now
SPREADSHEET_ID_FROM_CONFIG = SETTINGS.get("spreadsheet_id")

if not all([BINANCE_API_KEY, BINANCE_API_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
    logger.error("Error: One or more Replit Secrets (BINANCE_API_KEY, BINANCE_API_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) are not set. Please set them in Replit.")
    exit(1)

# Setup clients
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)

# Google Sheets setup
gsheet = None
try:
    if SPREADSHEET_ID_FROM_CONFIG:
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        # Ensure 'credentials.json' is in the root directory for Replit
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        gsheet = gspread.authorize(creds)
        logger.info("Google Sheets connected successfully.")
    else:
        logger.info("SPREADSHEET_ID not provided in config. Google Sheets integration disabled.")
except Exception as e:
    logger.warning(f"Could not connect to Google Sheets: {e}. Trading logs will not be written to sheet.")
    gsheet = None

# --- Firebase Admin SDK setup for Firestore ---
FIREBASE_CRED_PATH = os.path.join(os.path.dirname(__file__), "firebase_credentials.json")
firebase_db = None

# Initialize Firebase only if not already initialized
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(FIREBASE_CRED_PATH)
        firebase_admin.initialize_app(cred)
        print("✅ Firebase initialized.")
        firebase_db = firestore.client() # Initialize Firestore client after app init
    except Exception as e:
        print(f"❌ Firebase init failed: {e}")
else:
    print("⚠️ Firebase already initialized.")
    firebase_db = firestore.client() # Get Firestore client if already initialized

# Fixed app_id and user_id for standalone script's Firestore paths
APP_ID = "myApp" # You can change this
USER_ID = "user123" # You can change this or generate a UUID
# --- End Firebase Admin SDK setup ---


# --- Utility functions ---
def get_klines(symbol, interval=SETTINGS.get("timeframe", "15m"), lookback=SETTINGS.get("lookback", 250)):
    """
    Fetches klines data for a given symbol and interval.
    The 'lookback' parameter is now dynamically read from SETTINGS in config.json.
    """
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

def get_latest_price(symbol):
    """Fetches the current ticker price for a given symbol."""
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])
    except Exception as e:
        logger.error(f"Error fetching latest price for {symbol}: {e}")
        return None

def send_telegram_message(message, image_path=None):
    """Sends a message to Telegram, optionally with an image."""
    try:
        if image_path:
            with open(image_path, 'rb') as f:
                bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=f, caption=message)
        else:
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

def add_indicators(df):
    """Adds technical indicators to the DataFrame based on settings."""
    if INDICATORS_SETTINGS.get("rsi_enabled", False):
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=INDICATORS_SETTINGS.get("rsi_period", 14)).rsi()
    else:
        df['rsi'] = None

    if INDICATORS_SETTINGS.get("ema_enabled", False):
        df['ema_fast'] = ta.trend.EMAIndicator(df['close'], window=INDICATORS_SETTINGS.get("ema_fast", 50)).ema_indicator()
        df['ema_slow'] = ta.trend.EMAIndicator(df['close'], window=INDICATORS_SETTINGS.get("ema_slow", 200)).ema_indicator()
    else:
        df['ema_fast'] = None
        df['ema_slow'] = None

    if INDICATORS_SETTINGS.get("macd_enabled", False):
        macd = ta.trend.MACD(
            close=df['close'],
            window_fast=INDICATORS_SETTINGS.get("macd_fast", 12),
            window_slow=INDICATORS_SETTINGS.get("macd_slow", 26),
            window_sign=INDICATORS_SETTINGS.get("macd_signal", 9)
        )
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_hist'] = macd.macd_diff()
    else:
        df['macd'] = None
        df['macd_signal'] = None
        df['macd_hist'] = None

    if INDICATORS_SETTINGS.get("bollinger_enabled", False):
        bollinger = ta.volatility.BollingerBands(
            close=df['close'],
            window=INDICATORS_SETTINGS.get("bollinger_period", 20),
            window_dev=INDICATORS_SETTINGS.get("bollinger_std", 2)
        )
        df['bb_bbm'] = bollinger.bollinger_mavg()
        df['bb_bbh'] = bollinger.bollinger_hband()
        df['bb_bbl'] = bollinger.bollinger_lband()
    else:
        df['bb_bbm'] = None
        df['bb_bbh'] = None
        df['bb_bbl'] = None

    if INDICATORS_SETTINGS.get("stoch_rsi_enabled", False):
        stoch_rsi = ta.momentum.StochRSIIndicator(
            close=df['close'],
            window=INDICATORS_SETTINGS.get("stoch_rsi_period", 14),
        )
        df['stoch_rsi_k'] = stoch_rsi.stochrsi_k()
        df['stoch_rsi_d'] = stoch_rsi.stochrsi_d()
    else:
        df['stoch_rsi_k'] = None
        df['stoch_rsi_d'] = None

    return df

def get_symbol_info(symbol):
    """Fetches symbol exchange information for precision, minQty, and minNotional."""
    try:
        info = client.get_symbol_info(symbol)
        if not info:
            logger.error(f"Could not get symbol info for {symbol}")
            return None

        price_precision = 0
        quantity_precision = 0
        min_notional = 0.0
        min_qty = 0.0

        for f in info['filters']:
            if f['filterType'] == 'PRICE_FILTER':
                price_precision = int(round(-math.log10(float(f['tickSize']))))
            elif f['filterType'] == 'LOT_SIZE':
                quantity_precision = int(round(-math.log10(float(f['stepSize']))))
                min_qty = float(f['minQty'])
            elif f['filterType'] == 'MIN_NOTIONAL':
                min_notional = float(f['minNotional'])

        return {
            'pricePrecision': price_precision,
            'quantityPrecision': quantity_precision,
            'minNotional': min_notional,
            'minQty': min_qty
        }
    except Exception as e:
        logger.error(f"Error getting symbol info for {symbol}: {e}")
        return None

def generate_chart(df, symbol, timeframe, indicator_settings):
    """
    Generates a Matplotlib chart of price action and selected indicators.
    Saves the chart to a temporary file and returns its path.
    """
    if df.empty:
        logger.warning(f"Cannot generate chart for {symbol}: DataFrame is empty.")
        return None

    # Use a temporary file to save the chart
    temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    image_path = temp_file.name
    temp_file.close() # Close the file handle as matplotlib will open it

    fig, axes = plt.subplots(nrows=3, ncols=1, figsize=(12, 10), sharex=True,
                             gridspec_kw={'height_ratios': [3, 1, 1]}) # Price, RSI, MACD

    # Plot Price (Candlestick would be better, but for simplicity, using close line)
    axes[0].plot(df['timestamp'], df['close'], label='Close Price', color='blue')
    if indicator_settings.get("ema_enabled", False) and 'ema_fast' in df.columns and 'ema_slow' in df.columns:
        axes[0].plot(df['timestamp'], df['ema_fast'], label=f'EMA {indicator_settings.get("ema_fast", 50)}', color='orange')
        axes[0].plot(df['timestamp'], df['ema_slow'], label=f'EMA {indicator_settings.get("ema_slow", 200)}', color='purple')
    if indicator_settings.get("bollinger_enabled", False) and 'bb_bbm' in df.columns:
        axes[0].plot(df['timestamp'], df['bb_bbm'], label='BB Middle', color='green', linestyle='--')
        axes[0].plot(df['timestamp'], df['bb_bbh'], label='BB Upper', color='red', linestyle=':')
        axes[0].plot(df['timestamp'], df['bb_bbl'], label='BB Lower', color='red', linestyle=':')

    axes[0].set_title(f'{symbol} Price Chart ({timeframe})')
    axes[0].set_ylabel('Price')
    axes[0].legend()
    axes[0].grid(True)

    # Plot RSI
    if indicator_settings.get("rsi_enabled", False) and 'rsi' in df.columns:
        axes[1].plot(df['timestamp'], df['rsi'], label='RSI', color='green')
        axes[1].axhline(70, color='red', linestyle='--', alpha=0.7)
        axes[1].axhline(30, color='red', linestyle='--', alpha=0.7)
        axes[1].set_title('RSI')
        axes[1].set_ylabel('RSI')
        axes[1].set_ylim(0, 100)
        axes[1].grid(True)
    else:
        fig.delaxes(axes[1]) # Remove unused subplot

    # Plot MACD
    if indicator_settings.get("macd_enabled", False) and 'macd' in df.columns:
        axes[2].plot(df['timestamp'], df['macd'], label='MACD', color='blue')
        axes[2].plot(df['timestamp'], df['macd_signal'], label='Signal', color='red')
        axes[2].bar(df['timestamp'], df['macd_hist'], label='Histogram', color='gray', alpha=0.7)
        axes[2].set_title('MACD')
        axes[2].set_ylabel('Value')
        axes[2].legend()
        axes[2].grid(True)
    else:
        fig.delaxes(axes[2]) # Remove unused subplot

    # Format x-axis dates
    fig.autofmt_xdate()
    # Ensure all subplots have the same x-axis limits for proper alignment
    axes[0].set_xlim(df['timestamp'].iloc[0], df['timestamp'].iloc[-1])

    plt.tight_layout()
    plt.savefig(image_path)
    plt.close(fig) # Close the figure to free up memory
    return image_path

def format_signal_summary(symbol, timeframe, latest_data, current_price, trade_signal="No Trade Signal"):
    """Formats the signal summary message."""
    rsi_val = f"{latest_data['rsi']:.2f}" if latest_data['rsi'] is not None else "N/A"
    ema_fast_val = f"{latest_data['ema_fast']:.2f}" if latest_data['ema_fast'] is not None else "N/A"
    macd_hist_val = f"{latest_data['macd_hist']:.4f}" if latest_data['macd_hist'] is not None else "N/A"
    stoch_rsi_k_val = f"{latest_data['stoch_rsi_k']:.2f}" if latest_data['stoch_rsi_k'] is not None else "N/A"
    stoch_rsi_d_val = f"{latest_data['stoch_rsi_d']:.2f}" if latest_data['stoch_rsi_d'] is not None else "N/A"

    return (
        f"📊 [{symbol}] Signal Summary ({timeframe})\n\n"
        f"• Price: {current_price:.2f}\n"
        f"• RSI (14): {rsi_val}\n"
        f"• EMA (Fast 50): {ema_fast_val}\n"
        f"• MACD Hist: {macd_hist_val}\n"
        f"• Stoch RSI K/D: {stoch_rsi_k_val}/{stoch_rsi_d_val}\n\n"
        f"• Current Paper Balance: {trade_manager.paper_balance:,.2f} USD\n\n" # Access directly from trade_manager
        f"💡 {trade_signal}"
    )

def format_bot_status(trade_manager, current_prices):
    """Formats the overall bot status message."""
    total_unrealized_pnl, open_positions_summary = trade_manager.get_open_positions_pnl(current_prices)
    current_total_balance = trade_manager.paper_balance + total_unrealized_pnl
    total_realized_pnl = trade_manager.paper_balance - trade_manager.initial_paper_balance

    return (
        f"\n\n📋 Bot Status Update\n\n"
        f"• Mode: {'REAL' if trade_manager.real_mode else 'PAPER'}\n"
        f"• Paper Balance: {trade_manager.paper_balance:,.2f} USD\n"
        f"• Unrealized PnL: {total_unrealized_pnl:,.2f} USD\n"
        f"• Total Effective Balance: {current_total_balance:,.2f} USD\n"
        f"• Total Realized PnL: {total_realized_pnl:,.2f} USD\n"
        f"• Open Positions:\n{open_positions_summary}"
    )


# --- Trade Manager Class ---
class TradeManager:
    """Manages paper and real trades, position tracking, and logging."""
    def __init__(self, client, realtime_mode, paper_balance_initial, trade_amount_usd, symbols_config, gsheet_client, firebase_db_client):
        self.client = client
        self.real_mode = realtime_mode
        self.paper_balance = paper_balance_initial # Managed within class, not global
        self.initial_paper_balance = paper_balance_initial # Store initial balance for total P&L calculation
        self.trade_amount_usd = trade_amount_usd
        self.symbols_config = symbols_config
        # Updated paper_positions structure to include TSL/SL/TP data
        # {symbol: {side: "BUY/SELL", quantity: X, entry_price: Y, stop_loss: Z, take_profit: A, highest_price_since_entry: B, current_trailing_stop_price: C}}
        self.paper_positions = {}
        self.gsheet_client = gsheet_client
        self.spreadsheet_id = SPREADSHEET_ID_FROM_CONFIG # Store spreadsheet ID for internal use

        # Firestore
        self.db = firebase_db_client
        self.app_id = APP_ID
        self.user_id = USER_ID
        self.bot_state_doc_ref = None
        self.trade_history_collection_ref = None

        if self.db:
            # According to STEP 8: artifacts/myApp/users/user123/settings/
            self.bot_state_doc_ref = self.db.collection(f"artifacts/{self.app_id}/users/{self.user_id}/settings").document("bot_state")
            # According to STEP 8: artifacts/myApp/users/user123/trades/
            self.trade_history_collection_ref = self.db.collection(f"artifacts/{self.app_id}/users/{self.user_id}/trades")
            self._load_bot_state() # Load state at startup

        # --- New for Daily Summary & Hourly Summary ---
        self.last_daily_summary_date = datetime.date.today() # Initialize with current date
        self.daily_pnl_accumulator = 0.0
        self.last_hourly_summary_time = datetime.datetime.now() # Initialize for hourly summaries
        # self.hourly_trades_log is removed, will query Firestore for hourly summary
        # --- End New for Daily Summary & Hourly Summary ---

        logger.info(f"TradeManager initialized. Realtime Mode: {self.real_mode}, Paper Balance (Initial): {self.initial_paper_balance:.2f} USD")
        logger.info(f"Current Paper Balance (after load): {self.paper_balance:.2f} USD")


    def _save_bot_state(self):
        """Saves the current bot state (balance, positions) to Firestore."""
        if not self.db or not self.bot_state_doc_ref:
            logger.warning("Firestore client not initialized. Cannot save bot state.")
            return

        try:
            state_data = {
                "paper_balance": self.paper_balance,
                "initial_paper_balance": self.initial_paper_balance,
                "paper_positions": json.dumps(self.paper_positions), # Store positions as JSON string
                "last_updated": firestore.SERVER_TIMESTAMP # Use server timestamp
            }
            self.bot_state_doc_ref.set(state_data)
            logger.debug("Bot state saved to Firestore.")
        except Exception as e:
            logger.error(f"Error saving bot state to Firestore: {e}")

    def _load_bot_state(self):
        """Loads the bot state from Firestore at startup."""
        if not self.db or not self.bot_state_doc_ref:
            logger.warning("Firestore client not initialized. Cannot load bot state.")
            return

        try:
            doc = self.bot_state_doc_ref.get()
            if doc.exists:
                state_data = doc.to_dict()
                self.paper_balance = state_data.get("paper_balance", self.initial_paper_balance)
                self.initial_paper_balance = state_data.get("initial_paper_balance", self.initial_paper_balance)
                # Parse positions from JSON string
                positions_json = state_data.get("paper_positions", "{}")
                self.paper_positions = json.loads(positions_json)
                logger.info("Bot state loaded from Firestore.")
            else:
                logger.info("No existing bot state found in Firestore. Starting with initial balance.")
                self._save_bot_state() # Save initial state
        except Exception as e:
            logger.error(f"Error loading bot state from Firestore: {e}")

    def _log_trade_to_firestore(self, trade_details):
        """Logs individual trade details to a Firestore collection."""
        if not self.db or not self.trade_history_collection_ref:
            logger.warning("Firestore client not initialized. Cannot log trade to Firestore.")
            return

        try:
            # Add server timestamp for accurate ordering and filtering
            trade_details["timestamp_server"] = firestore.SERVER_TIMESTAMP
            self.trade_history_collection_ref.add(trade_details) # Use add() for auto-generated document ID
            logger.debug(f"Trade logged to Firestore: {trade_details['symbol']} {trade_details['type']}")
        except Exception as e:
            logger.error(f"Error logging trade to Firestore: {e}")


    def _format_quantity(self, symbol, quantity):
        """Formats quantity to the correct precision for the symbol."""
        info = get_symbol_info(symbol)
        if info:
            precision = info['quantityPrecision']
            return float(f"{quantity:.{precision}f}")
        return quantity

    def _format_price(self, symbol, price):
        """Formats price to the correct precision for the symbol."""
        info = get_symbol_info(symbol)
        if info:
            precision = info['pricePrecision']
            return float(f"{price:.{precision}f}")
        return price

    def log_trade_to_sheet(self, trade_data):
        """Logs trade details to the configured Google Sheet."""
        if not self.gsheet_client or not self.spreadsheet_id:
            logger.warning("Google Sheet client not initialized or Spreadsheet ID missing. Cannot log trade.")
            return

        try:
            # Open the first sheet (assuming it's the main trade log)
            worksheet = self.gsheet_client.open_by_key(self.spreadsheet_id).sheet1
            worksheet.append_row(trade_data)
            logger.info(f"Trade logged to Google Sheet: {trade_data}")
        except Exception as e:
            logger.error(f"Error logging trade to Google Sheet: {e}")

    def log_daily_summary(self):
        """Logs daily summary of paper trading balance and PnL to Google Sheet and saves bot state."""
        if not self.gsheet_client or not self.spreadsheet_id:
            logger.warning("Google Sheet client not initialized or Spreadsheet ID missing. Cannot log daily summary.")
            return

        current_date = datetime.date.today()
        # Only log if it's a new day or if it's the first run and last_daily_summary_date is still today
        if current_date > self.last_daily_summary_date:
            try:
                # Open the "Summary" sheet
                summary_sheet = self.gsheet_client.open_by_key(self.spreadsheet_id).worksheet("Summary")

                # Log the summary for the *previous* day
                summary_data = [
                    self.last_daily_summary_date.strftime('%Y-%m-%d'),
                    f"{self.paper_balance:.2f}",
                    f"{self.daily_pnl_accumulator:.2f}"
                ]
                summary_sheet.append_row(summary_data)
                logger.info(f"Daily Summary logged: Date: {self.last_daily_summary_date}, Balance: {self.paper_balance:.2f}, Daily PnL: {self.daily_pnl_accumulator:.2f}")

                # Reset daily PnL accumulator for the new day
                self.daily_pnl_accumulator = 0.0
                # Update last summary date to the current date
                self.last_daily_summary_date = current_date
                self._save_bot_state() # Save state after daily summary

            except gspread.exceptions.WorksheetNotFound:
                logger.error("Google Sheet 'Summary' tab not found. Please create a sheet named 'Summary'.")
            except Exception as e:
                logger.error(f"Error logging daily summary to Google Sheet: {e}")

    def get_open_positions_pnl(self, current_prices):
        """
        Calculates the total unrealized P&L for all open paper positions
        and returns a formatted string of individual positions.
        """
        total_unrealized_pnl = 0.0
        positions_summary_lines = []

        if not self.paper_positions:
            return 0.0, "No open positions."

        for symbol, position in self.paper_positions.items():
            if symbol in current_prices:
                current_price = current_prices[symbol]
                unrealized_pnl = (current_price - position["entry_price"]) * position["quantity"]
                total_unrealized_pnl += unrealized_pnl

                positions_summary_lines.append(
                    f"  • {symbol}: Qty {position['quantity']:.4f}, Entry {position['entry_price']:.2f}, "
                    f"Current {current_price:.2f}, PnL {unrealized_pnl:.2f} USD"
                )
            else:
                positions_summary_lines.append(f"  • {symbol}: Current price not available.")

        return total_unrealized_pnl, "\n".join(positions_summary_lines)


    def execute_trade(self, symbol, signal_type, current_price, reason="SIGNAL", indicator_details=None):
        """Executes a trade (real or paper) based on the signal."""
        if indicator_details is None:
            indicator_details = {} # Default empty dict if not provided

        trade_quantity_raw = self.trade_amount_usd / current_price

        symbol_info = get_symbol_info(symbol)
        if not symbol_info:
            logger.error(f"Could not get symbol info for {symbol}. Cannot execute trade.")
            return

        formatted_quantity = self._format_quantity(symbol, trade_quantity_raw)

        # Check minimum quantity
        if formatted_quantity < symbol_info['minQty']:
            logger.warning(f"Trade quantity {formatted_quantity} for {symbol} is less than minimum quantity {symbol_info['minQty']}. Adjusting to min_qty for paper/logging, but might fail real trade.")
            formatted_quantity = symbol_info['minQty']

        # Check minimum notional value
        trade_notional = formatted_quantity * current_price
        if trade_notional < symbol_info['minNotional']:
            logger.warning(f"Trade notional value for {symbol} ({trade_notional:.2f}) is less than minimum notional {symbol_info['minNotional']}. Cannot execute trade.")
            send_telegram_message(f"🚫 Trade Failed for {symbol} ({signal_type}): Notional value too low ({trade_notional:.2f} USD). Min: {symbol_info['minNotional']} USD.")
            return

        # Get symbol specific SL/TP/TSL percentages from config
        symbol_params = self.symbols_config.get(symbol, {})
        sl_percent = symbol_params.get("sl", 0.02) # Default 2%
        tp_percent = symbol_params.get("tp", 0.04) # Default 4%
        tsl_percent = symbol_params.get("tsl", 0.01) # Default 1% trailing distance

        # Common trade data for logging (extended for indicator details)
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        common_trade_log_details = {
            'rsi': indicator_details.get('rsi', 'N/A'),
            'ema_fast': indicator_details.get('ema_fast', 'N/A'),
            'macd_hist': indicator_details.get('macd_hist', 'N/A'),
            'stoch_rsi_k': indicator_details.get('stoch_rsi_k', 'N/A'),
            'stoch_rsi_d': indicator_details.get('stoch_rsi_d', 'N/A'),
            'bb_bbh': indicator_details.get('bb_bbh', 'N/A'),
            'bb_bbl': indicator_details.get('bb_bbl', 'N/A'),
            'bb_bbm': indicator_details.get('bb_bbm', 'N/A')
        }


        if self.real_mode:
            logger.info(f"Attempting REAL {signal_type} order for {symbol} at {current_price:.2f} with quantity {formatted_quantity}")
            try:
                if signal_type == "BUY":
                    order = self.client.create_order(
                        symbol=symbol,
                        side=SIDE_BUY,
                        type=ORDER_TYPE_MARKET,
                        quantity=formatted_quantity
                    )
                elif signal_type == "SELL":
                    order = self.client.create_order(
                        symbol=symbol,
                        side=SIDE_SELL,
                        type=ORDER_TYPE_MARKET,
                        quantity=formatted_quantity
                    )

                trade_message = (
                    f"✅ REAL TRADE EXECUTED! (Reason: {reason})\n"
                    f"Symbol: {symbol}\n"
                    f"Type: {signal_type}\n"
                    f"Order ID: {order['orderId']}\n"
                    f"Executed Qty: {order['executedQty']}\n"
                    f"Price: {order['fills'][0]['price'] if order['fills'] else 'N/A'}\n"
                    f"Status: {order['status']}"
                )
                logger.info(trade_message)
                send_telegram_message(trade_message)

                # Log real trade to sheet (PnL 'N/A' for opens)
                trade_data_sheet = [
                    timestamp,
                    symbol,
                    f"{signal_type} (Real) - {reason}",
                    f"{order['fills'][0]['price'] if order['fills'] else current_price:.2f}",
                    f"{order['executedQty']}",
                    "N/A", # PnL for real trades is calculated later when closing positions
                    reason, # Reason for trade
                ] + list(common_trade_log_details.values()) + ['N/A','N/A','N/A','N/A'] # Add more N/A for position details
                self.log_trade_to_sheet(trade_data_sheet)

                # Log to Firestore
                trade_data_firestore = {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "type": signal_type,
                    "quantity": float(order['executedQty']),
                    "price": float(order['fills'][0]['price']) if order['fills'] else current_price,
                    "pnl": 0.0, # PnL for buy is 0 at entry, for sell it's calculated on close
                    "reason": reason,
                    "indicator_details": common_trade_log_details,
                    "entry_price": float(order['fills'][0]['price']) if order['fills'] else current_price,
                    "sl_price_at_entry": "N/A", # SL/TP/TSL not directly managed by Binance market orders
                    "tp_price_at_entry": "N/A",
                    "tsl_price_at_hit": "N/A",
                    "real_trade": True
                }
                self._log_trade_to_firestore(trade_data_firestore)
                self._save_bot_state() # Save state after real trade

            except Exception as e:
                error_message = f"❌ REAL TRADE FAILED for {symbol} ({signal_type}): {e}"
                logger.error(error_message)
                send_telegram_message(error_message)

        else: # Paper trading mode
            logger.info(f"Executing PAPER {signal_type} order for {symbol} at {current_price:.2f} with quantity {formatted_quantity}. Reason: {reason}")

            if signal_type == "BUY":
                cost = formatted_quantity * current_price
                if self.paper_balance >= cost:
                    self.paper_balance -= cost

                    # Initialize TSL/SL/TP parameters for the new position
                    initial_stop_loss_price = current_price * (1 - sl_percent)
                    initial_take_profit_price = current_price * (1 + tp_percent)
                    initial_trailing_stop_price = current_price * (1 - tsl_percent) # TSL starts below entry

                    self.paper_positions[symbol] = {
                        "side": "BUY",
                        "quantity": formatted_quantity,
                        "entry_price": current_price,
                        "stop_loss": initial_stop_loss_price, # Fixed stop loss
                        "take_profit": initial_take_profit_price, # Fixed take profit
                        "highest_price_since_entry": current_price, # For TSL, tracks peak price
                        "current_trailing_stop_price": initial_trailing_stop_price, # For TSL, the actual stop price
                    }
                    trade_message = (
                        f"📈 PAPER BUY Order Executed! (Reason: {reason})\n"
                        f"Symbol: {symbol}\n"
                        f"Price: {current_price:.2f}\n"
                        f"Quantity: {formatted_quantity}\n"
                        f"Virtual SL: {self.paper_positions[symbol]['stop_loss']:.2f}\n"
                        f"Virtual TP: {self.paper_positions[symbol]['take_profit']:.2f}\n"
                        f"Virtual TSL: {self.paper_positions[symbol]['current_trailing_stop_price']:.2f}\n"
                        f"Remaining Paper Balance: {self.paper_balance:.2f} USD"
                    )
                    logger.info(trade_message)
                    send_telegram_message(trade_message)

                    trade_data_sheet = [
                        timestamp,
                        symbol,
                        f"BUY (Paper)",
                        f"{current_price:.2f}",
                        f"{formatted_quantity}",
                        "N/A", # PnL is N/A for open positions
                        reason, # Reason for trade
                    ] + list(common_trade_log_details.values()) + [
                        f"{current_price:.2f}", # Entry Price for BUY
                        f"{initial_stop_loss_price:.2f}",
                        f"{initial_take_profit_price:.2f}",
                        f"{initial_trailing_stop_price:.2f}"
                    ]
                    self.log_trade_to_sheet(trade_data_sheet)

                    # Log this trade to Firestore
                    trade_data_firestore = {
                        "timestamp": timestamp,
                        "symbol": symbol,
                        "type": "BUY",
                        "quantity": formatted_quantity,
                        "price": current_price,
                        "pnl": 0.0, # PnL for buy is 0 at entry
                        "reason": reason,
                        "indicator_details": common_trade_log_details,
                        "entry_price": current_price,
                        "sl_price_at_entry": initial_stop_loss_price,
                        "tp_price_at_entry": initial_take_profit_price,
                        "tsl_price_at_hit": initial_trailing_stop_price,
                        "real_trade": False
                    }
                    self._log_trade_to_firestore(trade_data_firestore)
                    self._save_bot_state() # Save state after paper trade
                else:
                    message = f"Insufficient paper balance to BUY {symbol}. Needed: {cost:.2f} USD, Have: {self.paper_balance:.2f} USD"
                    logger.warning(message)
                    send_telegram_message(message)

            elif signal_type == "SELL":
                if symbol in self.paper_positions and self.paper_positions[symbol]["side"] == "BUY":
                    position_qty = self.paper_positions[symbol]["quantity"]
                    entry_price = self.paper_positions[symbol]["entry_price"]
                    sl_price_at_entry = self.paper_positions[symbol]["stop_loss"]
                    tp_price_at_entry = self.paper_positions[symbol]["take_profit"]
                    tsl_price_at_hit = self.paper_positions[symbol]["current_trailing_stop_price"] # Capture TSL price when hit

                    revenue = position_qty * current_price
                    profit_loss = (current_price - entry_price) * position_qty
                    self.paper_balance += revenue
                    self.daily_pnl_accumulator += profit_loss # Accumulate daily PnL

                    trade_message = (
                        f"📉 PAPER SELL Order Executed (Closing Position)! (Reason: {reason})\n"
                        f"Symbol: {symbol}\n"
                        f"Close Price: {current_price:.2f}\n"
                        f"Quantity: {position_qty}\n"
                        f"Entry Price: {entry_price:.2f}\n"
                        f"Profit/Loss: {profit_loss:.2f} USD\n"
                        f"New Paper Balance: {self.paper_balance:.2f} USD"
                    )
                    logger.info(trade_message)
                    send_telegram_message(trade_message)

                    trade_data_sheet = [
                        timestamp,
                        symbol,
                        f"SELL (Paper)",
                        f"{current_price:.2f}",
                        f"{position_qty}",
                        f"{profit_loss:.2f}", # PnL is now calculated for closing position
                        reason, # Reason for trade
                    ] + list(common_trade_log_details.values()) + [
                        f"{entry_price:.2f}", # Entry Price for SELL (closing the BUY)
                        f"{sl_price_at_entry:.2f}",
                        f"{tp_price_at_entry:.2f}",
                        f"{tsl_price_at_hit:.2f}"
                    ]
                    self.log_trade_to_sheet(trade_data_sheet)

                    # Log this trade to Firestore
                    trade_data_firestore = {
                        "timestamp": timestamp,
                        "symbol": symbol,
                        "type": "SELL",
                        "quantity": position_qty,
                        "price": current_price,
                        "pnl": profit_loss,
                        "reason": reason,
                        "indicator_details": common_trade_log_details,
                        "entry_price": entry_price, # The original entry price of the position
                        "sl_price_at_entry": sl_price_at_entry,
                        "tp_price_at_entry": tp_price_at_entry,
                        "tsl_price_at_hit": tsl_price_at_hit,
                        "real_trade": False
                    }
                    self._log_trade_to_firestore(trade_data_firestore)

                    del self.paper_positions[symbol] # Remove position after closing
                    self.daily_pnl_accumulator += profit_loss # Also add to daily PnL accumulator
                    self._save_bot_state() # Save state after paper trade

                else:
                    logger.warning(f"Attempted to SELL {symbol} but no BUY position found or side mismatch.")
                    send_telegram_message(f"🚫 Failed to SELL {symbol}: No active BUY position to close.")

    def check_and_manage_positions(self, current_prices):
        """
        Manages open paper positions:
        - Updates highest price since entry for TSL.
        - Updates trailing stop loss price.
        - Checks for Stop Loss, Take Profit, or Trailing Stop Loss hits.
        - Executes SELL orders for hits.
        """
        positions_to_close = []

        for symbol, position in list(self.paper_positions.items()): # Iterate on a copy if modifying during loop
            if symbol not in current_prices:
                logger.warning(f"Skipping position management for {symbol}: current price not available.")
                continue

            current_price = current_prices[symbol]
            entry_price = position['entry_price']
            pos_quantity = position['quantity']

            # Update highest price for TSL
            if current_price > position['highest_price_since_entry']:
                position['highest_price_since_entry'] = current_price
                # Update trailing stop price if the price has moved favorably
                tsl_percent = self.symbols_config.get(symbol, {}).get("tsl", 0.01)
                new_trailing_stop = position['highest_price_since_entry'] * (1 - tsl_percent)
                if new_trailing_stop > position['current_trailing_stop_price']: # Only move TSL up
                    position['current_trailing_stop_price'] = new_trailing_stop
                    logger.debug(f"Updated TSL for {symbol} to {new_trailing_stop:.2f}")

            # Check for close conditions (TP, SL, TSL)
            close_reason = None
            if current_price >= position['take_profit']:
                close_reason = "TAKE_PROFIT"
            elif current_price <= position['stop_loss']:
                close_reason = "STOP_LOSS"
            elif position['current_trailing_stop_price'] and current_price <= position['current_trailing_stop_price']:
                # TSL hit. Check if it's above entry to signify profit protection, or below for dynamic stop loss
                if position['current_trailing_stop_price'] > position['entry_price']:
                    close_reason = "TRAILING_STOP_LOSS (profit protected)"
                else:
                    close_reason = "TRAILING_STOP_LOSS (loss minimized)"

            if close_reason:
                logger.info(f"Position close signal for {symbol} due to {close_reason} at {current_price:.2f}. Entry: {entry_price:.2f}")
                positions_to_close.append((symbol, close_reason))

        # Execute closes outside the loop to avoid RuntimeError: dictionary changed size during iteration
        for symbol, reason in positions_to_close:
            self.execute_trade(symbol, "SELL", current_prices[symbol], reason=reason)

    def run_strategy_for_symbol(self, symbol, df, current_price):
        """
        Implement your trading strategy here.
        This function will be called for each active symbol.
        """
        # Ensure DataFrame has enough data for indicators
        if df is None or len(df) < max(INDICATORS_SETTINGS.values()): # Adjust based on your max indicator period
            logger.warning(f"Not enough data for {symbol} to calculate indicators.")
            return "No Trade Signal" # Return signal status

        # Get the latest row with indicators
        latest_data = df.iloc[-1]

        # Extract indicator values for logging
        indicator_details = {
            'rsi': latest_data['rsi'],
            'ema_fast': latest_data['ema_fast'],
            'macd_hist': latest_data['macd_hist'],
            'stoch_rsi_k': latest_data['stoch_rsi_k'],
            'stoch_rsi_d': latest_data['stoch_rsi_d'],
            'bb_bbh': latest_data['bb_bbh'],
            'bb_bbl': latest_data['bb_bbl'],
            'bb_bbm': latest_data['bb_bbm']
        }

        # --- Example Strategy Logic (PLACE YOUR STRATEGY HERE) ---
        # This is a placeholder. Replace with your actual trading logic.

        # Example: Simple RSI Strategy
        rsi_buy_threshold = SYMBOLS_CONFIG.get(symbol, {}).get("rsi_buy_threshold", 30)
        rsi_sell_threshold = SYMBOLS_CONFIG.get(symbol, {}).get("rsi_sell_threshold", 70)

        has_position = symbol in self.paper_positions

        trade_signal = "No Trade Signal"

        if not has_position:
            # BUY condition: RSI below threshold
            if latest_data['rsi'] is not None and latest_data['rsi'] < rsi_buy_threshold:
                logger.info(f"Strategy: BUY signal for {symbol} (RSI: {latest_data['rsi']:.2f})")
                self.execute_trade(symbol, "BUY", current_price, reason="RSI_BUY_SIGNAL", indicator_details=indicator_details)
                trade_signal = "BUY Signal"
        else:
            # SELL condition: RSI above threshold (to close an existing BUY position)
            if latest_data['rsi'] is not None and latest_data['rsi'] > rsi_sell_threshold:
                logger.info(f"Strategy: SELL signal for {symbol} (RSI: {latest_data['rsi']:.2f})")
                self.execute_trade(symbol, "SELL", current_price, reason="RSI_SELL_SIGNAL", indicator_details=indicator_details)
                trade_signal = "SELL Signal"

        # You would add more complex conditions here combining multiple indicators
        # Example: MACD Crossover, EMA crossover, etc.
        # if latest_data['macd'] > latest_data['macd_signal'] and df.iloc[-2]['macd'] < df.iloc[-2]['macd_signal']:
        #     # Buy signal for MACD crossover
        #     pass
        # --- End Example Strategy Logic ---
        return trade_signal, indicator_details


    def run_trading_cycle(self):
        """
        Executes a single trading cycle: fetches data, runs strategy, manages positions.
        """
        logger.info(f"--- Starting Trading Cycle ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---")

        current_prices = {}
        for symbol in ACTIVE_SYMBOLS:
            price = get_latest_price(symbol)
            if price:
                current_prices[symbol] = price
            else:
                logger.warning(f"Could not get latest price for {symbol}. Skipping this symbol for this cycle.")

        if not current_prices:
            logger.warning("No current prices retrieved for any active symbol. Skipping trading cycle.")
            return

        # 1. Check and manage existing positions first (SL/TP/TSL)
        self.check_and_manage_positions(current_prices)

        # 2. Run strategy for each symbol to potentially open new positions and send Telegram updates
        for symbol in ACTIVE_SYMBOLS:
            df = get_klines(symbol, interval=SETTINGS.get("timeframe", "15m"), lookback=SETTINGS.get("lookback", 250))

            image_path = None
            try:
                if df is not None and not df.empty:
                    df = add_indicators(df)
                    latest_data = df.iloc[-1] if not df.empty else {}

                    # Generate chart
                    image_path = generate_chart(df, symbol, SETTINGS.get("timeframe", "15m"), INDICATORS_SETTINGS)

                    trade_signal_status, indicator_details = "No Trade Signal", {} # Default values
                    if symbol in current_prices:
                        trade_signal_status, indicator_details = self.run_strategy_for_symbol(symbol, df, current_prices[symbol])
                    else:
                        logger.warning(f"Current price not available for {symbol}, skipping strategy.")

                    # Format signal summary
                    signal_summary_message = format_signal_summary(
                        symbol,
                        SETTINGS.get("timeframe", "15m"),
                        latest_data,
                        current_prices.get(symbol, 0.0), # Use .get with default for safety
                        trade_signal=trade_signal_status
                    )
                else:
                    signal_summary_message = f"📊 [{symbol}] Signal Summary ({SETTINGS.get('timeframe', '15m')})\n\n" \
                                             f"• Price: N/A\n" \
                                             f"• Indicators: N/A (Data not available)\n\n" \
                                             f"💡 No Trade Signal (Data Error)"
                    logger.warning(f"Could not retrieve klines for {symbol}, skipping strategy and chart generation.")

                # Format bot status (this will be the same for all symbols in one cycle, but sent per symbol report)
                bot_status_message = format_bot_status(self, current_prices)

                # Combine messages
                final_message = f"{signal_summary_message}\n\n" \
                                f"🕒 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} IST" \
                                f"{bot_status_message}"

                # Send combined message with chart
                send_telegram_message(final_message, image_path=image_path)

            except Exception as e:
                logger.error(f"Error during processing or sending Telegram message for {symbol}: {e}", exc_info=True)
            finally:
                if image_path and os.path.exists(image_path):
                    os.remove(image_path) # Clean up the temporary image file

        # 3. Log daily summaries (if a new day has started)
        self.log_daily_summary()

        # 4. Log hourly summaries (new function to be added if needed, or query Firestore directly)
        self.log_hourly_summary_to_firestore() # This function will be added/implemented below

        logger.info("--- Trading Cycle Completed ---")

    def log_hourly_summary_to_firestore(self):
        """Logs hourly summary of PnL to Firestore."""
        current_time = datetime.datetime.now()
        # Check if an hour has passed since the last summary
        if (current_time - self.last_hourly_summary_time).total_seconds() >= 3600: # 3600 seconds = 1 hour

            # Define the time range for the last hour
            start_of_last_hour = current_time - datetime.timedelta(hours=1)

            if not self.db or not self.trade_history_collection_ref:
                logger.warning("Firestore client not initialized. Cannot log hourly summary to Firestore.")
                return

            try:
                # Fetch trades from the last hour from Firestore
                # Note: This timestamp is a string in your Firestore, so direct comparison might not work perfectly with Firestore's timestamp object.
                # It's better to store timestamp_server as actual Firestore Timestamps.
                # For now, we'll try to filter using the string timestamp, which is less ideal.
                # A better approach would be to convert Firestore's `timestamp_server` to datetime objects for comparison.

                # Fetching the last few hundred trades and filtering locally is okay for moderate volume
                # For very high volume, you'd need a robust Firestore query or a separate hourly summary collection
                docs = self.trade_history_collection_ref.order_by("timestamp_server", direction=firestore.Query.DESCENDING).limit(200).stream()
                hourly_pnl = 0.0
                hourly_trade_count = 0

                for doc in docs:
                    trade_data = doc.to_dict()
                    trade_timestamp_str = trade_data.get('timestamp')
                    if trade_timestamp_str:
                        try:
                            # Convert stored string timestamp to datetime object
                            trade_dt = datetime.datetime.strptime(trade_timestamp_str, '%Y-%m-%d %H:%M:%S')
                            # Check if the trade occurred within the last hour window
                            if start_of_last_hour <= trade_dt <= current_time:
                                pnl = trade_data.get('pnl', 0.0)
                                # Ensure pnl is numeric; handle 'N/A' or similar if present
                                if isinstance(pnl, (int, float)):
                                    hourly_pnl += pnl
                                else:
                                    try:
                                        hourly_pnl += float(pnl) # Try converting if it's a string like "1.23"
                                    except ValueError:
                                        pass # Ignore if PnL can't be converted
                                hourly_trade_count += 1
                        except ValueError:
                            logger.warning(f"Could not parse timestamp string: {trade_timestamp_str}")
                            continue

                # Log to a new collection for hourly summaries
                hourly_summary_ref = self.db.collection(f"artifacts/{self.app_id}/users/{self.user_id}/hourly_summaries")
                summary_data = {
                    "start_time": start_of_last_hour, # Store as Firestore Timestamp
                    "end_time": current_time, # Store as Firestore Timestamp
                    "hourly_pnl": hourly_pnl,
                    "hourly_trade_count": hourly_trade_count,
                    "paper_balance_at_end": self.paper_balance,
                    "last_updated": firestore.SERVER_TIMESTAMP
                }
                hourly_summary_ref.add(summary_data)
                logger.info(f"Hourly summary logged to Firestore: PnL={hourly_pnl:.2f}, Trades={hourly_trade_count}")
                self.last_hourly_summary_time = current_time # Update the last summary time

            except Exception as e:
                logger.error(f"Error logging hourly summary to Firestore: {e}")

# --- Main execution block ---
if __name__ == "__main__":
    # Ensure SETTINGS are correctly populated from config.json
    REALTIME_MODE = SETTINGS.get("realtime_mode", False)
    PAPER_BALANCE_INITIAL = SETTINGS.get("paper_balance_initial", 1000.0)
    TRADE_AMOUNT_USD = SETTINGS.get("trade_amount_usd", 100.0)
    TRADING_INTERVAL_SECONDS = SETTINGS.get("trading_interval_seconds", 300) # Default 5 minutes

    trade_manager = TradeManager(
        client=client,
        realtime_mode=REALTIME_MODE,
        paper_balance_initial=PAPER_BALANCE_INITIAL,
        trade_amount_usd=TRADE_AMOUNT_USD,
        symbols_config=SYMBOLS_CONFIG,
        gsheet_client=gsheet,
        firebase_db_client=firebase_db
    )

    # Main bot loop
    try:
        while True:
            trade_manager.run_trading_cycle()
            logger.info(f"Sleeping for {TRADING_INTERVAL_SECONDS} seconds...")
            time.sleep(TRADING_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Bot stopped manually by KeyboardInterrupt.")
    except Exception as e:
        logger.critical(f"An unhandled error caused the bot to stop: {e}", exc_info=True)
