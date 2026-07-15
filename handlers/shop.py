"""Shop, categories, products, search, profile, referral, orders, and state wizard."""
from __future__ import annotations

import re

from sqlalchemy import func, or_, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db import (
    Card,
    Category,
    Order,
    Product,
    User,
    get_session,
    setting,
)
from helpers import (
    ensure_user,
    fa_num,
    is_user_admin,
    main_menu_kb,
    membership_kb,
    toman,
)
from services import check_required_channels_async


# -------------------------------------------------------------------- categories
async def show_categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = get_session()
    try:
        cats = s.scalars(
            select(Category).where(Category.is_active == 1).order_by(Category.sort_order, Category.id)
        ).all()
        rows = []
        cols = []
        for c in cats:
            label = (f"{c.icon} " if c.icon else "") + c.name
            cols.append(InlineKeyboardButton(label, callback_data=f"cat:{c.id}:1"))
            if len(cols) == 2:
                rows.append(cols)
                cols = []
        if cols:
            rows.append(cols)
        rows.append([InlineKeyboardButton("🏠 منو", callback_data="home")])
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📁 <b>دسته‌بندی‌ها</b>\n\nیک دسته را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="HTML",
        )
    finally:
        s.close()


async def show_products_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cat_id: int, page: int) -> None:
    s = get_session()
    try:
        per_page = int(setting(s, "per_page", "8"))
        offset = (page - 1) * per_page
        total = s.scalar(select(func.count()).select_from(Product).where(
            Product.category_id == cat_id, Product.is_active == 1
        )) or 0
        products = s.scalars(
            select(Product)
            .where(Product.category_id == cat_id, Product.is_active == 1)
            .order_by(Product.id.desc())
            .offset(offset)
            .limit(per_page)
        ).all()
        cat = s.get(Category, cat_id)
        rows = []
        for p in products:
            price = toman(p.price) if p.price > 0 else "رایگان"
            rows.append([InlineKeyboardButton(f"📦 {p.name} — {price}", callback_data=f"prod:{p.id}")])
        pages = max(1, (total + per_page - 1) // per_page)
        if pages > 1:
            nav = []
            for i in range(1, pages + 1):
                label = "●" + fa_num(i) if i == page else fa_num(i)
                nav.append(InlineKeyboardButton(label, callback_data=f"page:prod:{cat_id}:{i}"))
            rows.append(nav)
        rows.append([
            InlineKeyboardButton("⬅️ دسته‌بندی‌ها", callback_data="cats"),
            InlineKeyboardButton("🏠 منو", callback_data="home"),
        ])
        text = f"📁 <b>{cat.name if cat else 'دسته'}</b>\n\nتعداد: {fa_num(total)} محصول"
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
    finally:
        s.close()


async def show_product_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE, prod_id: int) -> None:
    s = get_session()
    try:
        p = s.get(Product, prod_id)
        if not p or not p.is_active:
            await update.callback_query.answer("محصول یافت نشد", show_alert=True)
            return
        price = toman(p.price) if p.price > 0 else "رایگان"
        text = f"📦 <b>{p.name}</b>\n\n💰 قیمت: {price}"
        if p.description:
            text += f"\n\n{p.description}"
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("💳 خرید", callback_data=f"buy:{p.id}")],
                [InlineKeyboardButton("⬅️ بازگشت", callback_data=f"cat:{p.category_id or 0}:1")],
            ]
        )
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    finally:
        s.close()


# -------------------------------------------------------------------- search
async def do_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    q = query.strip()
    s = get_session()
    try:
        if not q:
            await ctx.bot.send_message(chat_id=update.effective_chat.id, text="❗ عبارت خالی است.",
                                       reply_markup=main_menu_kb())
            return
        like = f"%{q}%"
        products = s.scalars(
            select(Product)
            .where(Product.is_active == 1, or_(
                Product.name.like(like), Product.tags.like(like), Product.description.like(like)
            ))
            .order_by(Product.id.desc())
            .limit(20)
        ).all()
        if not products:
            await ctx.bot.send_message(chat_id=update.effective_chat.id, text="🔍 نتیجه‌ای یافت نشد.",
                                       reply_markup=main_menu_kb())
            return
        rows = []
        for p in products:
            price = toman(p.price) if p.price > 0 else "رایگان"
            rows.append([InlineKeyboardButton(f"📦 {p.name} — {price}", callback_data=f"prod:{p.id}")])
        rows.append([InlineKeyboardButton("🏠 منو", callback_data="home")])
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🔍 نتایج جستجو برای: <b>{q}</b>",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="HTML",
        )
    finally:
        s.close()


