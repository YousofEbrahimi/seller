"""Admin panel inside the bot. All admin functions live here."""
from __future__ import annotations

import re
import secrets

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import FILES_DIR, cfg
from db import (
    Broadcast,
    Card,
    Category,
    Channel,
    Log,
    Order,
    Product,
    Setting,
    User,
    get_session,
    log_error,
    set_setting,
    setting,
)
from helpers import (
    back_button,
    ensure_user,
    fa_num,
    generate_referral_code,
    human_size,
    is_user_admin,
    main_menu_kb,
    toman,
)
from services import deliver_order_file, notify_admins, save_telegram_file

ADMIN_PER_PAGE = 8


# =====================================================
# state_data helpers (compact k=v;k=v format)
# =====================================================
import json

def _parse_sd(data: str | None) -> dict:
    if not data:
        return {}
    try:
        return json.loads(data)
    except Exception:
        # Fallback for old data
        out: dict[str, str] = {}
        for pair in data.split(";"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                out[k.strip()] = v.strip()
        return out


def _format_sd(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)


def _reload_user(s: Session, user: User) -> User:
    """Re-attach ``user`` to session ``s`` so subsequent writes commit cleanly.

    The handlers receive a ``User`` instance from an outer session which may
    already be closed by the time the wizard runs. Using ``s.merge`` would re-
    load the row if necessary, but since it keeps the in-memory state we use it
    here as a safe attach. We read ``user.id`` first (the PK never changes) and
    fall back to a select-by-id if merge complains so that we always operate on
    a managed instance of the current row.
    """
    try:
        return s.merge(user)
    except Exception:
        return s.get(User, user.id)  # type: ignore[return-value]




# =====================================================
# Main admin menu
# =====================================================
async def admin_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = "🎛 <b>پنل مدیریت</b>\n\nیک بخش را انتخاب کنید:"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 محصولات", callback_data="adm_prodlist:1")],
        [InlineKeyboardButton("📁 دسته‌بندی‌ها", callback_data="adm_catlist")],
        [InlineKeyboardButton("📋 سفارش‌ها", callback_data="adm_orderlist:pending:1")],
        [InlineKeyboardButton("👤 کاربران", callback_data="adm_userlist:1")],
        [InlineKeyboardButton("📢 کانال‌های اجباری", callback_data="adm_channellist")],
        [InlineKeyboardButton("💳 کارت‌های بانکی", callback_data="adm_cardlist")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="adm_broadcast_menu")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="adm_settings")],
        [InlineKeyboardButton("🐛 لاگ خطاها", callback_data="adm_logs:1")],
        [InlineKeyboardButton("🏠 منوی ربات", callback_data="home")],
    ])
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id, text=text,
                reply_markup=kb, parse_mode="HTML",
            )
    else:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id, text=text,
            reply_markup=kb, parse_mode="HTML",
        )


# =====================================================
# Callback dispatcher
# =====================================================
async def handle_admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    parts = data.split(":")
    cmd = parts[0]
    a1 = parts[1] if len(parts) > 1 else ""
    a2 = parts[2] if len(parts) > 2 else ""
    cb = update.callback_query

    if cmd == "adm_menu":
        await admin_menu(update, ctx)
    # Products
    elif cmd in ("adm_prodlist", "adm_prodpage"):
        await admin_product_list(update, ctx, int(a1) if a1 and a1.isdigit() else 1)
    elif cmd == "adm_prodadd":
        await admin_product_add_step(update, ctx)
    elif cmd == "adm_proddetails":
        await admin_product_details(update, ctx, int(a1))
    elif cmd == "adm_prodtoggle":
        await admin_product_toggle(update, ctx, int(a1))
    elif cmd == "adm_proddel":
        await admin_product_delete(update, ctx, int(a1))
    elif cmd == "adm_pcatset":
        await admin_product_set_category(update, ctx, int(a1) if a1.isdigit() else 0)
    elif cmd == "adm_pvipset":
        await admin_product_set_vip(update, ctx, int(a1) if a1.isdigit() else 0)
    elif cmd == "adm_psave":
        await admin_product_save(update, ctx, int(a1) if a1.isdigit() else 1)
    elif cmd == "adm_pcancel":
        await admin_product_cancel(update, ctx)
    # Categories
    elif cmd == "adm_catlist":
        await admin_category_list(update, ctx)
    elif cmd == "adm_catadd":
        await admin_category_add(update, ctx)
    elif cmd == "adm_catdel":
        await admin_category_delete(update, ctx, int(a1))
    elif cmd == "adm_catdelconfirm":
        await admin_category_delete_confirm(update, ctx, int(a1))
    elif cmd == "adm_cattoggle":
        await admin_category_toggle(update, ctx, int(a1))
    # Orders
    elif cmd in ("adm_orderlist", "adm_orderpage"):
        st = a1 if a1 else "pending"
        pg = int(a2) if a2 and a2.isdigit() else 1
        await admin_order_list(update, ctx, st, pg)
    elif cmd == "adm_order":
        await admin_order_show(update, ctx, int(a1))
    elif cmd == "adm_orderview":
        await admin_order_view(update, ctx, int(a1))
    # Users
    elif cmd in ("adm_userlist", "adm_userpage"):
        await admin_user_list(update, ctx, int(a1) if a1 and a1.isdigit() else 1)
    elif cmd == "adm_usershow":
        await admin_user_show(update, ctx, int(a1))
    elif cmd == "adm_userban":
        await admin_user_toggle_ban(update, ctx, int(a1))
    elif cmd == "adm_useradmin":
        await admin_user_toggle_admin(update, ctx, int(a1))
    # Channels
    elif cmd == "adm_channellist":
        await admin_channel_list(update, ctx)
    elif cmd == "adm_channeladd":
        await admin_channel_add(update, ctx)
    elif cmd == "adm_channeldel":
        await admin_channel_delete(update, ctx, int(a1))
    elif cmd == "adm_channeltoggle":
        await admin_channel_toggle(update, ctx, int(a1))
    # Cards
    elif cmd == "adm_cardlist":
        await admin_card_list(update, ctx)
    elif cmd == "adm_cardadd":
        await admin_card_add(update, ctx)
    elif cmd == "adm_carddel":
        await admin_card_delete(update, ctx, int(a1))
    elif cmd == "adm_cardtoggle":
        await admin_card_toggle(update, ctx, int(a1))
    # Broadcast
    elif cmd == "adm_broadcast_menu":
        await admin_broadcast_menu(update, ctx)
    elif cmd == "adm_broadcast_text":
        await admin_broadcast_start(update, ctx, "text")
    elif cmd == "adm_broadcast_photo":
        await admin_broadcast_start(update, ctx, "photo")
    elif cmd == "adm_broadcast_file":
        await admin_broadcast_start(update, ctx, "document")
    elif cmd == "adm_broadcast_send":
        await admin_broadcast_send(update, ctx, int(a1))
    elif cmd == "adm_broadcast_cancel":
        await admin_broadcast_cancel(update, ctx)
    # Settings
    elif cmd == "adm_settings":
        await admin_settings(update, ctx)
    elif cmd == "adm_setstart":
        await admin_set_setting(update, ctx, "welcome_text", "متن خوش‌آمدگویی")
    elif cmd == "adm_setrules":
        await admin_set_setting(update, ctx, "rules_text", "متن قوانین")
    elif cmd == "adm_setsupport":
        await admin_set_setting(update, ctx, "support_text", "متن پشتیبانی")
    elif cmd == "adm_setpay":
        await admin_set_setting(update, ctx, "payment_text", "متن پرداخت")
    elif cmd == "adm_setreward":
        await admin_set_setting(update, ctx, "referral_reward", "پاداش دعوت (تومان)")
    elif cmd == "adm_setstore":
        await admin_set_setting(update, ctx, "store_name", "نام فروشگاه")
    elif cmd == "adm_setnotifier":
        await admin_set_setting(update, ctx, "admin_notify_id", "آیدی عددی ادمین")
    elif cmd == "adm_setperpage":
        await admin_set_setting(update, ctx, "per_page", "تعداد در هر صفحه")
    # Logs
    elif cmd in ("adm_logs", "adm_logspage"):
        await admin_logs(update, ctx, int(a1) if a1 and a1.isdigit() else 1)
    elif cmd == "adm_logsclear":
        await admin_logs_clear(update, ctx)
    elif cmd == "adm_logsdel":
        await admin_logs_delete(update, ctx, int(a1))
    elif cmd == "adm_logsdetails":
        await admin_logs_details(update, ctx, int(a1))
    else:
        await admin_menu(update, ctx)


