<?php
/**
 * Helper functions: settings, keyboards, formatting, security.
 */

function setting(string $key, ?string $default = null): ?string
{
    static $cache = null;
    if ($cache === null) {
        $cache = [];
        foreach (Database::fetchAll('SELECT key_name, value FROM settings') as $row) {
            $cache[$row['key_name']] = $row['value'];
        }
    }
    return $cache[$key] ?? $default;
}

function setSetting(string $key, string $value): void
{
    Database::query(
        'INSERT INTO settings (key_name, value) VALUES (:k, :v)
         ON DUPLICATE KEY UPDATE value = :v2',
        [':k' => $key, ':v' => $value, ':v2' => $value]
    );
}

function startSecureSession(): void
{
    if (session_status() !== PHP_SESSION_NONE) {
        return;
    }
    $isHttps = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (($_SERVER['SERVER_PORT'] ?? 0) == 443);
    session_set_cookie_params([
        'lifetime' => 0,
        'path'     => '/',
        'httponly' => true,
        'samesite' => 'Lax',
        'secure'   => $isHttps,
    ]);
    session_start();
}

function e(?string $s): string
{
    return htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8');
}

function faNum(int|string $n): string
{
    $fa = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];
    $en = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];
    return str_replace($fa, $en, (string) $n);
}

function toman(int $n): string
{
    return faNum(number_format($n)) . ' تومان';
}

function humanSize(int $bytes): string
{
    $unit = ['B', 'KB', 'MB', 'GB'];
    $i = 0;
    while ($bytes >= 1024 && $i < count($unit) - 1) {
        $bytes /= 1024;
        $i++;
    }
    return round($bytes, 2) . ' ' . $unit[$i];
}

function genOrderCode(): string
{
    return strtoupper(substr(bin2hex(random_bytes(4)), 0, 8));
}

function genReferralCode(): string
{
    return 'R' . substr(bin2hex(random_bytes(4)), 0, 7);
}

function generateCsrf(): string
{
    if (empty($_SESSION['csrf'])) {
        $_SESSION['csrf'] = bin2hex(random_bytes(16));
    }
    return $_SESSION['csrf'];
}

function checkCsrf(): bool
{
    $token = $_POST['csrf'] ?? ($_SERVER['HTTP_X_CSRF_TOKEN'] ?? '');
    return !empty($_SESSION['csrf']) && hash_equals($_SESSION['csrf'], (string) $token);
}

function csrfQuery(): string
{
    return 't=' . generateCsrf();
}

function checkGetCsrf(): bool
{
    $token = $_GET['t'] ?? '';
    return !empty($_SESSION['csrf']) && hash_equals($_SESSION['csrf'], (string) $token);
}

function clientIp(): string
{
    return $_SERVER['HTTP_X_FORWARDED_FOR'] ?? ($_SERVER['REMOTE_ADDR'] ?? '0.0.0.0');
}

function getUserByTelegramId(int $telegramId): ?array
{
    return Database::fetch('SELECT * FROM users WHERE telegram_id = :t', [':t' => $telegramId]) ?: null;
}

function isAdminTelegram(int $telegramId): bool
{
    $u = getUserByTelegramId($telegramId);
    if ($u && (int) $u['is_admin'] === 1) {
        return true;
    }
    // Also allow allow-listed IDs from ADMIN_IDS in config (so the first admin
    // can bootstrap without needing DB access).
    $ids = defined('ADMIN_IDS') ? ADMIN_IDS : '';
    if ($ids !== '') {
        foreach (preg_split('/[\s,]+/', $ids) as $id) {
            if ((int) trim($id) === $telegramId && $telegramId > 0) {
                return true;
            }
        }
    }
    return false;
}

/**
 * Reply keyboard helper.
 */
function rk(array $rows, bool $resize = true, bool $oneTime = false): array
{
    return [
        'keyboard'        => $rows,
        'resize_keyboard' => $resize,
        'one_time_keyboard' => $oneTime,
    ];
}

/** Main menu reply keyboard */
function mainMenu(): array
{
    return rk([
        [['text' => '🛍 فروشگاه'], ['text' => '🔍 جستجو']],
        [['text' => '📁 دسته‌بندی‌ها'], ['text' => '👤 پروفایل']],
        [['text' => '🎁 دعوت دوستان'], ['text' => '📋 سفارش‌های من']],
        [['text' => '📖 قوانین'], ['text' => '📞 پشتیبانی']],
    ]);
}

function backButton(): array
{
    return rk([[['text' => '⬅️ بازگشت به منو']]], true, true);
}

