#!/usr/bin/env python3
"""
install.py — Database installer for the File Store Telegram Bot.

Works on alwaysdata (PaaS) or any VPS — no root needed.
Creates database tables and admin user. Run once after setting up .env.

Usage:
    python3 install.py

This script:
  1. Reads .env settings
  2. Creates all database tables (SQLAlchemy create_all)
  3. Seeds default settings (welcome text, rules, etc.)
  4. Promotes your TELEGRAM_ID to admin in the database
  5. Verifies the bot token is valid by calling Telegram getMe

No MySQL CLI or root needed — everything goes through SQLAlchemy.
"""
from __future__ import annotations

import sys

# --- Step 1: load config and verify .env ---
print("=" * 50)
print("  File Store Telegram Bot — Installer")
print("=" * 50)
print()

try:
    from config import cfg
except SystemExit as e:
    print(f"❌ Configuration error: {e}")
    print()
    print("Make sure .env exists. Copy .env.example to .env:")
    print("  cp .env.example .env")
    print("Then edit .env with your bot token and database URL.")
    sys.exit(1)
except Exception as e:
    print(f"❌ Cannot load config: {e}")
    print("Make sure you installed dependencies: pip install -r requirements.txt")
    sys.exit(1)

print("✅ Config loaded.")
print(f"   Database URL: {cfg.database_url}")
print(f"   Admin IDs:    {list(cfg.admin_ids) if cfg.admin_ids else '(none in .env)'}")
print()

# --- Step 2: connect to database and create tables ---
print("[1/4] Creating database tables...")
from db import Base, engine, init_db, seed_defaults, User, get_session, Setting
from sqlalchemy import select

try:
    init_db()
    print("   ✅ Tables created (or already existed).")
except Exception as e:
    print(f"   ❌ Database error: {e}")
    print()
    print("If using MySQL on alwaysdata:")
    print("  1. Create the database via the alwaysdata admin panel")
    print("  2. Make sure DATABASE_URL in .env is correct:")
    print('     mysql+pymysql://USER:PASS@mysql-HOST.alwaysdata.net/DBNAME?charset=utf8mb4')
    sys.exit(1)

# --- Step 3: seed default settings ---
print()
print("[2/4] Seeding default settings...")
try:
    s = get_session()
    seed_defaults(s)
    s.close()
    print("   ✅ Default settings inserted.")
except Exception as e:
    print(f"   ⚠️  Settings seed warning: {e}")

# --- Step 4: promote admin in database ---
print()
print("[3/4] Setting up admin user...")
if cfg.admin_ids:
    s = get_session()
    try:
        from helpers import generate_referral_code
        import secrets as _s
        for admin_id in cfg.admin_ids:
            user = s.scalar(select(User).where(User.telegram_id == admin_id))
            if user is None:
                user = User(
                    telegram_id=admin_id,
                    referral_code=generate_referral_code(s),
                    is_admin=1,
                    first_name="Admin",
                )
                s.add(user)
                print(f"   ✅ Admin user created for Telegram ID {admin_id}")
            else:
                user.is_admin = 1
                print(f"   ✅ User {admin_id} promoted to admin")
        s.commit()
    except Exception as e:
        print(f"   ⚠️  Admin setup warning: {e}")
        s.rollback()
    finally:
        s.close()
else:
    print("   ⚠️  No ADMIN_IDS in .env — you can promote yourself later from the bot.")

# --- Step 5: verify bot token ---
print()
print("[4/4] Verifying bot token with Telegram...")
import asyncio

async def verify_token():
    from telegram import Bot
    api_base = cfg.telegram_api_base or None
    bot = Bot(token=cfg.bot_token, base_url=api_base) if api_base else Bot(token=cfg.bot_token)
    me = await bot.get_me()
    return me

try:
    me = asyncio.run(verify_token())
    print(f"   ✅ Bot connected: @{me.username} ({me.first_name})")
except Exception as e:
    print(f"   ❌ Telegram connection failed: {e}")
    print()
    print("If api.telegram.org is blocked from your server:")
    print("  1. Deploy a Deno Deploy proxy (see README.md)")
    print("  2. Set TELEGRAM_API_BASE in .env to the proxy URL")
    print("  3. Re-run this script")
    print()
    print("Tables are created — you can still start the bot, but Telegram won't work until connectivity is fixed.")
    sys.exit(1)

# --- Done ---
print()
print("=" * 50)
print("  ✅ Installation complete!")
print("=" * 50)
print()
print("Next steps:")
print("  1. Make sure .env has your BOT_TOKEN, DATABASE_URL, and ADMIN_IDS")
print("  2. Start the bot:")
print("     bash run.sh start")
print("  3. In Telegram, send /start to your bot")
print("  4. Send /admin to open the admin panel")
print()
