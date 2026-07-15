from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from telegram import Bot
from telegram.error import TelegramError

from config import FILES_DIR, cfg
from db import (
    Channel,
    Order,
    Product,
    Setting,
    User,
    get_session,
    log_error,
)


async def check_required_channels_async(bot: Bot, telegram_id: int) -> list[dict]:
    """Return list of channels the user hasn't joined. Async version."""
    s = get_session()
    try:
        channels = s.scalars(
            select(Channel).where(Channel.is_active == 1).order_by(Channel.id)
        ).all()
    finally:
        s.close()
    if not channels:
        return []
    not_joined: list[dict] = []
    for ch in channels:
        uname = ch.channel_username.lstrip("@")
        link = ch.invite_link or f"https://t.me/{uname}"
        entry = {"username": uname, "title": ch.title or uname, "invite_link": link}
        try:
            member = await bot.get_chat_member(f"@{uname}", telegram_id)
            if member.status in ("left", "kicked", "restricted"):
                not_joined.append(entry)
        except TelegramError:
            not_joined.append(entry)
    return not_joined


async def deliver_order_file(bot: Bot, order: Order, product: Product, chat_id: int) -> bool:
    """Send the product file to chat_id; update download counters. True on success."""
    if not product.file_path:
        return False
    file_path = FILES_DIR / product.file_path
    if not file_path.is_file():
        return False
    try:
        with open(file_path, "rb") as f:
            await bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=product.file_name or file_path.name,
                caption=f"📦 {product.name}",
            )
    except (TelegramError, OSError) as e:
        s = get_session()
        log_error(s, "deliver file error", f"{order.order_code}: {e}")
        s.close()
        return False
    s = get_session()
    try:
        order_row = s.get(Order, order.id)
        if order_row is not None:
            order_row.downloaded = (order_row.downloaded or 0) + 1
        prod = s.get(Product, product.id)
        if prod is not None:
            prod.download_count = (prod.download_count or 0) + 1
        s.commit()
    finally:
        s.close()
    return True


async def save_telegram_file(
    bot: Bot, file_id: str, save_dir: Path, filename: str | None = None
) -> Path | None:
    """Download a file from Telegram by file_id into save_dir."""
    save_dir.mkdir(parents=True, exist_ok=True)
    try:
        tg_file = await bot.get_file(file_id)
    except TelegramError:
        return None
    if filename is None:
        import secrets

        filename = secrets.token_hex(8) + ".bin"
    dest = save_dir / filename
    try:
        await tg_file.download_to_drive(str(dest))
    except (TelegramError, OSError):
        return None
    return dest


def get_admin_targets() -> list[int]:
    """Return all Telegram IDs that should receive admin notifications."""
    s = get_session()
    targets: set[int] = set(cfg.admin_ids)
    try:
        notify_id = s.get(Setting, "admin_notify_id")
        if notify_id and notify_id.value and notify_id.value.isdigit():
            notify_int = int(notify_id.value)
            if notify_int > 0:
                targets.add(notify_int)
        admins = s.scalars(select(User).where(User.is_admin == 1)).all()
        for a in admins:
            targets.add(a.telegram_id)
    except Exception:
        pass
    finally:
        s.close()
    return list(targets)


async def notify_admins(bot: Bot, text: str, reply_markup=None, file=None, file_is_photo: bool = False) -> None:
    """Send a notification to all admin targets.

    When ``file`` is provided, send it inline: as a photo when ``file_is_photo``
    (so image receipts render inline) or as a document otherwise.
    """
    for tid in get_admin_targets():
        try:
            if file is not None:
                if file_is_photo:
                    await bot.send_photo(chat_id=tid, photo=file, caption=text, reply_markup=reply_markup)
                else:
                    await bot.send_document(chat_id=tid, document=file, caption=text, reply_markup=reply_markup)
            else:
                await bot.send_message(chat_id=tid, text=text, reply_markup=reply_markup)
        except TelegramError:
            pass