# =====================================================
# Admin state dispatcher (wizard text routing)
# =====================================================
async def handle_admin_state(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str
) -> None:
    s = get_session()
    try:
        user = s.merge(user)
        state = user.state or ""

        if text in ("⬅️ بازگشت به منو", "/cancel", "/admin"):
            user.state = None
            user.state_data = ""
            s.commit()
            if text == "/admin":
                await admin_menu(update, ctx)
            else:
                from handlers.start import send_welcome
                await send_welcome(update, ctx)
            return

        # States that expect non-text messages (file upload) are handled by
        # start.py's text_menu gate; here we only handle text-based wizard steps.
        if state == "admin_pfile":
            # Text sent while admin_pfile expects a file — prompt again, unless cancelling.
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❗ لطفاً یک فایل (عکس، ویدیو یا سند) بفرستید، نه متن. یا /cancel برای لغو.",
                reply_markup=back_button(),
            )
            return
        elif state == "admin_pname":
            await wiz_product_name(update, ctx, user, text)
            return
        elif state == "admin_pprice":
            await wiz_product_price(update, ctx, user, text)
            return
        elif state == "admin_ptags":
            await wiz_product_tags(update, ctx, user, text)
            return
        elif state == "admin_pdesc":
            await wiz_product_desc(update, ctx, user, text)
            return
        elif state == "admin_pcat":
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text="📁 لطفاً از دکمه‌های زیر یک دسته را انتخاب کنید.",
            )
            return
        elif state == "admin_pvip":
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⭐ لطفاً از دکمه‌ها نوع محصول (VIP یا معمولی) را انتخاب کنید.",
            )
            return
        elif state == "admin_psave":
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text="✅ لطفاً از دکمه‌ها وضعیت انتشار را انتخاب کنید.",
            )
            return
        elif state == "admin_catname":
            await wiz_category_name(update, ctx, user, text)
            return
        elif state == "admin_channeluser":
            await wiz_channel_user(update, ctx, user, text)
            return
        elif state == "admin_channelinvite":
            await wiz_channel_invite(update, ctx, user, text)
            return
        elif state == "admin_channeltitle":
            await wiz_channel_title(update, ctx, user, text)
            return
        elif state == "admin_cardnum":
            await wiz_card_num(update, ctx, user, text)
            return
        elif state == "admin_cardholder":
            await wiz_card_holder(update, ctx, user, text)
            return
        elif state == "admin_cardbank":
            await wiz_card_bank(update, ctx, user, text)
            return
        elif state.startswith("admin_set_"):
            await wiz_setting_value(update, ctx, user, state[10:], text)
            return
        elif state == "admin_bc_text":
            await wiz_broadcast_content(update, ctx, user, update.effective_message)
            return
        else:
            user.state = None
            user.state_data = ""
            s.commit()
            from handlers.start import send_welcome
            await send_welcome(update, ctx)
            return
    finally:
        s.close()


# =====================================================
# Products: list
# =====================================================
async def admin_product_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    per_page = ADMIN_PER_PAGE
    offset = (page - 1) * per_page
    s = get_session()
    try:
        total = s.scalar(select(func.count()).select_from(Product)) or 0
        products = s.scalars(
            select(Product).order_by(Product.id.desc()).offset(offset).limit(per_page)
        ).all()
        rows: list[list] = []
        for p in products:
            price = toman(p.price) if p.price > 0 else "رایگان"
            badge = "✅" if p.is_active else "⬜"
            vip = "⭐" if p.is_vip else ""
            rows.append([InlineKeyboardButton(
                f"{badge} {vip} {p.name} — {price}",
                callback_data=f"adm_proddetails:{p.id}",
            )])
        pages = max(1, (total + per_page - 1) // per_page)
        if pages > 1:
            nav = [InlineKeyboardButton("●" + fa_num(i) if i == page else fa_num(i),
                    callback_data=f"adm_prodpage:{i}") for i in range(1, pages + 1)]
            rows.append(nav)
        rows.append([
            InlineKeyboardButton("➕ افزودن محصول", callback_data="adm_prodadd"),
            InlineKeyboardButton("⬅️ پنل", callback_data="adm_menu"),
        ])
        text = f"📦 <b>محصولات</b> ({fa_num(total)})"
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
            except Exception:
                await ctx.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
        else:
            await ctx.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
    finally:
        s.close()


# =====================================================
# Products: add step (ask for file upload)
# =====================================================
async def admin_product_add_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        user.state = "admin_pfile"
        user.state_data = ""
        s.commit()
    finally:
        s.close()
    await update.callback_query.edit_message_text(
        text="➕ افزودن محصول جدید\n\n📤 لطفاً فایل محصول را ارسال کنید (عکس، ویدیو یا فایل):",
        reply_markup=back_button(),
    )


# =====================================================
# Products: details
# =====================================================
async def admin_product_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE, prod_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        p = s.get(Product, prod_id)
        if not p:
            await update.callback_query.answer("محصول یافت نشد", show_alert=True)
            return
        cat = s.get(Category, p.category_id) if p.category_id else None
        price = toman(p.price) if p.price > 0 else "رایگان"
        status = "فعال ✅" if p.is_active else "غیرفعال ⬜"
        text = (
            f"📦 <b>{p.name}</b>\n\n"
            f"💰 قیمت: {price}\n"
            f"📁 دسته: {cat.name if cat else 'بدون دسته'}\n"
            f"⭐ VIP: {'بله' if p.is_vip else 'خیر'}\n"
            f"📊 وضعیت: {status}\n"
            f"📥 دانلودها: {fa_num(p.download_count)}\n"
            f"📦 حجم: {human_size(p.file_size)}\n"
            f"🏷 برچسب‌ها: {p.tags or '-'}\n"
        )
        if p.description:
            text += f"\n📝 {p.description}"
        rows = [
            [InlineKeyboardButton("✅/⬜ فعال/غیرفعال", callback_data=f"adm_prodtoggle:{p.id}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"adm_proddel:{p.id}")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_prodlist:1")],
        ]
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
    finally:
        s.close()


# =====================================================
# Products: toggle active
# =====================================================
async def admin_product_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE, prod_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        p = s.get(Product, prod_id)
        if p:
            p.is_active = 1 - p.is_active
            s.commit()
    finally:
        s.close()
    await admin_product_details(update, ctx, prod_id)


# =====================================================
# Products: delete
# =====================================================
async def admin_product_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE, prod_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        p = s.get(Product, prod_id)
        name = p.name if p else ""
        if p:
            filepath = FILES_DIR / p.file_path if p.file_path else None
            s.delete(p)
            s.commit()
            if filepath and filepath.is_file():
                try:
                    filepath.unlink()
                except OSError:
                    pass
    finally:
        s.close()
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🗑 محصول «{name}» حذف شد.",
    )
    await admin_product_list(update, ctx, 1)


