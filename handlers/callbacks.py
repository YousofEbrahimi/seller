"""Single callback router that dispatches to the right handler."""
from __future__ import annotations

from sqlalchemy import select
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db import Order, Product, User, get_session
from helpers import back_button, ensure_user, is_user_admin, main_menu_kb, membership_kb
from services import check_required_channels_async, deliver_order_file


async def callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cb = update.callback_query
    await cb.answer()
    data = cb.data or ""
    parts = data.split(":")

    if data == "check_join":
        not_joined = await check_required_channels_async(ctx.bot, update.effective_user.id)
        if not_joined:
            await cb.edit_message_text(
                "🔒 هنوز در همه کانال‌ها عضو نشده‌اید. لطفاً عضو شوید و دوباره بررسی کنید.",
                reply_markup=membership_kb(not_joined),
            )
        else:
            from handlers.start import send_welcome
            await cb.delete_message()
            await send_welcome(update, ctx)
        return

    # Admin callbacks
    if data.startswith("adm_"):
        s = get_session()
        try:
            user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                               update.effective_user.first_name)
            if not is_user_admin(user):
                await cb.answer("دسترسی ندارید", show_alert=True)
                return
        finally:
            s.close()
        from handlers.admin import handle_admin_callback
        await handle_admin_callback(update, ctx, data)
        return

    # Admin approve/reject/info shortcut (inline in admin chat)
    if data.startswith("admin_"):
        action = parts[0]
        order_id = int(parts[1]) if len(parts) > 1 else 0
        await admin_order_action(update, ctx, action, order_id)
        return

    # Membership gate for non-admin
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        if not is_user_admin(user):
            not_joined = await check_required_channels_async(ctx.bot, update.effective_user.id)
            if not_joined:
                await ctx.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="🔒 ابتدا در کانال‌های اجباری عضو شوید.",
                    reply_markup=membership_kb(not_joined),
                )
                return

        cmd = parts[0] if parts else ""
        if cmd == "cat":
            from handlers.shop import show_products_cb
            await show_products_cb(update, ctx, int(parts[1]), int(parts[2]) if len(parts) > 2 else 1)
        elif cmd == "prod":
            from handlers.shop import show_product_cb
            await show_product_cb(update, ctx, int(parts[1]))
        elif cmd == "buy":
            from handlers.buy import start_buy
            await start_buy(update, ctx, int(parts[1]))
        elif cmd == "cats":
            from handlers.shop import show_categories
            await show_categories(update, ctx)
        elif cmd == "home":
            await cb.delete_message()
            from handlers.start import send_welcome
            await send_welcome(update, ctx)
        elif cmd == "myorders":
            from handlers.shop import show_orders
            await show_orders(update, ctx)
        elif cmd == "page":
            from handlers.shop import show_products_cb
            await show_products_cb(update, ctx, int(parts[2]), int(parts[3]) if len(parts) > 3 else 1)
        elif cmd == "cancelbuy":
            user.state = None
            s.commit()
            await cb.delete_message()
            from handlers.start import send_welcome
            await send_welcome(update, ctx)
        elif cmd == "dl":
            await download_order(update, ctx, int(parts[1]))
        elif cmd == "searchtag":
            from handlers.shop import do_search
            await do_search(update, ctx, parts[1] or "")
    finally:
        s.close()


async def admin_order_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE, action: str, order_id: int) -> None:
    s = get_session()
    try:
        order = s.get(Order, order_id)
        if not order:
            await update.callback_query.answer("سفارش یافت نشد", show_alert=True)
            return
        if order.status not in ("pending", "need_info"):
            await update.callback_query.answer("این سفارش قبلاً بررسی شده است", show_alert=True)
            try:
                await update.callback_query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([]))
            except Exception:
                pass
            return
        buyer = s.get(User, order.user_id)
        prod = s.get(Product, order.product_id)
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([]))
        except Exception:
            pass

        if action == "admin_approve":
            order.status = "approved"
            order.admin_note = "تایید شد"
            s.commit()
            await update.callback_query.answer("سفارش تایید شد ✅")
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ سفارش <code>{order.order_code}</code> تایید شد و فایل برای کاربر ارسال شد.",
                parse_mode="HTML",
            )
            await ctx.bot.send_message(
                chat_id=buyer.telegram_id,
                text=f"✅ سفارش شما تایید شد!\n📦 محصول: {prod.name if prod else '-'}\n\nدر ادامه فایل محصول ارسال می‌شود:",
                reply_markup=main_menu_kb(),
            )
            delivered = await deliver_order_file(ctx.bot, order, prod, buyer.telegram_id) if prod else False
            if not delivered:
                await ctx.bot.send_message(
                    chat_id=buyer.telegram_id,
                    text="⚠️ فایل محصول یافت نشد. با پشتیبانی تماس بگیرید.",
                    reply_markup=main_menu_kb(),
                )
            return

        if action == "admin_reject":
            order.status = "rejected"
            order.admin_note = "رد شد"
            s.commit()
            await update.callback_query.answer("سفارش رد شد ❌")
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ سفارش <code>{order.order_code}</code> رد شد.",
                parse_mode="HTML",
            )
            await ctx.bot.send_message(
                chat_id=buyer.telegram_id,
                text=f"❌ سفارش شما با کد <code>{order.order_code}</code> متأسفانه رد شد.\nبرای پیگیری با پشتیبانی در تماس باشید.",
                parse_mode="HTML",
            )
            return

        if action == "admin_info":
            order.status = "need_info"
            order.admin_note = "درخواست توضیح بیشتر"
            if buyer:
                buyer.state = f"receipt:{order.id}"
            s.commit()
            await update.callback_query.answer("درخواست توضیح ارسال شد")
            await ctx.bot.send_message(chat_id=update.effective_chat.id,
                                       text="❓ از کاربر توضیح بیشتر خواسته شد.")
            await ctx.bot.send_message(
                chat_id=buyer.telegram_id,
                text=(f"❓ سفارش شما با کد <code>{order.order_code}</code> نیاز به توضیح بیشتر دارد.\n"
                      "لطفاً جزئیات بیشتری درباره رسید ارسال کنید."),
                reply_markup=back_button(),
                parse_mode="HTML",
            )
    finally:
        s.close()


async def download_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE, order_id: int) -> None:
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        order = s.scalar(select(Order).where(
            Order.id == order_id, Order.user_id == user.id, Order.status == "approved"
        ))
        if not order:
            await update.callback_query.answer("سفارش معتبر نیست", show_alert=True)
            return
        prod = s.get(Product, order.product_id)
        if not prod or not prod.file_path:
            await update.callback_query.answer("فایل موجود نیست", show_alert=True)
            return
        limit = prod.download_limit or 0
        if limit > 0 and (order.downloaded or 0) >= limit:
            await update.callback_query.answer("محدودیت دانلود به پایان رسیده است", show_alert=True)
            return
        ok = await deliver_order_file(ctx.bot, order, prod, update.effective_chat.id)
        if ok:
            await update.callback_query.answer("✅ فایل ارسال شد")
        else:
            await update.callback_query.answer("ارسال فایل ناموفق بود، دوباره تلاش کنید", show_alert=True)
    finally:
        s.close()
