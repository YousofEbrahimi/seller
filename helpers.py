from __future__ import annotations

import secrets
import string

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import User

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def generate_referral_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_order_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


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
        ref_by_id: int | None = None
        if referral_code:
            ref_user = s.scalar(select(User).where(User.referral_code == referral_code))
            if ref_user and ref_user.telegram_id != telegram_id:
                ref_by_id = ref_user.id
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            referral_code=generate_referral_code(),
            referred_by=ref_by_id,
        )
        s.add(user)
        s.flush()
        new = True
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