# =====================================================
# Categories: list
# =====================================================
async def admin_category_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        cats = s.scalars(select(Category).order_by(Category.sort_order, Category.id)).all()
        rows: list[list] = []
        for c in cats:
            rows.append([
                InlineKeyboardButton(
                    ("✅ " if c.is_active else "⬜ ") + (c.icon or "") + " " + c.name,
                    callback_data=f"adm_catdel:{c.id}",
                ),
                InlineKeyboardButton("⬜" if c.is_active else "✅", callback_data=f"adm_cattoggle:{c.id}"),
            ])
        rows.append([InlineKeyboardButton("➕ افزودن دسته", callback_data="adm_catadd")])
        rows.append([InlineKeyboardButton("⬅️ پنل", callback_data="adm_menu")])
        await update.callback_query.edit_message_text(
            "📁 <b>دسته‌بندی‌ها</b>", reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML",
        )
    finally:
        s.close()


# =====================================================
# Categories: add (prompt for name)
# =====================================================
async def admin_category_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        text=("➕ نام دسته‌بندی جدید را بفرستید:\n"
              "(می‌توانید در ابتدای نام یک ایموجی به‌عنوان آیکن بگذارید، مثلا: 🎨 پس‌زمینه)\n\n"
              "/cancel برای لغو."),
        reply_markup=back_button(),
    )
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        user.state = "admin_catname"
        s.commit()
    finally:
        s.close()


# =====================================================
# Categories: wizard name handler
# =====================================================
async def wiz_category_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    text = text.strip()
    if not text:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id, text="❗ نام خالی است. /cancel برای لغو.",
            reply_markup=back_button(),
        )
        return
    icon = ""
    m = re.match(r"^(\S+)\s+(.+)$", text)
    if m:
        icon, text = m.group(1), m.group(2)
    s = get_session()
    try:
        user = _reload_user(s, user)
        max_sort = s.scalar(select(func.max(Category.sort_order))) or 0
        s.add(Category(name=text, icon=icon, sort_order=max_sort + 1, is_active=1))
        user.state = None
        s.commit()
    finally:
        s.close()
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id, text=f"✅ دسته «{text}» اضافه شد.",
    )
    await admin_category_list(update, ctx)


# =====================================================
# Categories: delete (prompt confirm)
# =====================================================
async def admin_category_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cat_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        c = s.get(Category, cat_id)
        name = c.name if c else ""
    finally:
        s.close()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"adm_catdelconfirm:{cat_id}")],
        [InlineKeyboardButton("❌ بازگشت", callback_data="adm_catlist")],
    ])
    await update.callback_query.edit_message_text(
        f"🗑 حذف دسته «{name}»؟ محصولات حذف نمی‌شوند ولی «بدون دسته» می‌شوند.",
        reply_markup=kb,
    )


# =====================================================
# Categories: delete confirm
# =====================================================
async def admin_category_delete_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cat_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        products = s.scalars(select(Product).where(Product.category_id == cat_id)).all()
        for p in products:
            p.category_id = None
        c = s.get(Category, cat_id)
        if c:
            s.delete(c)
        s.commit()
    finally:
        s.close()
    await admin_category_list(update, ctx)


# =====================================================
# Categories: toggle active
# =====================================================
async def admin_category_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cat_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        cat = s.get(Category, cat_id)
        if cat:
            cat.is_active = 1 - cat.is_active
            s.commit()
    finally:
        s.close()
    await admin_category_list(update, ctx)


