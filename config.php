<?php
/**
 * File Store Bot - Configuration
 * Secrets are loaded from includes/config.local.php (not committed).
 * If config.local.php is absent, edit the placeholders below.
 */

// Load local secrets if present (kept out of version control)
$local = __DIR__ . '/includes/config.local.php';
$hasLocal = is_file($local);
if ($hasLocal) { require $local; }

// ---------------- Database ----------------
define('DB_HOST', $hasLocal ? DB_HOST_LOCAL : 'localhost');
define('DB_NAME', $hasLocal ? DB_NAME_LOCAL : 'seller_db');
define('DB_USER', $hasLocal ? DB_USER_LOCAL : 'root');
define('DB_PASS', $hasLocal ? DB_PASS_LOCAL : '');
define('DB_CHARSET', 'utf8mb4');

// ---------------- Telegram ----------------
define('BOT_TOKEN', $hasLocal ? BOT_TOKEN_LOCAL : 'PUT-YOUR-BOT-TOKEN-HERE');

// Telegram IDs (comma-separated) who are allowed to use the admin panel
// inside the bot. These users will see the admin menu. Set at least your own
// Telegram numeric ID. Get it from @userinfobot.
define('ADMIN_IDS', $hasLocal ? ADMIN_IDS_LOCAL : '');

// ---------------- Paths ----------------
define('ROOT_PATH', __DIR__);
define('UPLOAD_PATH', ROOT_PATH . '/uploads');
// Secret token salt for download links (still used internally for receipts)
define('DOWNLOAD_TOKEN_SALT', $hasLocal ? DOWNLOAD_TOKEN_SALT_LOCAL : 'change-this-to-a-random-string');

// ---------------- Logging ----------------
// Set true to log errors to database/file.
define('ENABLE_LOGGING', true);

// ---------------- Long polling ----------------
// Seconds to wait on each getUpdates long-poll call.
define('POLL_TIMEOUT', 30);
// Maximum number of updates to fetch per getUpdates call.
define('POLL_LIMIT', 50);

// ---------------- Telegram access method ----------------
// (A) Recommended for blocked hosts: Cloudflare Worker / Deno Deploy reverse proxy.
//     Set TELEGRAM_API_BASE to the proxy URL. Leave empty to call
//     https://api.telegram.org directly.
define('TELEGRAM_API_BASE', $hasLocal && defined('TELEGRAM_API_BASE_LOCAL') ? TELEGRAM_API_BASE_LOCAL : '');

// (B) Fallback: HTTP/SOCKS5 proxy (needs a server outside Iran).
define('PROXY_HOST', $hasLocal && defined('PROXY_HOST_LOCAL') ? PROXY_HOST_LOCAL : '');
define('PROXY_PORT', $hasLocal && defined('PROXY_PORT_LOCAL') ? (int) PROXY_PORT_LOCAL : 0);
define('PROXY_TYPE', $hasLocal && defined('PROXY_TYPE_LOCAL') ? PROXY_TYPE_LOCAL : 'HTTP');
define('PROXY_USER', $hasLocal && defined('PROXY_USER_LOCAL') ? PROXY_USER_LOCAL : '');
define('PROXY_PASS', $hasLocal && defined('PROXY_PASS_LOCAL') ? PROXY_PASS_LOCAL : '');

date_default_timezone_set('Asia/Tehran');
