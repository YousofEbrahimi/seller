# فروشگاه فایل ربات تلگرام (PHP + MySQL)

ربات کامل فروش فایل‌های دیجیتال (PNG، Vector، PSD، Font، Mockup، Template، ZIP و ...) با پنل مدیریت داخل خود ربات، پرداخت دستی، عضویت اجباری در کانال و سیستم معرفی دوستان.

**بدون نیاز به:** دامنه، SSL، Nginx/Apache، وب‌پنل، یا دسترسی root.
با **Long Polling** اجرا می‌شود — فقط PHP + MySQL کافی است.

## امکانات

- 🤖 ربات تلگرام با Long Polling (بدون وبهوک، بدون دامنه، بدون SSL)
- 🎛 پنل مدیریت کامل داخل ربات (محصولات، دسته‌ها، سفارش‌ها، کاربران، کانال‌ها، کارت‌ها، تنظیمات، لاگ‌ها)
- 🗂 مدیریت محصولات: افزودن با ارسال فایل، ویرایش، فعال/غیرفعال، حذف
- 📁 مدیریت دسته‌بندی‌ها با آیکن
- 🔍 جستجوی محصولات (FULLTEXT + LIKE fallback)
- 🔒 عضویت اجباری در کانال‌ها (نامحدود) با بررسی خودکار
- 💳 پرداخت دستی با چند کارت بانکی و بررسی رسید
- ✅ تأیید/رد/درخواست توضیح برای سفارش‌ها از داخل تلگرام
- 📦 ارسال فایل محصول به کاربر پس از تأیید (دانلود نامحدود یا محدود)
- 👥 سیستم معرفی دوستان (Referral) با پاداش
- 📢 پیام همگانی (متن، عکس، فایل) به همه کاربران
- 📊 مدیریت کاربران: مسدود/رفع مسدود، ادمین‌کردن/حذف ادمین
- 🐛 لاگ خطاها داخل ربات
- 🛡 امنیت: Prepared Statements، خروجی امن، مسدودسازی دسترسی مستقیم به فایل‌ها

## ساختار پروژه

```
seller/
├── config.php                تنظیمات اصلی (رازها از config.local.php خوانده می‌شوند)
├── run.php                   حلقه long polling (نقطه ورود ربات)
├── run.sh                    مدیریت اجرای پس‌زمینه (start/stop/status/logs)
├── install.sh                اسکریپت نصب بدون root (ساخت دیتابیس + ایمپورت + config)
├── database.sql              اسکیمای کامل دیتابیس
├── includes/
│   ├── config.local.php      رازهای شما (توکن، دیتابیس) — در .gitignore
│   ├── db.php                کلاس دیتابیس (PDO)
│   ├── telegram.php          کلاس Telegram Bot API (cURL، getUpdates، downloadFile)
│   ├── helpers.php           توابع کمکی، کیبوردها، قالب‌بندی
│   └── bot.php               منطق اصلی ربات + پنل ادمین داخل ربات
├── uploads/
│   ├── files/                فایل‌های اصلی محصول (دسترسی مستقیم مسدود)
│   └── previews/             تصاویر پیش‌نمایش
└── README.md
```

## نصب روی سرور لینوکسی (VPS) — بدون root

### پیش‌نیازها

- سرور لینوکسی VPS (Ubuntu/Debian/CentOS)
- PHP 8.0+ با افزونه‌های: `cli`, `mysql` (pdo_mysql), `curl`, `mbstring`
- MySQL یا MariaDB (نسخه 5.7+/10.3+)
- **بدون نیاز به دسترسی root** (فقط یک کاربر عادی با دسترسی به MySQL)

اگر پیش‌نیازها نصب نیستند (از ادمین سرور بخواهید):

```bash
# Ubuntu/Debian:
sudo apt install php-cli php-mysql php-curl php-mbstring mariadb-server mariadb-clients

# RHEL/CentOS/Alma:
sudo dnf install php-cli php-mysqlnd php-curl php-mbstring mariadb-server mariadb
```

### مراحل نصب

۱. فایل‌های پروژه را روی سرور کپی کنید (مثلا `~/seller`):

```bash
# روی سرور:
mkdir -p ~/seller
# فایل‌ها را با scp/sftp کپی کنید به ~/seller
```

۲. اسکریپت نصب را اجرا کنید (بدون sudo):

```bash
cd ~/seller
bash install.sh
```