# =====================================================
# Orders: list (by status)
# =====================================================
async def admin_order_list(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, status: str, page: int
) -> None:
    await update.callback_query.answer()
    valid = ["pending", "approved", "rejected", "need_info", "all"]
    if status not in valid:
        status = "pending"
    per_page = ADMIN_PER_PAGE
    offset = (page - 1) * per_page
    s = get_session()
    try:
        if status == "all":
            total = s.scalar(select(func.count()).select_from(Order)) or 0
            orders = s.execute(
                select(Order, Product.name)
                .outerjoin(Product, Product.id == Order.product_id)
                .order_by(Order.id.desc()).offset(offset).limit(per_page)
            ).all()
        else:
            total = s.scalar(select(func.count()).select_from(Order).where(Order.status == status)) or 0
            orders = s.execute(
                select(Order, Product.name)
                .outerjoin(Product, Product.id == Order.product_id)
                .where(Order.status == status)
                .order_by(Order.id.desc()).offset(offset).limit(per_page)
            ).all()
        labels = {"pending": "⏳ در انتظار", "approved": "✅ تأیید",
                  "rejected": "❌ رد", "need_info": "❓ نیاز توضیح", "all": "📋 همه"}
        filter_row = [InlineKeyboardButton(
            ("● " if k == status else "") + lbl, callback_data=f"adm_orderpage:{k}:1"
        ) for k, lbl in labels.items()]
        rows = [filter_row]
        for o, pname in orders:
            rows.append([InlineKeyboardButton(
                f"🧾 {o.order_code} — {pname or '(حذف شده)'} ({fa_num(o.price)}ت)",
                callback_data=f"adm_order:{o.id}",
            )])
        pages = max(1, (total + per_page - 1) // per_page)
        if pages > 1:
            nav = [InlineKeyboardButton("●" + fa_num(i) if i == page else fa_num(i),
                    callback_data=f"adm_orderpage:{status}:{i}") for i in range(1, pages + 1)]
            rows.append(nav)
        rows.append([InlineKeyboardButton("⬅️ پنل", callback_data="adm_menu")])
        await update.callback_query.edit_message_text(
            text=f"📋 <b>سفارش‌ها</b> ({fa_num(total)})", reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="HTML",
        )
    finally:
        s.close()


# =====================================================
# Orders: show details
# =====================================================
async def admin_order_show(update: Update, ctx: ContextTypes.DEFAULT_TYPE, order_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        o = s.get(Order, order_id)
        if not o:
            await update.callback_query.answer("سفارش یافت نشد", show_alert=True)
            await admin_order_list(update, ctx, "pending", 1)
            return
        p = s.get(Product, o.product_id)
        u = s.get(User, o.user_id)
        badges = {"pending": "⏳ در انتظار", "approved": "✅ تأیید",
                  "rejected": "❌ رد", "need_info": "❓ نیاز توضیح"}
        text = (
            f"📋 <b>سفارش</b> {o.order_code}\n\n"
            f"📦 محصول: {p.name if p else '-'}\n"
            f"💰 مبلغ: {toman(o.price)}\n"
            f"👤 خریدار: {u.first_name if u else '-'}"
            f"{' @' + u.username if u and u.username else ''}\n"
            f"📱 تلگرام: <code>{fa_num(u.telegram_id) if u else ''}</code>\n"
            f"📌 وضعیت: {badges.get(o.status, o.status)}\n"
        )
        if o.receipt_message:
            text += f"📝 توضیح: {o.receipt_message}\n"
        if o.admin_note:
            text += f"🔖 یادداشت: {o.admin_note}\n"
        rows = []
        if o.status in ("pending", "need_info"):
            rows.append([
                InlineKeyboardButton("✅ تأیید و ارسال", callback_data=f"admin_approve:{o.id}"),
                InlineKeyboardButton("❌ رد", callback_data=f"admin_reject:{o.id}"),
            ])
            rows.append([InlineKeyboardButton("❓ درخواست توضیح", callback_data=f"admin_info:{o.id}")])
        if o.receipt_file_id:
            rows.append([InlineKeyboardButton("👁 نمایش رسید", callback_data=f"adm_orderview:{o.id}")])
        rows.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_orderlist:pending:1")])
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML",
        )
    finally:
        s.close()


# =====================================================
# Orders: view receipt file
# =====================================================
async def admin_order_view(update: Update, ctx: ContextTypes.DEFAULT_TYPE, order_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        o = s.get(Order, order_id)
        if o and o.receipt_file_id:
            if o.receipt_file_type == "photo":
                await ctx.bot.send_photo(update.effective_chat.id, o.receipt_file_id,
                                         caption=f"🧾 رسید {o.order_code}")
            elif o.receipt_file_type == "document":
                await ctx.bot.send_document(update.effective_chat.id, o.receipt_file_id,
                                            caption=f"🧾 رسید {o.order_code}")
            else:
                await ctx.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"🧾 توضیح رسید {o.order_code}:\n{o.receipt_message or '(بدون توضیح)'}",
                )
        else:
            await update.callback_query.answer("رسید وجود ندارد", show_alert=True)
    finally:
        s.close()
# Product wizard: file download (called from start.py for non-text)
# =====================================================
async def wiz_product_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User) -> None:
    """Called when admin sends a file while state='admin_pfile'."""
    msg = update.effective_message
    file_id = None
    file_name = "file"

    if msg.document:
        file_id = msg.document.file_id
        file_name = msg.document.file_name or "file"
    elif msg.photo:
        file_id = msg.photo[-1].file_id
        file_name = "photo.jpg"
    elif msg.video and msg.video.file_id:
        file_id = msg.video.file_id
        file_name = "video.mp4"

    if not file_id:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❗ لطفاً یک فایل یا عکس بفرستید. یا /cancel برای لغو.",
            reply_markup=back_button(),
        )
        return

    ext = ""
    if "." in file_name:
        ext = file_name.rsplit(".", 1)[-1].lower()
    elif msg.photo:
        ext = "jpg"
    local_name = secrets.token_hex(8) + ("." + ext if ext else "")
    dest = await save_telegram_file(ctx.bot, file_id, FILES_DIR, local_name)
    if not dest:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ دانلود فایل از تلگرام ناموفق بود. دوباره فایل را بفرستید یا /cancel.",
        )
        return

    size = dest.stat().st_size if dest.exists() else 0
    sd = {"file": f"files/{local_name}", "name": file_name, "size": str(size), "ext": ext}
    s = get_session()
    try:
        # user object may be detached from a closed session in start.py —  merge to keep writes valid.
        user = s.merge(user)
        user.state_data = _format_sd(sd)
        user.state = "admin_pname"
        s.commit()
    finally:
        s.close()
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✅ فایل دریافت شد ({human_size(size)})\n\n📝 نام محصول را بفرستید:",
        reply_markup=back_button(),
    )


# =====================================================
# Product wizard: name
# =====================================================
async def wiz_product_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    text = text.strip()
    if not text:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id, text="❗ نام خالی است. /cancel برای لغو.",
            reply_markup=back_button(),
        )
        return
    sd = _parse_sd(user.state_data)
    sd["pname"] = text
    s = get_session()
    try:
        user = _reload_user(s, user)
        user.state_data = _format_sd(sd)
        user.state = "admin_pprice"
        s.commit()
    finally:
        s.close()
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text="💰 حالا قیمت محصول را به تومان بفرستید (۰ = رایگان):",
        reply_markup=back_button(),
    )


# =====================================================
# Product wizard: price → show category picker
# =====================================================
async def wiz_product_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    price = int(re.sub(r"\D", "", text) or "0")
    sd = _parse_sd(user.state_data)
    sd["price"] = str(price)
    s = get_session()
    try:
        user = _reload_user(s, user)
        user.state_data = _format_sd(sd)
        user.state = "admin_pcat"
        s.commit()
        cats = s.scalars(select(Category).order_by(Category.sort_order, Category.id)).all()
    finally:
        s.close()
    rows: list[list] = []
    cols: list = []
    for c in cats:
        label = (c.icon or "") + " " + c.name
        cols.append(InlineKeyboardButton(label, callback_data=f"adm_pcatset:{c.id}"))
        if len(cols) == 2:
            rows.append(cols)
            cols = []
    if cols:
        rows.append(cols)
    rows.append([InlineKeyboardButton("➖ بدون دسته", callback_data="adm_pcatset:0")])
    rows.append([InlineKeyboardButton("❌ لغو", callback_data="adm_pcancel")])
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text="📁 دسته‌بندی محصول را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# =====================================================
# Product wizard: set category (callback) → ask tags
# =====================================================
async def admin_product_set_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cat_id: int) -> None:
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        sd = _parse_sd(user.state_data)
        sd["category_id"] = str(cat_id) if cat_id > 0 else ""
        user.state_data = _format_sd(sd)
        user.state = "admin_ptags"
        s.commit()
    finally:
        s.close()
    await update.callback_query.answer()
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🏷 برچسب‌ها را بفرستید (با ویرگول جدا کنید، یا - برای خالی):",
        reply_markup=back_button(),
    )


# =====================================================
# Product wizard: tags
# =====================================================
async def wiz_product_tags(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    text = text.strip()
    tags = "" if text in ("", "-") else text
    sd = _parse_sd(user.state_data)
    sd["tags"] = tags
    s = get_session()
    try:
        user = _reload_user(s, user)
        user.state_data = _format_sd(sd)
        user.state = "admin_pdesc"
        s.commit()
    finally:
        s.close()
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text="📜 توضیحات محصول را بفرستید (یا - برای خالی):",
        reply_markup=back_button(),
    )


# =====================================================
# Product wizard: desc → show VIP picker
# =====================================================
async def wiz_product_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    text = text.strip()
    desc = "" if text in ("", "-") else text
    sd = _parse_sd(user.state_data)
    sd["description"] = desc
    s = get_session()
    try:
        user = _reload_user(s, user)
        user.state_data = _format_sd(sd)
        user.state = "admin_pvip"
        s.commit()
    finally:
        s.close()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 معمولی", callback_data="adm_pvipset:0")],
        [InlineKeyboardButton("⭐ VIP", callback_data="adm_pvipset:1")],
        [InlineKeyboardButton("❌ لغو", callback_data="adm_pcancel")],
    ])
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id, text="⭐ آیا این محصول VIP است؟", reply_markup=kb,
    )


