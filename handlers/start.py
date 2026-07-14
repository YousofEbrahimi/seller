"""Start, admin command, and main-menu text routing."""
from __future__ import annotations

from sqlalchemy import select
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db import User, get_session, setting
from helpers import (
    back_button,
    ensure_user,
    is_user_admin,
    main_menu_kb,
    membership_kb,
)
from services import check_required_channels_async


async def send_welcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = update.effective_user
    telegram_id = update.effective_user.id
    s = get_session()
    try:
        user = ensure_user(
            s, telegram_id, user_data.username, user_data.first_name, user_data.last_name,
        )
        welcome = setting(s, "welcome_text", "سلام! خوش آمدید.")
        not_joined = await check_required_channels_async(ctx.bot, telegram_id)
        if not_joined:
            await ctx.bot.send_message(
                chat_id=telegram_id,
                text="🔒 برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید:",
                reply_markup=membership_kb(not_joined),
            )
            return
        kb = main_menu_kb(is_admin=is_user_admin(user))
        await ctx.bot.send_message(chat_id=telegram_id, text=f"👋 {welcome}", reply_markup=kb)
    finally:
        s.close()


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    s = get_session()
    try:
        args = ctx.args
        referral = args[0] if args else None
        user_data = update.effective_user
        user = ensure_user(
            s,
            telegram_id,
            user_data.username,
            user_data.first_name,
            user_data.last_name,
            referral_code=referral,
        )
        user.state = None
        s.commit()
    finally:
        s.close()
    await send_welcome(update, ctx)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel any active wizard and return to the main menu."""
    telegram_id = update.effective_user.id
    s = get_session()
    try:
        user = ensure_user(
            s, telegram_id, update.effective_user.username,
            update.effective_user.first_name, update.effective_user.last_name,
        )
        user.state = None
        user.state_data = ""
        s.commit()
    finally:
        s.close()
    await send_welcome(update, ctx)


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from handlers.admin import admin_menu

    telegram_id = update.effective_user.id
    s = get_session()
    try:
        user = ensure_user(s, telegram_id, update.effective_user.username,
                           update.effective_user.first_name)
        if not is_user_admin(user):
            await update.effective_message.reply_text("⛔ شما ادمین نیستید.")
            return
        await admin_menu(update, ctx)
    finally:
        s.close()


async def text_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Route all non-command text messages."""
    from handlers.shop import handle_state, show_categories, do_search, show_profile, show_referral, show_orders
    from handlers.admin import admin_menu, handle_admin_state

    telegram_id = update.effective_user.id
    text = (update.effective_message.text or "").strip()
    s = get_session()
    try:
        user = ensure_user(
            s, telegram_id, update.effective_user.username,
            update.effective_user.first_name, update.effective_user.last_name,
        )

        # /start payload handled elsewhere
        if text.startswith("/start"):
            user.state = None
            s.commit()
            await send_welcome(update, ctx)
            return

        admin = is_user_admin(user)
        if text in ("/admin", "🎛 مدیریت", "/panel"):
            if admin:
                user.state = None
                s.commit()
                await admin_menu(update, ctx)
                return

        # If user is in a wizard state, route to state handler.
        # Some wizard steps expect non-text media (file/photo/video) instead of text:
        #   admin_pfile  → product file upload   (admin only)
        #   admin_bc_text → broadcast content (text or media, admin only)
        #   receipt:ID    → receipt upload        (any user)
        # Those media steps route to their own handlers; text-based states go to handle_state.
        if user.state:
            from handlers.shop import handle_state as _hs

            msg = update.effective_message
            has_media = bool(msg.document or msg.photo or msg.video)

            # Cancel takes precedence over any wizard state.
            if text in ("⬅️ بازگشت به منو", "/cancel"):
                user.state = None
                s.commit()
                await send_welcome(update, ctx)
                return

            # --- States that accept media (or text) directly ---
            if user.state == "admin_pfile" and has_media:
                from handlers.admin import wiz_product_file
                s.close()
                await wiz_product_file(update, ctx, user)
                return

            # Broadcast wizard accepts both text and media.
            if user.state == "admin_bc_text" and (text or has_media):
                from handlers.admin import wiz_broadcast_content
                s.close()
                await wiz_broadcast_content(update, ctx, user, msg)
                return

            # Receipt upload accepts media or text (text is treated as caption/note).
            if user.state.startswith("receipt:") and has_media:
                await _hs(update, ctx, user)
                return

            # --- Text-based wizard states ---
            if user.state.startswith(("admin_", "receipt:", "search")):
                if not text:
                    if has_media:
                        await ctx.bot.send_message(
                            chat_id=telegram_id,
                            text="❗ الان منتظر متن هستم، نه فایل. /cancel برای لغو.",
                        )
                    return  # stickers/animations/etc — ignore
                await _hs(update, ctx, user)
                return

            # Non-admin/receipt/search state with media and no text: ignore
            if not text:
                return

        # Membership gate (admins exempt)
        if not admin:
            not_joined = await check_required_channels_async(ctx.bot, telegram_id)
            if not_joined:
                await ctx.bot.send_message(
                    chat_id=telegram_id,
                    text="🔒 برای دسترسی به امکانات ربات ابتدا در کانال‌های زیر عضو شوید:",
                    reply_markup=membership_kb(not_joined),
                )
                return

        # Main menu navigation
        if text in ("🛍 فروشگاه", "/shop", "📁 دسته‌بندی‌ها"):
            await show_categories(update, ctx)
        elif text == "🔍 جستجو":
            user.state = "search"
            s.commit()
            await ctx.bot.send_message(
                chat_id=telegram_id,
                text="🔍 عبارت مورد نظر را برای جستجو ارسال کنید (نام، برچسب یا توضیحات):",
                reply_markup=back_button(),
            )
        elif text == "👤 پروفایل":
            await show_profile(update, ctx)
        elif text == "🎁 دعوت دوستان":
            await show_referral(update, ctx)
        elif text == "📋 سفارش‌های من":
            await show_orders(update, ctx)
        elif text == "📖 قوانین":
            rules = setting(s, "rules_text", "")
            await ctx.bot.send_message(
                chat_id=telegram_id,
                text=f"📖 <b>قوانین</b>\n\n{rules}",
                reply_markup=main_menu_kb(is_admin=admin),
                parse_mode="HTML",
            )
        elif text == "📞 پشتیبانی":
            support = setting(s, "support_text", "")
            await ctx.bot.send_message(
                chat_id=telegram_id,
                text=f"📞 <b>پشتیبانی</b>\n\n{support}",
                reply_markup=main_menu_kb(is_admin=admin),
                parse_mode="HTML",
            )
        elif text in ("⬅️ بازگشت به منو", "/cancel"):
            user.state = None
            s.commit()
            await send_welcome(update, ctx)
        else:
            await send_welcome(update, ctx)
    finally:
        s.close()