# -------------------------------------------------------------------- profile
async def show_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        orders = s.scalar(select(func.count()).select_from(Order).where(Order.user_id == user.id)) or 0
        refs = s.scalar(select(func.count()).select_from(User).where(User.referred_by == user.id)) or 0
        text = (
            f"👤 <b>پروفایل شما</b>\n\n"
            f"🆔 شناسه: <code>{fa_num(user.telegram_id)}</code>\n"
            f"👋 نام: {user.first_name or '-'}\n"
            f"🧾 سفارش‌ها: {fa_num(orders)}\n"
            f"👥 زیرمجموعه‌ها: {fa_num(refs)}\n"
            f"💰 موجودی پاداش: {toman(user.referral_balance)}"
        )
        await ctx.bot.send_message(chat_id=update.effective_chat.id, text=text,
                                   reply_markup=main_menu_kb(), parse_mode="HTML")
    finally:
        s.close()


# -------------------------------------------------------------------- referral
async def show_referral(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        me = await ctx.bot.get_me()
        link = f"https://t.me/{me.username}?start={user.referral_code}"
        tmpl = setting(s, "referral_text", "دوستان خود را دعوت کنید:\n{referral_link}")
        text = tmpl.replace("{referral_link}", link)
        refs = s.scalar(select(func.count()).select_from(User).where(User.referred_by == user.id)) or 0
        text += f"\n\n👥 تعداد زیرمجموعه‌های شما: {fa_num(refs)}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 لینک دعوت", url=link)]])
        await ctx.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb)
    finally:
        s.close()


# -------------------------------------------------------------------- orders
async def show_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
    s = get_session()
    try:
        user = ensure_user(s, update.effective_user.id, update.effective_user.username,
                           update.effective_user.first_name)
        per_page = int(setting(s, "per_page", "8"))
        offset = (page - 1) * per_page
        total = s.scalar(select(func.count()).select_from(Order).where(Order.user_id == user.id)) or 0
        orders = s.execute(
            select(Order, Product.name)
            .outerjoin(Product, Product.id == Order.product_id)
            .where(Order.user_id == user.id)
            .order_by(Order.id.desc())
            .offset(offset)
            .limit(per_page)
        ).all()
        if not orders:
            await ctx.bot.send_message(chat_id=update.effective_chat.id, text="📋 شما هنوز سفارشی ثبت نکرده‌اید.",
                                       reply_markup=main_menu_kb())
            return
        text = "📋 <b>سفارش‌های شما</b>\n"
        badges = {"pending":"⏳ در انتظار","approved":"✅ تایید شد","rejected":"❌ رد شد","need_info":"❓ نیاز به توضیح"}
        for o, pname in orders:
            text += f"\n🧾 <code>{o.order_code}</code> | {pname or '(محصول حذف شده)'} | {badges.get(o.status, o.status)}\n"
        rows = [[InlineKeyboardButton("🏠 منو", callback_data="home")]]
        await ctx.bot.send_message(chat_id=update.effective_chat.id, text=text,
                                   reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
    finally:
        s.close()


# -------------------------------------------------------------------- state router
async def handle_state(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: User) -> None:
    from handlers.buy import handle_receipt_upload
    from handlers.admin import handle_admin_state

    s = get_session()
    text = (update.effective_message.text or "").strip()
    # Attach user to this session so subsequent writes commit cleanly.
    user = s.merge(user)
    state = user.state
    try:
        if text and text in ("⬅️ بازگشت به منو", "/cancel", "/admin"):
            user.state = None
            user.state_data = ""
            s.commit()
            if text == "/admin" and is_user_admin(user):
                from handlers.admin import admin_menu
                await admin_menu(update, ctx)
            else:
                from handlers.start import send_welcome
                await send_welcome(update, ctx)
            return

        if state == "search":
            await do_search(update, ctx, text)
            user.state = None
            s.commit()
            return

        if state and state.startswith("receipt:"):
            # Receipt upload can be text (explanation note) or media (photo/document).
            order_id = int(state.split(":", 1)[1])
            await handle_receipt_upload(update, ctx, user, order_id)
            return

        if state and state.startswith("admin_"):
            await handle_admin_state(update, ctx, user, text)
            return

        user.state = None
        s.commit()
        from handlers.start import send_welcome
        await send_welcome(update, ctx)
    finally:
        s.close()