اسکریپت از شما می‌پرسد:
- نام دیتابیس (پیش‌فرض: `seller_db`)
- نام کاربر دیتابیس (پیش‌فرض: `seller_db_user`)
- یک رمز تصادفی دیتابیس تولید می‌شود
- توکن ربات (از @BotFather)
- شناسه عددی تلگرام شما (از @userinfobot)

سپس:
- دیتابیس و کاربر را می‌سازد (اگر اکانت MySQL دسترسی کافی داشته باشد)
- `database.sql` را ایمپورت می‌کند
- `includes/config.local.php` را می‌نویسد
- شما را به‌عنوان اولین ادمین در دیتابیس ثبت می‌کند

> اگر کاربر فعالی MySQL دسترسی ساخت دیتابیس ندارد، اسکریپت از شما یک اکانت درANGSDIran rented MySQL می‌خواهد و SQL لازم را نمایش می‌دهد تا دستی اجرا کنید.

۳. ربات را اجرا کنید:

```bash
bash run.sh start
```

۴. آماده است! در تلگرام به ربات `/start` و سپس `/admin` بفرستید.

### مدیریت اجرا

```bash
bash run.sh start     # اجرای پس‌زمینه (با nohup)
bash run.sh stop      # توقف
bash run.sh restart   # راه‌اندازی مجدد
bash run.sh status    # وضعیت
bash run.sh logs      # مشاهده لاگ (tail -f)
```

برای اجرای مستقیم (foreground برای دیباگ):

```bash
php run.php
```

## نصب دستی (بدون install.sh)

اگر می‌خواهید همه‌چیز را دستی انجام دهید:

۱. دیتابیس بسازید:

```sql
CREATE DATABASE seller_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'seller_db_user'@'localhost' IDENTIFIED BY 'YOUR_PASSWORD';
GRANT ALL PRIVILEGES ON seller_db.* TO 'seller_db_user'@'localhost';
FLUSH PRIVILEGES;
```

۲. اسکیمای دیتابیس را ایمپورت کنید:

```bash
mysql -u seller_db_user -p seller_db < database.sql
```

۳. فایل `includes/config.local.php` را بسازید:

```php
<?php
define('DB_HOST_LOCAL', 'localhost');
define('DB_NAME_LOCAL', 'seller_db');
define('DB_USER_LOCAL', 'seller_db_user');
define('DB_PASS_LOCAL', 'YOUR_PASSWORD');
define('BOT_TOKEN_LOCAL', '123456:ABC-YOUR-BOT-TOKEN');
define('ADMIN_IDS_LOCAL', '123456789');  // شناسه عددی تلگرام شما
define('DOWNLOAD_TOKEN_SALT_LOCAL', 'یک-رشته-تصادفی-طولانی');
define('TELEGRAM_API_BASE_LOCAL', '');
define('PROXY_HOST_LOCAL', '');
define('PROXY_PORT_LOCAL', 0);
define('PROXY_TYPE_LOCAL', 'HTTP');
define('PROXY_USER_LOCAL', '');
define('PROXY_PASS_LOCAL', '');
```

۴. ربات را اجرا کنید:

```bash
bash run.sh start
```

## ساخت ربات در BotFather

