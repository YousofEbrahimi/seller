"""Buy flow: create order, await receipt upload, notify admins."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db import Card, Order, Product, User, get_session, setting
from helpers import back_button, fa_num, generate_order_code, is_user_admin, main_menu_kb, toman
from services import notify_admins


async def start_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE, prod_id: int) -> None:
    cb = update.callback_query
    s = get_session()
    try:
        user = s.scalar(select(User).where(User.telegram_id == update.effective_user.id)) if False else None
        from helpers import ensure_user
        userrecord = ensure_user(s, update.effective_user.id, update.effective_user.username,
                                 update.effective_user.first_name)
        p = s.get(Product, prod_id)
        if not p or not p.is_active:
            await cb.answer("محصول یافت نشد", show_alert=True)
            return
        # Reuse existing pending order if any
        existing = s.scalar(
            select(Order).where(
                Order.user_id == userrecord.id, Order.product_id == prod_id,
                Order.status.in_(["pending", "need_info"]),
            ).order_by(Order.id.desc())
        )
        if existing:
            order = existing
        else:
            order = Order(
                order_code=generate_order_code(),
                user_id=userrecord.id,
                product_id=prod_id,
                price=p.price,
                status="pending",
            )
            s.add(order)
            s.flush()
        tmpl = setting(s, "payment_text", "مبلغ را واریز کنید.")
        cards = s.scalars(select(Card).where(Card.is_active == 1).order_by(Card.sort_order, Card.id)).all()
        cards_text = ""
        for c in cards:
            bank = f" ({c.bank_name})" if c.bank_name else ""
            cards_text += f"\n💳 {c.card_number}\n👤 {c.holder_name}{bank}\n"
        text = tmpl.replace("{product_name}", p.name) \
                   .replace("{price}", fa_num(f"{p.price:,}")) \
                   .replace("{cards}", cards_text or "—") \
                   .replace("{order_code}", order.order_code)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="cancelbuy")]])
        await cb.edit_message_text(text=text, reply_markup=kb)
        userrecord.state = f"receipt:{order.id}"
        s.commit()
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📩 لطفاً رسید پرداخت را (عکس یا فایل) ارسال کنید:",
            reply_markup=back_button(),
        )
    finally:
        s.close()


async def handle_receipt_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, order_id: int) -> None:
    msg = update.effective_message
    s = get_session()
    try:
        order = s.scalar(
            select(Order).where(
                Order.id == order_id, Order.user_id == user.id,
                Order.status.in_(["pending", "need_info"]),
            )
        )
        if not order:
            user.state = None
            s.commit()
            from handlers.start import send_welcome
            await send_welcome(update, ctx)
            return

        file_id = None
        file_type = None
        caption = ""
        if msg.photo:
            file_id = msg.photo[-1].file_id
            file_type = "photo"
            caption = msg.caption or ""
        elif msg.document:
            file_id = msg.document.file_id
            file_type = "document"
            caption = msg.caption or ""
        elif msg.text and msg.text.strip():
            file_type = "text"
            caption = msg.text.strip()

        if not file_id and file_type != "text":
            await ctx.bot.send_message(chat_id=update.effective_chat.id, text="❗ لطفاً یک عکس یا فایل ارسال کنید.")
            return

        order.receipt_file_id = file_id
        order.receipt_file_type = file_type
        order.receipt_message = caption
        order.status = "pending"
        user.state = None
        s.commit()

        product = s.get(Product, order.product_id)
        admin_text = (
            "🔔 <b>سفارش جدید در انتظار تایید</b>\n\n"
            f"🧾 کد: <code>{order.order_code}</code>\n"
            f"📦 محصول: {product.name if product else '-'}\n"
            f"💰 مبلغ: {toman(order.price)}\n"
            f"👤 کاربر: {user.first_name or ''} "
            f"({'@' + user.username if user.username else fa_num(user.telegram_id)})\n"
            f"📝 توضیح: {caption}"
        )
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ تایید و ارسال فایل", callback_data=f"admin_approve:{order.id}")],
                [InlineKeyboardButton("❌ رد", callback_data=f"admin_reject:{order.id}"),
                 InlineKeyboardButton("❓ درخواست توضیح", callback_data=f"admin_info:{order.id}")],
            ]
        )
        file_obj = file_id if file_id and file_type in ("photo", "document") else None
        await notify_admins(ctx.bot, admin_text, reply_markup=kb, file=file_obj)
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ رسید شما دریافت شد و در انتظار تایید مدیر است.\nکد پیگیری: <code>{order.order_code}</code>",
            reply_markup=main_menu_kb(),
            parse_mode="HTML",
        )
    finally:
        s.close()


# needed import
from sqlalchemy import select  # noqa: E402,F401
