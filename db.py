from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from config import cfg


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(100))
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    referral_code: Mapped[str] = mapped_column(String(20), unique=True)
    referred_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    referral_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    is_blocked: Mapped[int] = mapped_column(Integer, default=0)
    is_admin: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str | None] = mapped_column(String(100))
    state_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    icon: Mapped[str | None] = mapped_column(String(50))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[int] = mapped_column(Integer, default=1)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[int] = mapped_column(BigInteger, default=0)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    preview_image: Mapped[str | None] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(String(255))
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    tags: Mapped[str | None] = mapped_column(String(500))
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    download_limit: Mapped[int] = mapped_column(Integer, default=0)
    is_vip: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_username: Mapped[str] = mapped_column(String(100))
    channel_id: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(150))
    invite_link: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_number: Mapped[str] = mapped_column(String(32))
    holder_name: Mapped[str] = mapped_column(String(100))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_code: Mapped[str] = mapped_column(String(20), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    price: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    receipt_file_id: Mapped[str | None] = mapped_column(String(255))
    receipt_file_type: Mapped[str | None] = mapped_column(String(20))
    receipt_message: Mapped[str | None] = mapped_column(Text)
    admin_note: Mapped[str | None] = mapped_column(Text)
    downloaded: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Setting(Base):
    __tablename__ = "settings"

    key_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(20), default="error")
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bc_type: Mapped[str] = mapped_column("type", String(20), default="text")
    content: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[str | None] = mapped_column(String(255))
    caption: Mapped[str | None] = mapped_column(Text)
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


engine = create_engine(
    cfg.database_url,
    echo=False,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Session:
    return SessionLocal()


def init_db() -> None:
    """Create all tables. Safe to call on every startup."""
    Base.metadata.create_all(engine)


def seed_defaults(s: Session) -> None:
    defaults = {
        "welcome_text": "سلام به فروشگاه فایل ما خوش آمدید!\nبرای ادامه روی /start بزنید.",
        "rules_text": "قوانین فروشگاه:\n۱. پس از پرداخت رسید را ارسال کنید.\n۲. فایل‌ها فقط از طریق ربات قابل دانلود است.",
        "support_text": "برای پشتیبانی به آیدی زیر پیام دهید:\n@your_support",
        "payment_text": (
            "نام محصول: {product_name}\nقیمت: {price} تومان\n\n"
            "لطفاً مبلغ فوق را به کارت زیر واریز نمایید:\n\n{cards}\n\n"
            "پس از پرداخت، رسید واریز را ارسال کنید."
        ),
        "referral_reward": "0",
        "referral_text": "با دعوت دوستان خود از لینک زیر، پاداش دریافت کنید!\n\nلینک شما:\n{referral_link}",
        "store_name": cfg.store_name,
        "admin_notify_id": "0",
        "per_page": "8",
    }
    for key, value in defaults.items():
        existing = s.get(Setting, key)
        if existing is None:
            s.add(Setting(key_name=key, value=value))
    s.commit()


def setting(s: Session, key: str, default: str = "") -> str:
    row = s.get(Setting, key)
    return row.value if row and row.value is not None else default


def set_setting(s: Session, key: str, value: str) -> None:
    row = s.get(Setting, key)
    if row is None:
        row = Setting(key_name=key, value=value)
        s.add(row)
    else:
        row.value = value
    s.commit()


def log_error(s: Session, message: str, context: str = "") -> None:
    try:
        s.add(Log(message=message[:5000], context=context[:5000]))
        s.commit()
    except Exception:
        s.rollback()


def get_setting_value(s: Session, key: str, default: str = "") -> str:
    return setting(s, key, default)