# =====================================================
# Product wizard: set VIP → show save/cancel buttons
# =====================================================
async def admin_product_set_vip(update: Update, ctx: ContextTypes.DEFAULT_TYPE, vip: int) -> None:
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        sd = _parse_sd(user.state_data)
        sd["is_vip"] = str(vip)
        user.state_data = _format_sd(sd)
        user.state = "admin_psave"
        s.commit()
    finally:
        s.close()
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 عمومی (فعال)", callback_data="adm_psave:1")],
        [InlineKeyboardButton("🔒 غیرفعال (پیش‌نویس)", callback_data="adm_psave:0")],
        [InlineKeyboardButton("❌ لغو", callback_data="adm_pcancel")],
    ])
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id, text="✅ وضعیت انتشار محصول:", reply_markup=kb,
    )


# =====================================================
# Product wizard: save (callback)
# =====================================================
async def admin_product_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE, active: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        sd = _parse_sd(user.state_data)
        if not sd.get("pname") or not sd.get("file"):
            user.state = None
            user.state_data = ""
            s.commit()
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ اطلاعات محصول ناقص است. دوباره امتحان کنید.",
            )
            await admin_menu(update, ctx)
            return
        p = Product(
            name=sd["pname"],
            description=sd.get("description", ""),
            price=int(sd.get("price", "0") or "0"),
            category_id=int(sd["category_id"]) if sd.get("category_id") else None,
            file_path=sd["file"],
            file_name=sd.get("name", ""),
            file_size=int(sd.get("size", "0") or "0"),
            tags=sd.get("tags", ""),
            is_vip=int(sd.get("is_vip", "0") or "0"),
            is_active=active,
        )
        s.add(p)
        user.state = None
        user.state_data = ""
        s.commit()
        name = sd["pname"]
    finally:
        s.close()
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✅ محصول «{name}» با موفقیت ذخیره شد.",
    )
    await admin_product_list(update, ctx, 1)


# =====================================================
# Product wizard: cancel (callback)
# =====================================================
async def admin_product_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        user.state = None
        user.state_data = ""
        s.commit()
    finally:
        s.close()
    await admin_menu(update, ctx)


# =====================================================
# Channels: list
# =====================================================
async def admin_channel_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        channels = s.scalars(select(Channel).order_by(Channel.id)).all()
        rows = []
        for ch in channels:
            status_badge = "✅" if ch.is_active else "⬜"
            rows.append([
                InlineKeyboardButton(
                    f"{status_badge} {ch.title or ch.channel_username}",
                    callback_data=f"adm_channeltoggle:{ch.id}"
                ),
                InlineKeyboardButton("🗑 حذف", callback_data=f"adm_channeldel:{ch.id}")
            ])
        rows.append([InlineKeyboardButton("➕ افزودن کانال", callback_data="adm_channeladd")])
        rows.append([InlineKeyboardButton("⬅️ پنل", callback_data="adm_menu")])
        
        text = "📢 <b>کانال‌های اجباری عضویت</b>\n\nکاربران قبل از استفاده از ربات باید در این کانال‌ها عضو شوند."
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="HTML"
        )
    finally:
        s.close()

# =====================================================
# Channels: add
# =====================================================
async def admin_channel_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        user.state = "admin_channeluser"
        user.state_data = ""
        s.commit()
    finally:
        s.close()
    await update.callback_query.edit_message_text(
        text="➕ افزودن کانال جدید\n\n🆔 لطفا آیدی کانال را بدون @ یا با @ ارسال کنید (مثلا: @mychannel یا mychannel):",
        reply_markup=back_button(),
    )

# =====================================================
# Channels: wizard - channel username
# =====================================================
async def wiz_channel_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    text = text.strip()
    if not text:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❗ آیدی کانال خالی است. مجددا تلاش کنید یا /cancel را بزنید.",
            reply_markup=back_button(),
        )
        return
    username = text if text.startswith("@") else f"@{text}"
    
    title = ""
    channel_id = ""
    try:
        chat = await ctx.bot.get_chat(username)
        title = chat.title or ""
        channel_id = str(chat.id)
    except Exception:
        pass

    s = get_session()
    try:
        user = _reload_user(s, user)
        sd = {"username": username, "title": title, "channel_id": channel_id}
        user.state = "admin_channelinvite"
        user.state_data = _format_sd(sd)
        s.commit()
    finally:
        s.close()
        
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔗 لینک دعوت کانال {username} را ارسال کنید (مثلا: https://t.me/...):",
        reply_markup=back_button(),
    )

# =====================================================
# Channels: wizard - channel invite link
# =====================================================
async def wiz_channel_invite(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    text = text.strip()
    if not text.startswith("http"):
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❗ لینک دعوت نامعتبر است. باید با http یا https شروع شود. دوباره بفرستید:",
            reply_markup=back_button(),
        )
        return
        
    sd = _parse_sd(user.state_data)
    sd["invite_link"] = text
    s = get_session()
    try:
        user = _reload_user(s, user)
        user.state = "admin_channeltitle"
        user.state_data = _format_sd(sd)
        s.commit()
    finally:
        s.close()
        
    title_prompt = f"✍️ عنوان نمایشی کانال را ارسال کنید (مثلا کانال رسمی ما):"
    if sd.get("title"):
        title_prompt += f"\n(یا بفرستید: - برای استفاده از عنوان پیش‌فرض: {sd['title']})"
        
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=title_prompt,
        reply_markup=back_button(),
    )

# =====================================================
# Channels: wizard - channel title & save
# =====================================================
async def wiz_channel_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    text = text.strip()
    sd = _parse_sd(user.state_data)
    
    title = sd.get("title") or sd.get("username")
    if text != "-":
        title = text
        
    s = get_session()
    try:
        user = _reload_user(s, user)
        new_channel = Channel(
            channel_username=sd["username"],
            channel_id=sd.get("channel_id") or None,
            title=title,
            invite_link=sd["invite_link"],
            is_active=1
        )
        s.add(new_channel)
        user.state = None
        user.state_data = ""
        s.commit()
    finally:
        s.close()
        
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✅ کانال «{title}» با موفقیت اضافه شد."
    )

# =====================================================
# Channels: delete
# =====================================================
async def admin_channel_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE, chan_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        ch = s.get(Channel, chan_id)
        if ch:
            title = ch.title or ch.channel_username
            s.delete(ch)
            s.commit()
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🗑 کانال «{title}» حذف شد."
            )
    finally:
        s.close()
    await admin_channel_list(update, ctx)

# =====================================================
# Channels: toggle active
# =====================================================
async def admin_channel_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE, chan_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        ch = s.get(Channel, chan_id)
        if ch:
            ch.is_active = 1 - ch.is_active
            s.commit()
    finally:
        s.close()
    await admin_channel_list(update, ctx)


