# 📈 Crypto-Trading-Bot

A real-time, multi-indicator **crypto paper trading bot** built in Python, using the Binance Testnet API.  
This bot monitors selected crypto pairs, detects trading signals using indicators like **RSI, EMA, MACD, ADX**, and **Bollinger Bands**, and sends real-time **Telegram alerts**, with **auto-logging to Google Sheets**.

---
## 🚀 Features

### 📊 Multi-Indicator Strategy
- **RSI** – Overbought/oversold detection
- **MACD** – Momentum shift confirmation
- **EMA** – Trend following
- **ADX** – Trend strength
- **Bollinger Bands** – Volatility breakout

### 🛡 Risk Management
- ✅ Stop Loss (SL)
- ✅ Take Profit (TP)
- ✅ Trailing Stop Loss (TSL)
- ✅ Daily Max Loss Guard
- ✅ Cooldown + Duplicate Trade Blocker

### 🧠 Smart Trade Logic
- Trade Confidence Score (based on multiple indicators)
- Per-coin configuration using `config.json`

### 📤 Telegram Alerts
- 📈 Trade Executed (BUY/SELL)
- 🚨 SL/TP/TSL Triggered
- 💬 Trade Summary (daily/weekly)
- ⚠️ Capital issues / loss guard

### 📄 Google Sheets Logging
- ✅ Trade history
- ✅ P&L tracking
- ✅ Per-symbol worksheets (BTCUSDT, ETHUSDT, etc.)

---

## 🛠 Files & Structure
Crypto-Trading-Bot/
│
├── main.py # Main bot script
├── config.json # SL/TP/TSL settings for each coin
├── requirements.txt # Python libraries
├── charts/ # Optional folder to save trade charts
└── README.md # You're reading it

⚙️ Setup Instructions

### 1. Clone the Repo
git clone https://github.com/KhushiThakur-AI/Crypto-Trading-Bot.git
cd Crypto-Trading-Bot

**2. Install Dependencies**

pip install -r requirements.txt

**3. Configure API Keys**
Rename .env.example → .env
Then fill in your credentials:

Secret
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

**4. Run the Bot**
python main.py

🧠 Skills Demonstrated
✅ Python Development
✅ API Integration (Binance, Telegram, Google Sheets)
✅ Trading Strategy Design
✅ Automation & Alert Systems
✅ Real-world product mindset

📈 Future Plans
📊 Web dashboard (Streamlit)
🧠 AI Signal Scoring
🔄 Real-money toggle
🔔 TradingView webhook triggers
💼 Long-term investment mode (BTC/ETH)

⚠️ Disclaimer
This bot is for educational purposes only.
I am not a financial advisor. Use at your own risk.
Never use real money without fully understanding what the code does.

**🙌 Created by @KhushiThakur-AI**
