# 📈 Crypto-Trading-Bot
![Python](https://img.shields.io/badge/Python-3.10-blue.svg)
![Status](https://img.shields.io/badge/Status-Active-success.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Last Commit](https://img.shields.io/github/last-commit/KhushiThakur-AI/Crypto-Trading-Bot)
![Repo Size](https://img.shields.io/github/repo-size/KhushiThakur-AI/Crypto-Trading-Bot) 

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

## 🧩 Feature Roadmap

| 📌 Feature                   | 🛠️ Description                                                | 🎯 Why It's Important                         | ✅ Priority     | 🚦 Status   |
|----------------------------|---------------------------------------------------------------|----------------------------------------------|----------------|-------------|
| Add More Indicators        | Add 2 advanced indicators to support RSI, EMA, MACD           | Improve accuracy, confirm signals            | ✅ Immediate    | ✅ DONE      |
| Real Balance Awareness     | Bot checks USDT wallet before trading                         | Prevents over-trading, protects capital      | ✅ Immediate    | ✅ DONE      |
| Smart Capital Allocation   | Use % of total balance per trade (not fixed $15)              | Adapts to wallet size, safer scaling         | ✅ Immediate    | ✅ DONE      |
| Diversification Logic      | Invest in 2–3 strongest signals across different coins        | Lowers risk, increases opportunity           | ✅ Immediate    | ✅ DONE      |
| Trailing Stop Loss (TSL)   | Dynamically lock in profits as price rises                    | Avoids profit reversal                       | ✅ Next Step    | ✅ DONE      |
| Daily Max Loss Guard       | If total loss > $X in a day, stop trading                     | Avoids wipeouts on bad days                  | ✅ Next Step    | ✅ DONE      |
| Trade Confidence Scoring   | Only trade if multiple indicators confirm                     | Filters out false signals                    | 🔄 Optional     |N/A |
| Trade Journal Logging      | Log reasons for each trade in detail                          | For audit, review, debugging                 | ✅ Recommended  | ✅ DONE      |
| Profit Target Exit         | Automatically exit after X% profit                            | Lock in wins when available                  | 🔄 Optional     | N/A |
| Dynamic Rebalancing        | Re-allocate funds weekly based on performance                 | For serious long-term optimization           | 🔄 Future       | ✅ DONE      |
---

## 📸 Sample Output

---

## 📸 Sample Output

### 🔹 Trade Chart Sent to Telegram
![Trade Chart](charts/sample_trade_chart.png)

### 🔹 Google Sheets Trade Log
![Trade Log](screenshots/trade_log_sample.png)

---

## 🛠 Files & Structure
Crypto-Trading-Bot/
│
├── main.py                # Main bot script
├── config.json            # SL/TP/TSL settings for each coin
├── requirements.txt       # Python libraries
├── .env.example           # Shows required env keys (no secrets)
├── charts/                # Optional: folder for trade chart images
├── screenshots/           # Optional: Google Sheets or bot output
└── README.md              # Full project documentation

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

🧠 Skills Demonstrated =
✅ Python Development
✅ API Integration (Binance, Telegram, Google Sheets)
✅ Trading Strategy Design
✅ Automation & Alert Systems
✅ Real-world product mindset

---

## 🚀 Confirmed Roadmap: From Paper Trading to AI Integration

| 🧭 Phase                         | 🛠️ Action                                | 🧰 Tools Used                                | 🎯 Goal                                        |
|----------------------------------|------------------------------------------|----------------------------------------------|------------------------------------------------|
| ✅ **1. Paper Trading (Now)**     | Use your bot in Binance Testnet          | Binance Testnet, Google Sheets, Telegram     | Practice signals, SL/TP/TSL, logging alerts    |
| 🔜 **2. Real Trading (Soon)**     | Switch to real Binance API keys          | Same bot with `RealMoney: true`              | Trade with small capital ($5–$20)              |
| 🤖 **3. AI Signal Assistant**     | Add ChatGPT & TradingView chart analysis | ChatGPT API, TradingView Webhook             | Get market suggestions and signal validation   |
| 📈 **4. Long-Term Investment Bot**| Build weekly trend-following bot         | Python, EMA/RSI, Daily Charts, Auto-rebalance| Smart long-term crypto investing               |

---

⚠️ Disclaimer
This bot is for educational purposes only.
I am not a financial advisor. Use at your own risk.
Never use real money without fully understanding what the code does.

**🙌 Created by @KhushiThakur-AI**