# =====================================================
# Cards: list
# =====================================================
async def admin_card_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        cards = s.scalars(select(Card).order_by(Card.sort_order, Card.id)).all()
        rows = []
        for c in cards:
            status_badge = "✅" if c.is_active else "⬜"
            rows.append([
                InlineKeyboardButton(
                    f"{status_badge} {c.card_number} — {c.holder_name}",
                    callback_data=f"adm_cardtoggle:{c.id}"
                ),
                InlineKeyboardButton("🗑 حذف", callback_data=f"adm_carddel:{c.id}")
            ])
        rows.append([InlineKeyboardButton("➕ افزودن کارت بانکی", callback_data="adm_cardadd")])
        rows.append([InlineKeyboardButton("⬅️ پنل", callback_data="adm_menu")])
        
        text = "💳 <b>کارت‌های بانکی جهت واریز</b>\n\nکارت‌های فعال در فاکتور پرداخت به کاربر نمایش داده می‌شوند."
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="HTML"
        )
    finally:
        s.close()

# =====================================================
# Cards: add
# =====================================================
async def admin_card_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        user.state = "admin_cardnum"
        user.state_data = ""
        s.commit()
    finally:
        s.close()
    await update.callback_query.edit_message_text(
        text="➕ افزودن کارت بانکی جدید\n\n🔢 لطفا شماره کارت ۱۶ رقمی را ارسال کنید:",
        reply_markup=back_button(),
    )

# =====================================================
# Cards: wizard - card number
# =====================================================
async def wiz_card_num(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    text = re.sub(r"\D", "", text)
    if len(text) < 16 or len(text) > 20:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❗ شماره کارت باید بین ۱۶ تا ۲۰ رقم باشد. دوباره بفرستید:",
            reply_markup=back_button(),
        )
        return
    
    sd = {"card_num": text}
    s = get_session()
    try:
        user = _reload_user(s, user)
        user.state = "admin_cardholder"
        user.state_data = _format_sd(sd)
        s.commit()
    finally:
        s.close()
        
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text="👤 نام دارنده کارت را ارسال کنید:",
        reply_markup=back_button(),
    )

# =====================================================
# Cards: wizard - card holder
# =====================================================
async def wiz_card_holder(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    text = text.strip()
    if not text:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❗ نام دارنده کارت نمی‌تواند خالی باشد. دوباره بفرستید:",
            reply_markup=back_button(),
        )
        return
        
    sd = _parse_sd(user.state_data)
    sd["holder"] = text
    s = get_session()
    try:
        user = _reload_user(s, user)
        user.state = "admin_cardbank"
        user.state_data = _format_sd(sd)
        s.commit()
    finally:
        s.close()
        
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🏦 نام بانک را ارسال کنید (یا - برای خالی):",
        reply_markup=back_button(),
    )

# =====================================================
# Cards: wizard - card bank & save
# =====================================================
async def wiz_card_bank(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, text: str) -> None:
    text = text.strip()
    sd = _parse_sd(user.state_data)
    bank = "" if text == "-" else text
    
    s = get_session()
    try:
        user = _reload_user(s, user)
        new_card = Card(
            card_number=sd["card_num"],
            holder_name=sd["holder"],
            bank_name=bank,
            is_active=1
        )
        s.add(new_card)
        user.state = None
        user.state_data = ""
        s.commit()
    finally:
        s.close()
        
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✅ کارت بانکی {sd['card_num']} با موفقیت ذخیره شد."
    )

# =====================================================
# Cards: delete
# =====================================================
async def admin_card_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE, card_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        c = s.get(Card, card_id)
        if c:
            num = c.card_number
            s.delete(c)
            s.commit()
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🗑 کارت بانکی {num} حذف شد."
            )
    finally:
        s.close()
    await admin_card_list(update, ctx)

# =====================================================
# Cards: toggle active
# =====================================================
async def admin_card_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE, card_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        c = s.get(Card, card_id)
        if c:
            c.is_active = 1 - c.is_active
            s.commit()
    finally:
        s.close()
    await admin_card_list(update, ctx)


# =====================================================
# Settings: menu
# =====================================================
async def admin_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        welcome = setting(s, "welcome_text", "-")
        rules = setting(s, "rules_text", "-")
        support = setting(s, "support_text", "-")
        pay = setting(s, "payment_text", "-")
        reward = setting(s, "referral_reward", "0")
        store = setting(s, "store_name", "-")
        notify = setting(s, "admin_notify_id", "0")
        per_page = setting(s, "per_page", "8")
        
        def truncate(t):
            t = t.replace('\n', ' ')
            return t[:30] + "..." if len(t) > 30 else t
            
        text = (
            "⚙️ <b>تنظیمات ربات</b>\n\n"
            f"🏪 نام فروشگاه: {store}\n"
            f"👋 متن خوش‌آمد: <code>{truncate(welcome)}</code>\n"
            f"📖 متن قوانین: <code>{truncate(rules)}</code>\n"
            f"📞 متن پشتیبانی: <code>{truncate(support)}</code>\n"
            f"💳 متن پرداخت: <code>{truncate(pay)}</code>\n"
            f"🎁 پاداش دعوت: {fa_num(reward)} تومان\n"
            f"🔔 آیدی نوتیفیکیشن ادمین: <code>{notify}</code>\n"
            f"📄 تعداد در صفحه: {fa_num(per_page)}\n"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏪 ویرایش نام فروشگاه", callback_data="adm_setstore")],
            [InlineKeyboardButton("👋 ویرایش متن خوش‌آمد", callback_data="adm_setstart")],
            [InlineKeyboardButton("📖 ویرایش متن قوانین", callback_data="adm_setrules")],
            [InlineKeyboardButton("📞 ویرایش متن پشتیبانی", callback_data="adm_setsupport")],
            [InlineKeyboardButton("💳 ویرایش متن پرداخت", callback_data="adm_setpay")],
            [InlineKeyboardButton("🎁 ویرایش پاداش دعوت", callback_data="adm_setreward")],
            [InlineKeyboardButton("🔔 ویرایش آیدی نوتیفیکیشن", callback_data="adm_setnotifier")],
            [InlineKeyboardButton("📄 ویرایش تعداد در صفحه", callback_data="adm_setperpage")],
            [InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="adm_menu")]
        ])
        
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    finally:
        s.close()

# =====================================================
# Settings: prompt for key
# =====================================================
async def admin_set_setting(update: Update, ctx: ContextTypes.DEFAULT_TYPE, key: str, name: str) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        user.state = f"admin_set_{key}"
        user.state_data = ""
        s.commit()
        current_val = setting(s, key, "")
    finally:
        s.close()
        
    prompt = (
        f"✍️ لطفا مقدار جدید را برای <b>{name}</b> ارسال کنید:\n\n"
        f"مقدار فعلی:\n<code>{current_val}</code>\n\n"
        f"/cancel برای انصراف."
    )
    await update.callback_query.edit_message_text(
        text=prompt,
        reply_markup=back_button(),
        parse_mode="HTML"
    )

# =====================================================
# Settings: wizard - save setting value
# =====================================================
async def wiz_setting_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, setting_key: str, text: str) -> None:
    text = text.strip()
    s = get_session()
    try:
        user = _reload_user(s, user)
        set_setting(s, setting_key, text)
        user.state = None
        user.state_data = ""
        s.commit()
    finally:
        s.close()
        
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ تنظیمات با موفقیت بروزرسانی شد."
    )