۱. در تلگرام به [@BotFather](https://t.me/BotFather) پیام دهید.
۲. `/newbot` بزنید و نام و یوزرنیم بدهید تا توکن را دریافت کنید.
۳. توکن را در `includes/config.local.php` قرار دهید (یا هنگام نصب وارد کنید).

## تنظیمات اولیه پس از نصب

همه تنظیمات از داخل ربات انجام می‌شوند. به ربات `/admin` بفرستید:

۱. **کانال اجباری:** ربات را در کانال عضو و ادمین کنید. سپس «📢 کانال‌های اجباری» → «➕ افزودن کانال».
۲. **کارت بانکی:** از «💳 کارت‌های بانکی» → «➕ افزودن کارت».
۳. **دسته‌بندی‌ها:** از «📁 دسته‌بندی‌ها» → «➕ افزودن دسته» (می‌توانید ایموجی آیکن بگذارید).
۴. **محصولات:** از «📦 محصولات» → «➕ افزودن محصول». فایل محصول را مستقیماً به ربات بفرستید، سپس نام، قیمت، دسته و... را وارد کنید.
۵. **متن‌ها:** از «⚙️ تنظیمات» متن خوش‌آمدگویی، پرداخت، قوانین، پشتیبانی و... را تنظیم کنید.
۶. **آیدی اعلان ادمین:** از «⚙️ تنظیمات» → «🔢 آیدی عددی مدیریت» — اعلان سفارش‌های جدید به این آیدی ارسال می‌شود.

## دسترسی به پنل ادمین

- کسانی که در `ADMIN_IDS_LOCAL` در `config.local.php` هستند.
- کسانی که در دیتابیس `is_admin = 1` هستند (می‌توان از داخل ربات به کاربران ادمین رو داد).
- در ربات `/admin` بفرستید یا اگر ادمین هستید دکمه «🎛 مدیریت» را بزنید.

## حل مشکل اتصال به تلگرام (سرورهای ایرانی)

اگر سرور VPS شما در ایران است و `api.telegram.org` مسدود شده، خطای `Connection timed out` دریافت می‌کنید.

### راه‌حل ۱: Deno Deploy Reverse Proxy (توصیه‌شده — رایگان)

دامنه `*.deno.dev` معمولاً در ایران مسدود نشده.

۱. به [dash.deno.com](https://dash.deno.com) بروید (با گیت‌هاب رایگان ثبت‌نام کنید).
۲. **New Project** → **Playground**.
۳. کد زیر را قرار دهید:

```javascript
export default async (req) => {
  const url = new URL(req.url);
  const target = "https://api.telegram.org" + url.pathname + url.search;
  const resp = await fetch(target, {
    method: req.method,
    headers: req.headers,
    body: req.method === "GET" || req.method === "HEAD" ? undefined : req.body,
  });
  return new Response(resp.body, { status: resp.status, headers: resp.headers });
};
```

۴. **Save & Deploy** را بزنید.
۵. URL کپی کنید (مثلاً `https://tg-proxy.deno.dev`).
۶. در `includes/config.local.php`:

```php
define('TELEGRAM_API_BASE_LOCAL', 'https://tg-proxy.deno.dev');
```

۷. ربات را ری‌استارت کنید: `bash run.sh restart`

### راه‌حل ۲: HTTP/SOCKS5 Proxy

اگر یک سرور پروکسی خارج از ایران دارید:

```php
define('PROXY_HOST_LOCAL', '1.2.3.4');
define('PROXY_PORT_LOCAL', 8080);
define('PROXY_TYPE_LOCAL', 'HTTP'); // یا 'SOCKS5'
define('PROXY_USER_LOCAL', 'username'); // اگر بدون احراز هویت است، خالی بگذارید
define('PROXY_PASS_LOCAL', 'password');
```

> **توجه:** پروکسی MTProto تلگرام فقط برای کلاینت تلگرام است و برای Bot API کار نمی‌کند.

## امنیت

- همه کوئری‌ها با **PDO Prepared Statements** اجرا می‌شوند → ضد SQL Injection.
- خروجی‌ها با `htmlspecialchars` → ضد XSS.
- پوشه `includes/` فقط کد PHP است و خارج از وب‌سرور serve نمی‌شود (در حالت long polling اصلاً وب‌سرور لازم نیست).
- فایل‌های اصلی محصولات در `uploads/files/` ذخیره می‌شوند و فقط از طریق ربات (به کاربران تأییدشده) ارسال می‌شوند.
- دکمه‌های inline با callback دارای اعتبارسنجی ادمین هستند.

## نکات مهم

- **PHP 8.0+** لازم است (استفاده از `match`, `str_starts_with`, `readonly` و...).
- افزودن محصول: فایل (Document) را مستقیماً به ربات بفرستید — ربات فایل را از تلگرام دانلود و در سرور ذخیره می‌کند.
- محدودیت حجم: فایل‌های بزرگ توسط Bot API ممکن است محدود شوند (حداکثر ۲۰ مگابایت برای `getFile`). برای فایل‌های بزرگ‌تر به IP API Server یا MTProto نیاز است.
- اگر خطایی پیش آمد، در بخش «🐛 لاگ خطاها» در پنل ادمین داخل ربات قابل مشاهده است.
- فایل `bot.log` و `error.log` در پوشه پروژه نوشته می‌شوند.

## اجرای مداوم (Persistence)

برای اینکه ربات پس از restart سرور خودکار اجرا شود، می‌توانید از `crontab` استفاده کنید:

```bash
crontab -e
# این خط را اضافه کنید (هر ۵ دقیقه چک می‌کند اگر در حال اجرا نیست، آن را اجرا کند):
*/5 * * * * cd ~/seller && bash run.sh start >> /dev/null 2>&1
```

یا از `systemctl --user` استفاده کنید (اگر `lingering` برای کاربر شما فعال باشد).
