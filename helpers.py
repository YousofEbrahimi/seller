from __future__ import annotations

import re
import secrets
import string

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import User

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def _unique_code(s: Session, length: int, col) -> str:
    """Generate a random code guaranteed unique against ``col`` (retries on collision)."""
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(50):
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if s.scalar(select(col).where(col == code)) is None:
            return code
    # Vanishingly unlikely: 50 collisions in a row. Fall back so we never crash onboarding.
    return "".join(secrets.choice(alphabet) for _ in range(length + 4))


def generate_referral_code(s: Session, length: int = 6) -> str:
    return _unique_code(s, length, User.referral_code)


def generate_order_code(s: Session) -> str:
    from db import Order

    return _unique_code(s, 8, Order.order_code)


def is_blocked(user: User | None) -> bool:
    """True if the user has been banned by an admin (DB flag). Admins are never blocked."""
    if user is None:
        return False
    from config import cfg

    if user.telegram_id in cfg.admin_ids:
        return False
    return bool(user.is_blocked)


def ensure_user(
    s: Session,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    referral_code: str | None = None,
) -> User:
    user = s.scalar(select(User).where(User.telegram_id == telegram_id))
    new = False
    if user is None:
        ref_user = None
        if referral_code:
            ref_user = s.scalar(select(User).where(User.referral_code == referral_code))
            if ref_user and ref_user.telegram_id == telegram_id:
                ref_user = None  # don't refer yourself
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            referral_code=generate_referral_code(s),
            referred_by=ref_user.id if ref_user else None,
        )
        # Retry on the off chance the generated code collided between check and commit.
        for _ in range(5):
            try:
                s.add(user)
                s.flush()
                break
            except IntegrityError:
                s.rollback()
                user.referral_code = generate_referral_code(s)
                s.add(user)
                s.flush()
        new = True
        # Credit the referrer once, at signup, with the configured reward.
        if ref_user is not None:
            reward = _referral_reward(s)
            if reward > 0:
                ref_user.referral_balance = (ref_user.referral_balance or 0) + reward
    else:
        if username is not None and user.username != username:
            user.username = username
        if first_name is not None and user.first_name != first_name:
            user.first_name = first_name
        if last_name is not None and user.last_name != last_name:
            user.last_name = last_name
    s.commit()
    if new:
        user._just_created = True  # type: ignore[attr-defined]
    else:
        user._just_created = False  # type: ignore[attr-defined]
    return user


def _referral_reward(s: Session) -> int:
    """Read the configured referral reward (Tomans) as a non-negative int."""
    from db import setting

    raw = setting(s, "referral_reward", "0")
    try:
        val = int(re.sub(r"\D", "", raw) or "0")
    except Exception:
        val = 0
    return val if val > 0 else 0


def is_user_admin(user: User | None) -> bool:
    if user is None:
        return False
    from config import cfg

    return user.telegram_id in cfg.admin_ids or bool(user.is_admin)


def fa_num(text: str | int) -> str:
    return str(text).translate(str.maketrans("0123456789", PERSIAN_DIGITS))


def toman(amount: int) -> str:
    return fa_num(f"{amount:,}") + " تومان"


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    if size < 1024**3:
        return f"{size / 1024**2:.1f} MB"
    return f"{size / 1024**3:.2f} GB"


# Keyboard layouts
from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        ["🛍 فروشگاه", "🔍 جستجو"],
        ["📁 دسته‌بندی‌ها", "👤 پروفایل"],
        ["🎁 دعوت دوستان", "📋 سفارش‌های من"],
        ["📖 قوانین", "📞 پشتیبانی"],
    ]
    if is_admin:
        rows.append(["🎛 مدیریت"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def back_button() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["⬅️ بازگشت به منو"]], resize_keyboard=True)


def membership_kb(not_joined: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for ch in not_joined:
        label = (ch.get("title") or ch.get("username") or "کانال")[:40]
        rows.append([InlineKeyboardButton(label, url=ch["invite_link"])])
    rows.append([InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data="check_join")])
    return InlineKeyboardMarkup(rows)