# =====================================================
# Broadcast: menu
# =====================================================
async def admin_broadcast_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    text = "📢 <b>ارسال پیام همگانی</b>\n\nنوع پیام خود را انتخاب کنید:"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 پیام متنی", callback_data="adm_broadcast_text")],
        [InlineKeyboardButton("🖼 پیام تصویری (عکس)", callback_data="adm_broadcast_photo")],
        [InlineKeyboardButton("📁 پیام فایل (سند)", callback_data="adm_broadcast_file")],
        [InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="adm_menu")]
    ])
    await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

# =====================================================
# Broadcast: start
# =====================================================
async def admin_broadcast_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE, bc_type: str) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        user.state = "admin_bc_text"
        user.state_data = _format_sd({"bc_type": bc_type})
        s.commit()
    finally:
        s.close()
    
    prompts = {
        "text": "لطفا متن پیام خود را ارسال کنید:",
        "photo": "لطفا تصویر خود را به همراه کپشن (اختیاری) ارسال کنید:",
        "document": "لطفا فایل سند خود را به همراه کپشن (اختیاری) ارسال کنید:"
    }
    prompt = prompts.get(bc_type, "لطفا پیام خود را ارسال کنید:")
    
    await update.callback_query.edit_message_text(
        text=f"📢 <b>ارسال پیام همگانی ({bc_type})</b>\n\n{prompt}\n\n/cancel برای انصراف.",
        reply_markup=back_button(),
        parse_mode="HTML"
    )

# =====================================================
# Broadcast: wizard - content
# =====================================================
async def wiz_broadcast_content(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User, message) -> None:
    s = get_session()
    try:
        # user may be detached from a closed session — merge first.
        user = s.merge(user)
        sd = _parse_sd(user.state_data)
        bc_type = sd.get("bc_type", "text")
        
        content = None
        file_id = None
        caption = None
        
        if message.photo:
            bc_type = "photo"
            file_id = message.photo[-1].file_id
            caption = message.caption or ""
        elif message.document:
            bc_type = "document"
            file_id = message.document.file_id
            caption = message.caption or ""
        elif message.video:
            bc_type = "video"
            file_id = message.video.file_id
            caption = message.caption or ""
        else:
            bc_type = "text"
            content = message.text or ""
            
        bc = Broadcast(
            bc_type=bc_type,
            content=content,
            file_id=file_id,
            caption=caption,
            status="pending",
            total=0,
            sent=0,
            failed=0
        )
        s.add(bc)
        s.flush()
        
        user.state = None
        user.state_data = ""
        s.commit()
        
        preview_text = f"📢 <b>پیش‌نمایش پیام همگانی ({bc_type}):</b>\n\n"
        if bc_type == "text":
            preview_text += content
        else:
            preview_text += f"[فایل رسانه]\n📝 شرح: {caption or '(بدون شرح)'}"
            
        preview_text += "\n\n⚠️ آیا از ارسال این پیام برای تمام کاربران مطمئن هستید؟"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ بله، ارسال کن", callback_data=f"adm_broadcast_send:{bc.id}")],
            [InlineKeyboardButton("❌ انصراف", callback_data="adm_broadcast_cancel")]
        ])
        
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=preview_text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    finally:
        s.close()

# =====================================================
# Broadcast: send
# =====================================================
async def admin_broadcast_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE, bc_id: int) -> None:
    await update.callback_query.answer("ارسال آغاز شد 🚀")
    import asyncio
    asyncio.create_task(broadcast_task(ctx.bot, update.effective_chat.id, bc_id))
    
    await update.callback_query.edit_message_text(
        "🚀 عملیات ارسال پیام همگانی در پس‌زمینه شروع شد.\nنتایج پس از پایان به شما گزارش خواهد شد.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ پنل", callback_data="adm_menu")]])
    )

# =====================================================
# Broadcast: background task helper
# =====================================================
async def broadcast_task(bot, admin_chat_id: int, bc_id: int) -> None:
    import asyncio
    s = get_session()
    try:
        bc = s.get(Broadcast, bc_id)
        if not bc or bc.status != "pending":
            return
        
        bc.status = "sending"
        s.commit()
        
        users = s.scalars(select(User.telegram_id)).all()
        bc.total = len(users)
        s.commit()
        
        sent_count = 0
        failed_count = 0
        
        for tid in users:
            try:
                if bc.bc_type == "text":
                    await bot.send_message(chat_id=tid, text=bc.content)
                elif bc.bc_type == "photo":
                    await bot.send_photo(chat_id=tid, photo=bc.file_id, caption=bc.caption)
                elif bc.bc_type == "document":
                    await bot.send_document(chat_id=tid, document=bc.file_id, caption=bc.caption)
                elif bc.bc_type == "video":
                    await bot.send_video(chat_id=tid, video=bc.file_id, caption=bc.caption)
                sent_count += 1
            except Exception:
                failed_count += 1
                
            if (sent_count + failed_count) % 10 == 0:
                s_bg = get_session()
                try:
                    bc_bg = s_bg.get(Broadcast, bc_id)
                    if bc_bg:
                        bc_bg.sent = sent_count
                        bc_bg.failed = failed_count
                        s_bg.commit()
                except Exception:
                    pass
                finally:
                    s_bg.close()
                    
            await asyncio.sleep(0.05)
            
        bc.sent = sent_count
        bc.failed = failed_count
        bc.status = "completed"
        s.commit()
        
        report = (
            "📢 <b>عملیات ارسال پیام همگانی پایان یافت!</b>\n\n"
            f"✅ ارسال موفق: {fa_num(sent_count)}\n"
            f"❌ ارسال ناموفق: {fa_num(failed_count)}\n"
            f"📊 کل کاربران: {fa_num(bc.total)}"
        )
        await bot.send_message(chat_id=admin_chat_id, text=report, parse_mode="HTML")
        
    except Exception as e:
        s_bg = get_session()
        try:
            log_error(s_bg, "broadcast error", str(e))
        except Exception:
            pass
        finally:
            s_bg.close()
    finally:
        s.close()

# =====================================================
# Broadcast: cancel
# =====================================================
async def admin_broadcast_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        user.state = None
        user.state_data = ""
        s.commit()
    finally:
        s.close()
    await admin_menu(update, ctx)


