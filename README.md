# 📦 File Store Telegram Bot (Python Version)

A premium, feature-rich Telegram File Store Bot rewritten from PHP to Python 3. It utilizes the modern `python-telegram-bot` framework and `SQLAlchemy` for robust database operations (supporting both SQLite and MySQL/MariaDB).

Admins can upload files, set prices (in Tomans or free), manage categories, view detailed error logs, edit settings, track orders, promote/demote admins, block users, force channel subscriptions, and broadcast messages to all users in a secure background process directly within Telegram.

---

## ✨ Features

### 🛍️ User Experience
- **Structured Categories**: Browse products by category using responsive inline keyboards.
- **Search Engine**: Search for products by name, description, or tags.
- **My Profile**: View Telegram ID, referral stats, order counts, and invite-link balance.
- **Referral System**: Users can invite friends via a referral link (`t.me/bot?start=CODE`) and earn balance rewards.
- **My Orders**: View purchase history and current status of payments.
- **Secure File delivery**: When a purchase is approved, the bot delivers the actual file to the user (supporting download limit counters).

### 💳 Order & Payment Flow
- **Offline Card Transfer**: Customers are given active bank card details and pay offline.
- **Receipt Upload**: Users upload images or documents of their bank receipts.
- **Admin Verification**: Admins receive an interactive request in Telegram to Approve, Reject, or Ask for clarification from the buyer.

### 🎛️ Inline Admin Panel (`/admin`)
- **Product Management**: Upload new files, set prices, assign categories, manage descriptions, tag products, and toggle visibility.
- **Category Management**: Create, toggle active status, and delete product categories.
- **Required Channel Gate**: Force users to join specific Telegram channels before using the bot.
- **Bank Card Management**: Update payment cards dynamically.
- **Settings Editor**: Modify bot messages (welcome text, rules, payment instructions, referral reward, etc.) without touching code.
- **Background Broadcasts**: Safely broadcast text, photo, or document messages to all users asynchronously (prevents bot timeouts and API limits).
- **User Administration**: List users, check stats, toggle ban status, and promote/demote admins.
- **Interactive Log Viewer**: Inspect and purge detailed error logs from within the Telegram interface.

---

## 🛠️ Technology Stack
- **Core**: Python 3.10+
- **Telegram Wrapper**: `python-telegram-bot` (v21.6)
- **Database Engine**: `SQLAlchemy` (v2.0)
- **Database Adapters**: `PyMySQL` (v1.1) for MySQL/MariaDB, built-in sqlite3 driver.
- **Config Management**: `python-dotenv` (v1.0)

---

## 🚀 Getting Started

### 1. Prerequisites
Ensure you have Python 3.10 or higher installed:
```bash
python3 --version
```

### 2. Clone the Repository
```bash
git clone https://github.com/YousofEbrahimi/seller.git
cd seller
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment (`.env`)
Copy the template configuration file:
```bash
cp .env.example .env
```
Open `.env` and configure:
- `BOT_TOKEN`: Obtain this from [@BotFather](https://t.me/BotFather).
- `ADMIN_IDS`: Comma-separated list of Telegram user IDs (e.g. `123456789,987654321`) who should have full admin privileges.
- `DATABASE_URL`: 
  - SQLite: `sqlite:///seller.db`
  - MySQL: `mysql+pymysql://USER:PASS@HOST:PORT/DBNAME?charset=utf8mb4`
- `STORE_NAME`: Display name shown in the bot (default: `فروشگاه فایل`).
- `TELEGRAM_API_BASE`: Leave empty for direct access. If `api.telegram.org` is blocked from your host, deploy a reverse proxy (e.g. on Deno Deploy) and put its URL here.
- `PROXY_HOST` / `PROXY_PORT` / `PROXY_TYPE`: Optional HTTP/HTTPS/SOCKS proxy if direct Telegram access is blocked.

### 5. Initialize the Database
Run the installation script to build database tables, populate default messages/settings, and register the admin IDs:
```bash
python install.py
```
The script verifies the bot token by calling `getMe` and prints a success banner when done. If it reports a Telegram connection error but still creates the tables, deploy a proxy and re-run it.

> Note: `install.py` is only required for the very first set-up. The bot itself also calls `init_db()` / `seed_defaults()` on startup via `post_init`, so tables are kept in sync automatically.

### 6. Run the Bot
Use the process manager script:
```bash
# Start the bot in background
bash run.sh start

# Stop the bot
bash run.sh stop

# Check status
bash run.sh status

# Monitor live logs
bash run.sh logs
```

---

## 📁 File Structure
- `main.py`: Entry point for the long-polling execution loop.
- `config.py`: Configuration parser reading from `.env` and environment variables.
- `db.py`: Database models definition and seeding utilities.
- `helpers.py`: Utility functions and keyboard layout generators.
- `services.py`: Telegram API wrappers, user membership checks, and broadcast handlers.
- `install.py`: Database setup and token validation script.
- `handlers/`:
  - `start.py`: Handles `/start`, `/admin`, and main text-based navigation routing.
  - `callbacks.py`: Central router for all inline queries and keyboard actions.
  - `shop.py`: Category browser, product detail views, profiles, and order history.
  - `buy.py`: Order checkout pipeline and receipt verification processes.
  - `admin.py`: Large admin workspace containing all management functions and state wizards.