/** Check membership of user in all active required channels */
function checkRequiredChannels(Telegram $bot, int $telegramId): array
{
    $channels = Database::fetchAll('SELECT * FROM channels WHERE is_active = 1');
    $notJoined = [];
    foreach ($channels as $ch) {
        $chatId = $ch['channel_username'];
        if (strpos($chatId, '@') !== 0) {
            $chatId = '@' . $chatId;
        }
        $member = $bot->getChatMember($chatId, $telegramId);
        $status = $member['status'] ?? 'left';
        if (!in_array($status, ['member', 'administrator', 'creator'], true)) {
            $notJoined[] = $ch;
        }
    }
    return $notJoined;
}

function membershipKeyboard(array $notJoined): array
{
    $rows = [];
    foreach ($notJoined as $ch) {
        $link = $ch['invite_link'] ?: ('https://t.me/' . ltrim($ch['channel_username'], '@'));
        $rows[] = [['text' => '🔗 عضویت در ' . ($ch['title'] ?? $ch['channel_username']), 'url' => $link]];
    }
    $rows[] = [['text' => '✅ بررسی مجدد عضویت', 'callback_data' => 'check_join']];
    return ['inline_keyboard' => $rows];
}

function uploadFile(string $field, string $subDir, array $allowedExt = []): ?array
{
    if (empty($_FILES[$field]) || $_FILES[$field]['error'] !== UPLOAD_ERR_OK) {
        return null;
    }
    $file = $_FILES[$field];
    $ext = strtolower(pathinfo($file['name'], PATHINFO_EXTENSION));
    // Always block executable/server-side extensions regardless of allow-list
    $dangerous = ['php', 'phtml', 'phar', 'phps', 'pht', 'htaccess', 'htpasswd',
        'cgi', 'pl', 'py', 'sh', 'bash', 'asp', 'aspx', 'jsp', 'exe', 'bat', 'cmd', 'so', 'dll'];
    if (in_array($ext, $dangerous, true)) {
        return null;
    }
    if (!empty($allowedExt) && !in_array($ext, $allowedExt, true)) {
        return null;
    }
    $dir = UPLOAD_PATH . '/' . trim($subDir, '/');
    if (!is_dir($dir)) {
        @mkdir($dir, 0755, true);
    }
    $name = bin2hex(random_bytes(8)) . '.' . $ext;
    $dest = $dir . '/' . $name;
    if (!move_uploaded_file($file['tmp_name'], $dest)) {
        return null;
    }
    $rel = trim($subDir, '/') . '/' . $name;
    return [
        'path' => $rel,
        'abs'  => $dest,
        'size' => $file['size'],
        'ext'  => $ext,
        'name' => $file['name'],
    ];
}

function productCard(array $p): string
{
    $vip = $p['is_vip'] ? '⭐ VIP ' : '';
    $price = $p['price'] > 0 ? toman($p['price']) : 'رایگان';
    $size = $p['file_size'] ? humanSize((int) $p['file_size']) : '-';
    return "<b>{$vip}</b>📦 <b>" . e($p['name']) . "</b>\n\n💰 قیمت: <b>{$price}</b>\n📦 حجم: {$size}\n⬇️ دانلودها: " . faNum($p['download_count']);
}

/**
 * Deliver an order's file via Telegram, then (only on success) consume the
 * download quota and record stats. Used by bot self-download, admin approval,
 * and the web admin approve action so behaviour stays identical.
 */
function deliverOrderFile(Telegram $bot, array $order, array $product, int|string $chatId, string $ipSentinel): bool
{
    if (empty($product['file_path'])) {
        return false;
    }
    $abs = UPLOAD_PATH . '/' . $product['file_path'];
    if (!file_exists($abs)) {
        return false;
    }
    $caption = "📦 " . e($product['name']) . "\n🧾 کد: <code>" . e($order['order_code']) . "</code>";
    $res = $bot->sendDocument($chatId, '@' . $abs, $caption);
    if (empty($res['ok'])) {
        return false;
    }
    Database::query('UPDATE orders SET downloaded = downloaded + 1 WHERE id=:i', [':i' => $order['id']]);
    Database::query('UPDATE products SET download_count = download_count + 1 WHERE id=:i', [':i' => $product['id']]);
    Database::insert('downloads', [
        'order_id'   => $order['id'],
        'user_id'    => $order['user_id'],
        'product_id' => $product['id'],
        'ip'         => $ipSentinel,
    ]);
    return true;
}
