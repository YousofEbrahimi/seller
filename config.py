"""Configuration loader for the File Store Telegram Bot.

Reads settings from environment variables and a `.env` file (via python-dotenv).
Exposes a singleton `cfg` and the `FILES_DIR` path used by services/admin.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
FILES_DIR = BASE_DIR / "uploads" / "files"
PREVIEW_DIR = BASE_DIR / "uploads" / "previews"


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on", "y")


def _env_int_list(key: str) -> set[int]:
    raw = os.getenv(key, "").strip()
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


class Config:
    """Single source of truth for runtime settings."""

    def __init__(self) -> None:
        self.bot_token: str = os.getenv("BOT_TOKEN", "").strip()
        if not self.bot_token:
            print(
                "FATAL: BOT_TOKEN is not set. Copy .env.example to .env and fill in your token."
            )
            raise SystemExit(1)

        self.database_url: str = os.getenv(
            "DATABASE_URL", "sqlite:///seller.db"
        ).strip()

        self.admin_ids: set[int] = _env_int_list("ADMIN_IDS")

        self.store_name: str = os.getenv("STORE_NAME", "فروشگاه فایل").strip() or "فروشگاه فایل"

        self.download_token_salt: str = os.getenv(
            "DOWNLOAD_TOKEN_SALT", "change-this-to-a-random-string"
        ).strip() or "change-this-to-a-random-string"

        self.telegram_api_base: str = os.getenv("TELEGRAM_API_BASE", "").strip()

        self.proxy_host: str = os.getenv("PROXY_HOST", "").strip()
        self.proxy_port: str = os.getenv("PROXY_PORT", "").strip()
        self.proxy_type: str = os.getenv("PROXY_TYPE", "HTTP").strip().upper() or "HTTP"
        proxy_user: str = os.getenv("PROXY_USERNAME", "").strip()
        proxy_pass: str = os.getenv("PROXY_PASSWORD", "").strip()
        self.proxy_username: str = proxy_user
        self.proxy_password: str = proxy_pass

        self.debug: bool = _env_bool("DEBUG", False)
        self.per_page_default: int = 8
        try:
            pp = int(os.getenv("PER_PAGE", "8"))
            if pp > 0:
                self.per_page_default = pp
        except ValueError:
            pass

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def get_proxy_request_kwargs(self) -> dict:
        """Return kwargs for ApplicationBuilder() if a proxy is configured, else {}."""
        if not self.proxy_host or not self.proxy_port:
            return {}
        ptype = self.proxy_type
        if ptype not in ("HTTP", "HTTPS", "SOCKS4", "SOCKS5"):
            ptype = "HTTP"
        url = f"{ptype.lower()}://{self.proxy_host}:{self.proxy_port}"
        if self.proxy_username:
            url = f"{ptype.lower()}://{self.proxy_username}:{self.proxy_password}@{self.proxy_host}:{self.proxy_port}"
        return {"proxy_url": url}


cfg = Config()

FILES_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