# =====================================================
# Logs: viewer
# =====================================================
async def admin_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    await update.callback_query.answer()
    per_page = ADMIN_PER_PAGE
    offset = (page - 1) * per_page
    s = get_session()
    try:
        total = s.scalar(select(func.count()).select_from(Log)) or 0
        logs = s.scalars(
            select(Log).order_by(Log.id.desc()).offset(offset).limit(per_page)
        ).all()
        
        rows = []
        for l in logs:
            msg_trunc = l.message[:30] + "..." if len(l.message) > 30 else l.message
            rows.append([
                InlineKeyboardButton(f"🐛 {l.level}: {msg_trunc}", callback_data=f"adm_logsdetails:{l.id}"),
                InlineKeyboardButton("🗑 حذف", callback_data=f"adm_logsdel:{l.id}")
            ])
            
        pages = max(1, (total + per_page - 1) // per_page)
        if pages > 1:
            nav = [InlineKeyboardButton("●" + fa_num(i) if i == page else fa_num(i),
                    callback_data=f"adm_logspage:{i}") for i in range(1, pages + 1)]
            rows.append(nav)
            
        rows.append([
            InlineKeyboardButton("🧹 پاکسازی کل لاگ‌ها", callback_data="adm_logsclear"),
            InlineKeyboardButton("⬅️ پنل", callback_data="adm_menu")
        ])
        
        text = f"🐛 <b>لاگ خطاهای ربات</b> ({fa_num(total)} خطا)"
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
    finally:
        s.close()

# =====================================================
# Logs: show details
# =====================================================
async def admin_logs_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE, log_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        l = s.get(Log, log_id)
        if not l:
            await update.callback_query.answer("لاگ یافت نشد", show_alert=True)
            await admin_logs(update, ctx, 1)
            return
        
        text = (
            f"🐛 <b>جزئیات خطای #{l.id}</b>\n\n"
            f"📅 زمان: <code>{l.created_at}</code>\n"
            f"🏷 سطح: <code>{l.level}</code>\n\n"
            f"📝 پیام خطا:\n<code>{l.message}</code>\n\n"
            f"🧩 زمینه (Context):\n<code>{l.context or '-'}</code>"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 حذف این لاگ", callback_data=f"adm_logsdel:{l.id}")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_logs:1")]
        ])
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    finally:
        s.close()

# =====================================================
# Logs: clear all
# =====================================================
async def admin_logs_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        s.execute(delete(Log))
        s.commit()
        await ctx.bot.send_message(chat_id=update.effective_chat.id, text="🧹 تمام لاگ‌ها پاک شدند.")
    finally:
        s.close()
    await admin_logs(update, ctx, 1)

# =====================================================
# Logs: delete single log
# =====================================================
async def admin_logs_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE, log_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        log = s.get(Log, log_id)
        if log:
            s.delete(log)
            s.commit()
    finally:
        s.close()
    await admin_logs(update, ctx, 1)


# =====================================================
# Users: list
# =====================================================
async def admin_user_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page: int) -> None:
    await update.callback_query.answer()
    per_page = ADMIN_PER_PAGE
    offset = (page - 1) * per_page
    s = get_session()
    try:
        total = s.scalar(select(func.count()).select_from(User)) or 0
        users = s.scalars(
            select(User).order_by(User.id.desc()).offset(offset).limit(per_page)
        ).all()
        
        rows = []
        for u in users:
            display_name = u.first_name or u.username or f"کاربر {u.telegram_id}"
            ban_badge = "❌ " if u.is_blocked else ""
            admin_badge = "⭐ " if u.is_admin else ""
            rows.append([InlineKeyboardButton(
                f"{ban_badge}{admin_badge}{display_name} ({fa_num(u.telegram_id)})",
                callback_data=f"adm_usershow:{u.id}"
            )])
            
        pages = max(1, (total + per_page - 1) // per_page)
        if pages > 1:
            nav = [InlineKeyboardButton("●" + fa_num(i) if i == page else fa_num(i),
                    callback_data=f"adm_userpage:{i}") for i in range(1, pages + 1)]
            rows.append(nav)
            
        rows.append([InlineKeyboardButton("⬅️ پنل", callback_data="adm_menu")])
        
        text = f"👤 <b>لیست کاربران ربات</b> ({fa_num(total)} کاربر)"
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
    finally:
        s.close()

# =====================================================
# Users: show details
# =====================================================
async def admin_user_show(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        u = s.get(User, user_id)
        if not u:
            await update.callback_query.answer("کاربر یافت نشد", show_alert=True)
            await admin_user_list(update, ctx, 1)
            return
            
        orders_count = s.scalar(select(func.count()).select_from(Order).where(Order.user_id == u.id)) or 0
        refs_count = s.scalar(select(func.count()).select_from(User).where(User.referred_by == u.id)) or 0
        
        status = "❌ مسدود شده" if u.is_blocked else "✅ فعال"
        role = "⭐ ادمین" if u.is_admin else "👤 کاربر معمولی"
        
        text = (
            f"👤 <b>پروفایل کاربر</b>\n\n"
            f"🆔 شناسه دیتابیس: <code>{u.id}</code>\n"
            f"📱 شناسه تلگرام: <code>{fa_num(u.telegram_id)}</code>\n"
            f"👋 نام: {u.first_name or '-'}\n"
            f"📛 نام خانوادگی: {u.last_name or '-'}\n"
            f"📧 نام کاربری: @{u.username if u.username else '-'}\n"
            f"📅 تاریخ عضویت: <code>{u.created_at}</code>\n"
            f"📊 وضعیت: {status}\n"
            f"🏷 نقش: {role}\n\n"
            f"🧾 تعداد سفارشات: {fa_num(orders_count)}\n"
            f"👥 تعداد زیرمجموعه‌ها: {fa_num(refs_count)}\n"
            f"💰 موجودی دعوت: {toman(u.referral_balance)}\n"
        )
        
        ban_lbl = "🔓 رفع مسدودیت" if u.is_blocked else "🔒 مسدود کردن"
        admin_lbl = "👤 عزل از ادمینی" if u.is_admin else "⭐ ارتقا به ادمین"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(ban_lbl, callback_data=f"adm_userban:{u.id}")],
            [InlineKeyboardButton(admin_lbl, callback_data=f"adm_useradmin:{u.id}")],
            [InlineKeyboardButton("⬅️ بازگشت", callback_data="adm_userlist:1")]
        ])
        
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    finally:
        s.close()

# =====================================================
# Users: toggle ban
# =====================================================
async def admin_user_toggle_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        u = s.get(User, user_id)
        if u:
            if u.telegram_id == update.effective_user.id:
                await update.callback_query.answer("شما نمی‌توانید خودتان را مسدود کنید!", show_alert=True)
                return
            if u.telegram_id in cfg.admin_ids:
                await update.callback_query.answer("این کاربر ادمین اصلی ربات در تنظیمات است و مسدود نمی‌شود.", show_alert=True)
                return
                
            u.is_blocked = 1 - u.is_blocked
            s.commit()
            action = "مسدود" if u.is_blocked else "فعال"
            await update.callback_query.answer(f"کاربر {action} شد.")
    finally:
        s.close()
    await admin_user_show(update, ctx, user_id)

# =====================================================
# Users: toggle admin role
# =====================================================
async def admin_user_toggle_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    await update.callback_query.answer()
    s = get_session()
    try:
        u = s.get(User, user_id)
        if u:
            if u.telegram_id == update.effective_user.id:
                await update.callback_query.answer("شما نمی‌توانید نقش خودتان را تغییر دهید!", show_alert=True)
                return
            if u.telegram_id in cfg.admin_ids:
                await update.callback_query.answer("این کاربر ادمین اصلی ربات در تنظیمات است و تغییر نمی‌کند.", show_alert=True)
                return
                
            u.is_admin = 1 - u.is_admin
            s.commit()
            role = "به عنوان ادمین ارتقا یافت" if u.is_admin else "از ادمینی عزل شد"
            await update.callback_query.answer(f"کاربر {role}.")
    finally:
        s.close()
    await admin_user_show(update, ctx, user_id)
