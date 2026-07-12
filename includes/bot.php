<?php
/**
 * Core bot logic. Processes a single Telegram update.
 */
class Bot
{
    private Telegram $bot;
    private array $update;
    private ?array $message;
    private ?array $callback;
    private ?array $user;
    private int $chatId;
    private int $telegramId;

    public function __construct(Telegram $bot, array $update)
    {
        $this->bot = $bot;
        $this->update = $update;
        $this->message = $update['message'] ?? $update['edited_message'] ?? null;
        $this->callback = $update['callback_query'] ?? null;
        $src = $this->callback ?? $this->message;
        $from = $src['from'] ?? null;
        $this->telegramId = $from['id'] ?? 0;
        $this->chatId = ($this->message['chat']['id'] ?? $this->callback['message']['chat']['id'] ?? 0);
    }

    public function run(): void
    {
        try {
            if (!$this->telegramId) {
                return;
            }
            $this->user = $this->ensureUser();
            if (!$this->user) {
                return;
            }
            if ((int) $this->user['is_blocked'] === 1) {
                $this->bot->sendMessage($this->chatId, '🚫 حساب شما مسدود شده است.');
                return;
            }
            if ($this->callback) {
                $this->handleCallback();
            } else {
                $this->handleMessage();
            }
        } catch (Throwable $e) {
            Database::logError('Bot error: ' . $e->getMessage(), $e->getTraceAsString());
        }
    }

    private function ensureUser(): ?array
    {
        $from = $this->callback['from'] ?? $this->message['from'];
        $user = getUserByTelegramId($this->telegramId);
        if ($user) {
            Database::update('users', [
                'username'      => $from['username'] ?? $user['username'],
                'first_name'    => $from['first_name'] ?? $user['first_name'],
                'last_name'     => $from['last_name'] ?? $user['last_name'],
                'last_activity' => date('Y-m-d H:i:s'),
            ], 'id = :id', [':id' => $user['id']]);
            $user['username'] = $from['username'] ?? $user['username'];
            $user['first_name'] = $from['first_name'] ?? $user['first_name'];
            return $user;
        }
        // new user - check referral from /start payload
        $referredBy = null;
        $start = $this->message['text'] ?? '';
        if (preg_match('#^/start\s+(\S+)#', $start, $m)) {
            $code = $m[1];
            $refUser = Database::fetch('SELECT id FROM users WHERE referral_code = :c', [':c' => $code]);
            if ($refUser) {
                $referredBy = (int) $refUser['id'];
            }
        }
        $id = Database::insert('users', [
            'telegram_id'    => $this->telegramId,
            'username'       => $from['username'] ?? null,
            'first_name'     => $from['first_name'] ?? null,
            'last_name'      => $from['last_name'] ?? null,
            'referral_code'  => genReferralCode(),
            'referred_by'    => $referredBy,
            'is_admin'       => 0,
        ]);
        if ($referredBy) {
            $reward = (int) setting('referral_reward', '0');
            if ($reward > 0) {
                Database::query('UPDATE users SET referral_balance = referral_balance + :r WHERE id = :i',
                    [':r' => $reward, ':i' => $referredBy]);
            }
        }
        return getUserByTelegramId($this->telegramId);
    }

    private function setState(?string $state, ?string $data = null): void
    {
        Database::update('users', ['state' => $state, 'state_data' => $data], 'id = :id', [':id' => $this->user['id']]);
        $this->user['state'] = $state;
        $this->user['state_data'] = $data;
    }

    private function clearState(): void
    {
        if (str_starts_with((string) ($this->user['state'] ?? ''), 'admin_')) {
            $this->clearWizard();
        }
        $this->setState(null, null);
    }

    /** Store wizard data in a JSON file keyed by chatId (avoids VARCHAR(255) limit). */
    private function wizardFile(): string
    {
        return sys_get_temp_dir() . '/seller_wizard_' . $this->chatId . '.json';
    }

    private function setWizard(array $data): void
    {
        @file_put_contents($this->wizardFile(), json_encode($data, JSON_UNESCAPED_UNICODE));
    }

    private function getWizard(): array
    {
        $f = $this->wizardFile();
        if (!is_file($f)) { return []; }
        $d = json_decode((string) @file_get_contents($f), true);
        return is_array($d) ? $d : [];
    }

    private function clearWizard(): void
    {
        @unlink($this->wizardFile());
    }

    // ---------------- Messages ----------------
    private function handleMessage(): void
    {
        $text = trim((string) ($this->message['text'] ?? ''));
        $state = $this->user['state'] ?? null;

        // start payload handled in ensureUser; handle display here
        if (str_starts_with($text, '/start')) {
            $this->clearState();
            $this->sendWelcome();
            return;
        }

        // Admin shortcut: /admin
        if ($text === '/admin' || $text === '🎛 مدیریت' || $text === '/panel') {
            if (isAdminTelegram($this->telegramId)) {
                $this->clearState();
                $this->adminMenu();
                return;
            }
        }

        // Allow in-progress flows (receipt upload, search, admin wizards) to continue
        if ($state) {
            $this->handleState($state, $text);
            return;
        }

        // Non-text content (photo/document) from a user not in a state: ignore,
        // unless it's an admin (caught below) — prevents flushing a menu.
        if ($text === '' && !isset($this->message['photo']) && !isset($this->message['document'])) {
            return;
        }

        // Require membership for menu navigation (admins exempt)
        $isAdm = isAdminTelegram($this->telegramId);
        if (!$isAdm && $this->telegramId !== (int) setting('admin_notify_id', '0')) {
            $notJoined = checkRequiredChannels($this->bot, $this->telegramId);
            if (!empty($notJoined)) {
                $this->bot->sendMessage($this->chatId, '🔒 برای دسترسی به امکانات ربات ابتدا در کانال‌های زیر عضو شوید:', membershipKeyboard($notJoined));
                return;
            }
        }

        // Admin commands
        if ($isAdm && str_starts_with($text, '/')) {
            $this->handleAdminCommand($text);
            return;
        }

        switch (true) {
            case $text === '🛍 فروشگاه':
            case $text === '/shop':
                $this->showCategories();
                break;
            case $text === '🔍 جستجو':
                $this->setState('search');
                $this->bot->sendMessage($this->chatId, '🔍 عبارت مورد نظر را برای جستجو ارسال کنید (نام، برچسب یا توضیحات):', backButton());
                break;
            case $text === '📁 دسته‌بندی‌ها':
                $this->showCategories();
                break;
            case $text === '👤 پروفایل':
                $this->showProfile();
                break;
            case $text === '🎁 دعوت دوستان':
                $this->showReferral();
                break;
            case $text === '📋 سفارش‌های من':
                $this->showOrders();
                break;
            case $text === '📖 قوانین':
                $this->bot->sendMessage($this->chatId, "📖 <b>قوانین</b>\n\n" . e(setting('rules_text', '')), mainMenu());
                break;
            case $text === '📞 پشتیبانی':
                $this->bot->sendMessage($this->chatId, "📞 <b>پشتیبانی</b>\n\n" . e(setting('support_text', '')), mainMenu());
                break;
            case $text === '⬅️ بازگشت به منو':
                $this->clearState();
                $this->sendWelcome();
                break;
            default:
                $this->sendWelcome();
        }
    }

    private function handleState(string $state, string $text): void
    {
        $data = $this->message;
        if ($text === '⬅️ بازگشت به منو' || $text === '/cancel' || $text === '/admin') {
            $this->clearState();
            if ($text !== '⬅️ بازگشت به منو' && isAdminTelegram($this->telegramId) && ($text === '/admin' || $text === '/panel')) {
                $this->adminMenu();
            } else {
                $this->sendWelcome();
            }
            return;
        }
        if ($state === 'search') {
            $this->doSearch($text);
            $this->clearState();
            return;
        }
        if (str_starts_with($state, 'receipt:')) {
            $orderId = (int) substr($state, 8);
            $this->handleReceiptUpload($orderId, $data);
            return;
        }
        // Admin wizard states
        if (str_starts_with($state, 'admin_')) {
            $this->handleAdminState($state, $text, $data);
            return;
        }
        $this->clearState();
        $this->sendWelcome();
    }

    private function sendWelcome(): void
    {
        $welcome = setting('welcome_text', 'سلام! خوش آمدید.');
        $notJoined = checkRequiredChannels($this->bot, $this->telegramId);
        if (!empty($notJoined)) {
            $this->bot->sendMessage(
                $this->chatId,
                '🔒 برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید:',
                membershipKeyboard($notJoined)
            );
            return;
        }
        $kb = mainMenu();
        if (isAdminTelegram($this->telegramId)) {
            // Admins get an extra reply-keyboard row to reach the panel.
            $kb['keyboard'][] = [['text' => '🎛 مدیریت']];
        }
        $this->bot->sendMessage($this->chatId, '👋 ' . $welcome, $kb);
    }

    // ---------------- Callbacks ----------------
    private function handleCallback(): void
    {
        $cb = $this->callback;
        $this->bot->answerCallbackQuery($cb['id']);
        $data = $cb['data'] ?? '';
        $msgId = $cb['message']['message_id'] ?? 0;
        $parts = explode(':', $data);

        if ($data === 'check_join') {
            $notJoined = checkRequiredChannels($this->bot, $this->telegramId);
            if (!empty($notJoined)) {
                $this->bot->editMessageText($this->chatId, $msgId,
                    '🔒 هنوز در همه کانال‌ها عضو نشده‌اید. لطفاً عضو شوید و دوباره بررسی کنید.',
                    membershipKeyboard($notJoined));
            } else {
                $this->bot->deleteMessage($this->chatId, $msgId);
                $this->sendWelcome();
            }
            return;
        }

        // Admin panel callbacks are handled before the channel-membership gate.
        if (str_starts_with($data, 'adm_')) {
            if (!isAdminTelegram($this->telegramId)) {
                $this->bot->answerCallbackQuery($cb['id'], 'دسترسی ندارید', true);
                return;
            }
            // Wizard-continuation callbacks must NOT clear state (they read/write the wizard file).
            $wizardCbs = ['adm_pcatset', 'adm_pvipset', 'adm_psave'];
            if (!in_array($parts[0] ?? '', $wizardCbs, true)) {
                $this->clearState();
            }
            $this->handleAdminCallback($data, $msgId);
            return;
        }

        // Require membership for everything else (admins are exempt)
        $adminNotifyId = (int) setting('admin_notify_id', '0');
        if (!isAdminTelegram($this->telegramId) && $this->telegramId !== $adminNotifyId) {
            $notJoined = checkRequiredChannels($this->bot, $this->telegramId);
            if (!empty($notJoined)) {
                $this->bot->sendMessage($this->chatId, '🔒 ابتدا در کانال‌های اجباری عضو شوید.', membershipKeyboard($notJoined));
                return;
            }
        }

        switch ($parts[0] ?? '') {
            case 'cat':
                $this->showProducts((int) $parts[1], (int) ($parts[2] ?? 1), $msgId);
                break;
            case 'prod':
                $this->showProduct((int) $parts[1], $msgId);
                break;
            case 'buy':
                $this->startBuy((int) $parts[1], $msgId);
                break;
            case 'cats':
                $this->showCategories($msgId);
                break;
            case 'home':
                $this->bot->deleteMessage($this->chatId, $msgId);
                $this->sendWelcome();
                break;
            case 'myorders':
                $this->showOrders(1, $msgId);
                break;
            case 'dl':
                $this->downloadOrder((int) $parts[1], $msgId);
                break;
            case 'page':
                // generic pagination: page:<type>:<id>:<p>
                $type = $parts[1] ?? '';
                $id = (int) ($parts[2] ?? 0);
                $p = (int) ($parts[3] ?? 1);
                if ($type === 'prod') {
                    $this->showProducts($id, $p, $msgId);
                } elseif ($type === 'order') {
                    $this->showOrders($p, $msgId);
                }
                break;
            case 'cancelbuy':
                $this->clearState();
                $this->bot->deleteMessage($this->chatId, $msgId);
                $this->sendWelcome();
                break;
            case 'searchtag':
                $this->doSearch(rawurldecode($parts[1] ?? ''));
                break;
            case 'admin_approve':
            case 'admin_reject':
            case 'admin_info':
                $this->adminOrderAction($parts[0], (int) $parts[1]);
                break;
            default:
                $this->sendWelcome();
        }
    }

    // ---------------- Shop / Categories ----------------
    private function showCategories(?int $msgId = null): void
    {
        $cats = Database::fetchAll('SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order, id');
        $rows = [];
        $cols = [];
        foreach ($cats as $c) {
            $cols[] = ['text' => ($c['icon'] ? $c['icon'] . ' ' : '') . $c['name'], 'callback_data' => 'cat:' . $c['id'] . ':1'];
            if (count($cols) === 2) {
                $rows[] = $cols;
                $cols = [];
            }
        }
        if ($cols) {
            $rows[] = $cols;
        }
        $rows[] = [['text' => '🏠 منو', 'callback_data' => 'home']];
        $kb = ['inline_keyboard' => $rows];
        $text = "📁 <b>دسته‌بندی‌ها</b>\n\nیک دسته را انتخاب کنید:";
        if ($msgId) {
            $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
        } else {
            $this->bot->sendMessage($this->chatId, $text, $kb);
        }
    }

    private function showProducts(int $catId, int $page, int $msgId): void
    {
        $perPage = (int) setting('per_page', '8');
        $offset = ($page - 1) * $perPage;
        $total = (int) Database::fetchColumn(
            'SELECT COUNT(*) FROM products WHERE category_id=:c AND is_active=1', [':c' => $catId]);
        $products = Database::fetchAll(
            'SELECT * FROM products WHERE category_id=:c AND is_active=1 ORDER BY id DESC LIMIT :o,:l',
            [':c' => $catId, ':o' => $offset, ':l' => $perPage]);
        $cat = Database::fetch('SELECT name FROM categories WHERE id=:c', [':c' => $catId]);
        $rows = [];
        foreach ($products as $p) {
            $rows[] = [['text' => '📦 ' . $p['name'] . ' — ' . ($p['price'] > 0 ? faNum(number_format($p['price'])) . 'ت' : 'رایگان'),
                'callback_data' => 'prod:' . $p['id']]];
        }
        // pagination
        $pages = (int) ceil($total / $perPage);
        if ($pages > 1) {
            $nav = [];
            for ($i = 1; $i <= $pages; $i++) {
                $nav[] = ['text' => ($i === $page) ? '●' . faNum($i) : faNum($i), 'callback_data' => 'page:prod:' . $catId . ':' . $i];
            }
            $rows[] = $nav;
        }
        $rows[] = [['text' => '⬅️ دسته‌بندی‌ها', 'callback_data' => 'cats'], ['text' => '🏠 منو', 'callback_data' => 'home']];
        $kb = ['inline_keyboard' => $rows];
        $text = "📁 <b>" . e($cat['name'] ?? 'دسته') . "</b>\n\nتعداد: " . faNum($total) . " محصول";
        $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
    }

    private function showProduct(int $prodId, int $msgId): void
    {
        $p = Database::fetch('SELECT * FROM products WHERE id=:i AND is_active=1', [':i' => $prodId]);
        if (!$p) {
            $this->bot->answerCallbackQuery($this->callback['id'], 'محصول یافت نشد', true);
            return;
        }
        $text = productCard($p);
        if ($p['description']) {
            $text .= "\n\n" . e($p['description']);
        }
        $kb = ['inline_keyboard' => [
            [['text' => '💳 خرید', 'callback_data' => 'buy:' . $p['id']]],
            [['text' => '⬅️ بازگشت', 'callback_data' => 'cat:' . $p['category_id'] . ':1']],
        ]];
        if ($p['preview_image']) {
            $ph = UPLOAD_PATH . '/' . $p['preview_image'];
            if (is_file($ph)) {
                $this->bot->sendPhoto($this->chatId, '@' . $ph, $text, $kb);
                $this->bot->deleteMessage($this->chatId, $msgId);
            } else {
                $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
            }
        } else {
            $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
        }
    }

    // ---------------- Buying ----------------
    private function startBuy(int $prodId, int $msgId): void
    {
        $p = Database::fetch('SELECT * FROM products WHERE id=:i AND is_active=1', [':i' => $prodId]);
        if (!$p) {
            return;
        }
        // Reuse an existing pending/need_info order for the same user+product instead of creating a duplicate
        $existing = Database::fetch(
            'SELECT * FROM orders WHERE user_id=:u AND product_id=:p AND status IN (:a,:b) ORDER BY id DESC LIMIT 1',
            [':u' => $this->user['id'], ':p' => $prodId, ':a' => 'pending', ':b' => 'need_info']);
        if ($existing) {
            $orderId = (int) $existing['id'];
            $orderCode = $existing['order_code'];
        } else {
            $orderCode = genOrderCode();
            $orderId = Database::insert('orders', [
                'order_code' => $orderCode,
                'user_id'    => $this->user['id'],
                'product_id' => $prodId,
                'price'      => $p['price'],
                'status'     => 'pending',
            ]);
        }
        $text = setting('payment_text', 'مبلغ را واریز کنید.');
        $cards = Database::fetchAll('SELECT * FROM cards WHERE is_active=1 ORDER BY sort_order, id');
        $cardsText = '';
        foreach ($cards as $c) {
            $cardsText .= "\n💳 " . e($c['card_number']) . "\n👤 " . e($c['holder_name']) . ($c['bank_name'] ? ' (' . e($c['bank_name']) . ')' : '') . "\n";
        }
        $text = strtr($text, [
            '{product_name}' => e($p['name']),
            '{price}'        => faNum(number_format($p['price'])),
            '{card_number}'  => $cardsText ?: '—',
            '{holder_name}'  => '',
            '{order_code}'   => $orderCode,
        ]);
        $kb = ['inline_keyboard' => [
            [['text' => '❌ انصراف', 'callback_data' => 'cancelbuy']],
        ]];
        $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
        $this->setState('receipt:' . $orderId);
        $this->bot->sendMessage($this->chatId, '📩 لطفاً رسید پرداخت را (عکس یا فایل) ارسال کنید:', backButton());
    }

    private function handleReceiptUpload(int $orderId, array $message): void
    {
        $order = Database::fetch('SELECT * FROM orders WHERE id=:i AND user_id=:u AND status IN (:p,:n)',
            [':i' => $orderId, ':u' => $this->user['id'], ':p' => 'pending', ':n' => 'need_info']);
        if (!$order) {
            $this->clearState();
            $this->sendWelcome();
            return;
        }
        $fileId = null;
        $fileType = null;
        $caption = $message['caption'] ?? '';
        if (isset($message['photo'])) {
            $photo = end($message['photo']);
            $fileId = $photo['file_id'];
            $fileType = 'photo';
        } elseif (isset($message['document'])) {
            $fileId = $message['document']['file_id'];
            $fileType = 'document';
        } elseif (isset($message['text']) && trim($message['text']) !== '') {
            $fileType = 'text';
            $caption = $message['text'];
        }
        if (!$fileId && $fileType !== 'text') {
            $this->bot->sendMessage($this->chatId, '❗ لطفاً یک عکس یا فایل ارسال کنید.');
            return;
        }
        Database::update('orders', [
            'receipt_file_id'   => $fileId,
            'receipt_file_type' => $fileType,
            'receipt_message'   => $caption,
            'status'            => 'pending',
        ], 'id = :id', [':id' => $orderId]);
        $this->clearState();

        $product = Database::fetch('SELECT name FROM products WHERE id=:i', [':i' => $order['product_id']]);
        $adminText = "🔔 <b>سفارش جدید در انتظار تایید</b>\n\n" .
            "🧾 کد: <code>" . e($order['order_code']) . "</code>\n" .
            "📦 محصول: " . e($product['name']) . "\n" .
            "💰 مبلغ: " . toman($order['price']) . "\n" .
            "👤 کاربر: " . e($this->user['first_name']) . " (" . ($this->user['username'] ? '@' . $this->user['username'] : faNum($this->telegramId)) . ")\n" .
            "📝 توضیح: " . e($caption);

        $kb = ['inline_keyboard' => [
            [['text' => '✅ تایید و ارسال فایل', 'callback_data' => 'admin_approve:' . $orderId]],
            [['text' => '❌ رد', 'callback_data' => 'admin_reject:' . $orderId], ['text' => '❓ درخواست توضیح', 'callback_data' => 'admin_info:' . $orderId]],
        ]];
        $this->notifyAdmins($adminText, $kb, $fileId, $fileType);

        $this->bot->sendMessage($this->chatId,
            "✅ رسید شما دریافت شد و در انتظار تایید مدیر است.\nکد پیگیری: <code>" . e($order['order_code']) . "</code>",
            mainMenu());
    }

    private function notifyAdmins(string $text, ?array $kb = null, ?string $fileId = null, ?string $fileType = null): void
    {
        $targets = [];
        $admins = Database::fetchAll('SELECT telegram_id FROM users WHERE is_admin=1');
        foreach ($admins as $a) {
            $targets[(int) $a['telegram_id']] = true;
        }
        $adminNotifyId = (int) setting('admin_notify_id', '0');
        if ($adminNotifyId > 0) {
            $targets[$adminNotifyId] = true;
        }
        foreach (array_keys($targets) as $tid) {
            if ($fileId && $fileType === 'photo') {
                $this->bot->sendPhoto($tid, $fileId, $text, $kb);
            } elseif ($fileId && $fileType === 'document') {
                $this->bot->sendDocument($tid, $fileId, $text, $kb);
            } else {
                $this->bot->sendMessage($tid, $text, $kb);
            }
        }
    }

    // ---------------- Search ----------------
    private function doSearch(string $query): void
    {
        $q = trim($query);
        if ($q === '') {
            $this->bot->sendMessage($this->chatId, '❗ عبارت خالی است.', mainMenu());
            return;
        }
        // Use the FULLTEXT index (name, description, tags); fall back to LIKE for short tokens
        $products = Database::fetchAll(
            'SELECT * FROM products WHERE is_active=1 AND MATCH(name, description, tags) AGAINST (:q IN BOOLEAN MODE) ORDER BY id DESC LIMIT 20',
            [':q' => $q]);
        if (!$products) {
            $like = '%' . $q . '%';
            $products = Database::fetchAll(
                'SELECT * FROM products WHERE is_active=1 AND (name LIKE :q OR tags LIKE :q OR description LIKE :q) ORDER BY id DESC LIMIT 20',
                [':q' => $like]);
        }
        if (!$products) {
            $this->bot->sendMessage($this->chatId, '🔍 نتیجه‌ای یافت نشد.', mainMenu());
            return;
        }
        $rows = [];
        foreach ($products as $p) {
            $rows[] = [['text' => '📦 ' . $p['name'] . ' — ' . ($p['price'] > 0 ? faNum(number_format($p['price'])) . 'ت' : 'رایگان'),
                'callback_data' => 'prod:' . $p['id']]];
        }
        $rows[] = [['text' => '🏠 منو', 'callback_data' => 'home']];
        $this->bot->sendMessage($this->chatId, '🔍 نتایج جستجو برای: <b>' . e($q) . '</b>', ['inline_keyboard' => $rows]);
    }

    // ---------------- Profile ----------------
    private function showProfile(): void
    {
        $u = $this->user;
        $count = (int) Database::fetchColumn('SELECT COUNT(*) FROM users WHERE referred_by=:i', [':i' => $u['id']]);
        $orders = (int) Database::fetchColumn('SELECT COUNT(*) FROM orders WHERE user_id=:i', [':i' => $u['id']]);
        $text = "👤 <b>پروفایل شما</b>\n\n" .
            "🆔 شناسه: <code>" . faNum($u['telegram_id']) . "</code>\n" .
            "👋 نام: " . e($u['first_name'] ?? '-') . "\n" .
            "🧾 تعداد سفارش: " . faNum($orders) . "\n" .
            "👥 زیرمجموعه‌ها: " . faNum($count) . "\n" .
            "💰 موجودی پاداش: " . toman($u['referral_balance']);
        $this->bot->sendMessage($this->chatId, $text, mainMenu());
    }

    private function showReferral(): void
    {
        $botInfo = $this->bot->request('getMe');
        $username = $botInfo['result']['username'] ?? 'bot';
        $link = 'https://t.me/' . $username . '?start=' . $this->user['referral_code'];
        $text = setting('referral_text', 'دوستان خود را دعوت کنید:');
        $text = strtr($text, ['{referral_link}' => $link]);
        $count = (int) Database::fetchColumn('SELECT COUNT(*) FROM users WHERE referred_by=:i', [':i' => $this->user['id']]);
        $text .= "\n\n👥 تعداد زیرمجموعه‌های شما: " . faNum($count);
        $kb = ['inline_keyboard' => [[['text' => '🔗 لینک دعوت', 'url' => $link]]]];
        $this->bot->sendMessage($this->chatId, $text, $kb, 'HTML', false);
    }

    // ---------------- Orders ----------------
    private function showOrders(int $page = 1, ?int $msgId = null): void
    {
        $perPage = (int) setting('per_page', '8');
        $offset = ($page - 1) * $perPage;
        $total = (int) Database::fetchColumn('SELECT COUNT(*) FROM orders WHERE user_id=:u', [':u' => $this->user['id']]);
        $orders = Database::fetchAll(
            'SELECT o.*, p.name AS pname FROM orders o JOIN products p ON p.id=o.product_id
             WHERE o.user_id=:u ORDER BY o.id DESC LIMIT :o,:l',
            [':u' => $this->user['id'], ':o' => $offset, ':l' => $perPage]);
        if (!$orders) {
            $text = "📋 شما هنوز سفارشی ثبت نکرده‌اید.";
        } else {
            $text = "📋 <b>سفارش‌های شما</b>\n";
            foreach ($orders as $o) {
                $status = ['pending' => '⏳ در انتظار تایید', 'approved' => '✅ تایید شد', 'rejected' => '❌ رد شد', 'need_info' => '❓ نیاز به توضیح'][$o['status']];
                $text .= "\n🧾 <code>" . e($o['order_code']) . "</code> | " . e($o['pname']) . " | " . $status . "\n";
            }
        }
        $rows = [];
        $pages = (int) ceil($total / $perPage);
        if ($pages > 1) {
            $nav = [];
            for ($i = 1; $i <= $pages; $i++) {
                $nav[] = ['text' => $i === $page ? '●' . faNum($i) : faNum($i), 'callback_data' => 'page:order:0:' . $i];
            }
            $rows[] = $nav;
        }
        $rows[] = [['text' => '🏠 منو', 'callback_data' => 'home']];
        $kb = ['inline_keyboard' => $rows];
        if ($msgId) {
            $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
        } else {
            $this->bot->sendMessage($this->chatId, $text, $kb);
        }
    }

    private function downloadOrder(int $orderId, int $msgId): void
    {
        $order = Database::fetch('SELECT * FROM orders WHERE id=:i AND user_id=:u AND status=:s',
            [':i' => $orderId, ':u' => $this->user['id'], ':s' => 'approved']);
        if (!$order) {
            $this->bot->answerCallbackQuery($this->callback['id'], 'سفارش معتبر نیست', true);
            return;
        }
        $product = Database::fetch('SELECT * FROM products WHERE id=:i', [':i' => $order['product_id']]);
        if (!$product || !$product['file_path']) {
            $this->bot->answerCallbackQuery($this->callback['id'], 'فایل موجود نیست', true);
            return;
        }
        $limit = (int) $order['downloaded'];
        $max = (int) $product['download_limit'];
        if ($max > 0 && $limit >= $max) {
            $this->bot->answerCallbackQuery($this->callback['id'], 'محدودیت دانلود به پایان رسیده است', true);
            return;
        }
        $ok = deliverOrderFile($this->bot, $order, $product, $this->chatId, clientIp());
        if (!$ok) {
            $this->bot->answerCallbackQuery($this->callback['id'], 'ارسال فایل ناموفق بود، دوباره تلاش کنید', true);
            return;
        }
        $this->bot->answerCallbackQuery($this->callback['id'], '✅ فایل ارسال شد');
    }

    // ---------------- Admin inline actions ----------------
    private function adminOrderAction(string $action, int $orderId): void
    {
        $adminNotifyId = (int) setting('admin_notify_id', '0');
        if ((int) $this->user['is_admin'] !== 1 && $this->telegramId !== $adminNotifyId) {
            $this->bot->answerCallbackQuery($this->callback['id'], 'دسترسی ندارید', true);
            return;
        }
        $order = Database::fetch('SELECT o.*, p.name AS pname, p.file_path, p.download_limit FROM orders o JOIN products p ON p.id=o.product_id WHERE o.id=:i', [':i' => $orderId]);
        if (!$order) {
            $this->bot->answerCallbackQuery($this->callback['id'], 'سفارش یافت نشد', true);
            return;
        }
        $buyer = Database::fetch('SELECT * FROM users WHERE id=:i', [':i' => $order['user_id']]);
        if (!$buyer) {
            $this->bot->answerCallbackQuery($this->callback['id'], 'کاربر یافت نشد', true);
            return;
        }

        // Only act on orders still awaiting a decision
        if (!in_array($order['status'], ['pending', 'need_info'], true)) {
            $this->bot->answerCallbackQuery($this->callback['id'], 'این سفارش قبلاً بررسی شده است', true);
            $this->bot->editMessageReplyMarkup($this->chatId, $this->callback['message']['message_id'], ['inline_keyboard' => []]);
            return;
        }
        // Remove the action buttons so the order can't be acted on twice
        $this->bot->editMessageReplyMarkup($this->chatId, $this->callback['message']['message_id'], ['inline_keyboard' => []]);

        if ($action === 'admin_approve') {
            $product = Database::fetch('SELECT * FROM products WHERE id=:i', [':i' => $order['product_id']]);
            Database::update('orders', ['status' => 'approved', 'admin_note' => 'تایید شد'], 'id=:i', [':i' => $orderId]);
            $this->bot->answerCallbackQuery($this->callback['id'], 'سفارش تایید شد ✅');
            $this->bot->sendMessage($this->chatId, "✅ سفارش <code>" . e($order['order_code']) . "</code> تایید شد و فایل برای کاربر ارسال شد.");
            $this->bot->sendMessage($buyer['telegram_id'],
                "✅ سفارش شما تایید شد!\n📦 محصول: " . e($order['pname']) . "\n\nدر ادامه فایل محصول ارسال می‌شود:",
                mainMenu());
            $delivered = $product ? deliverOrderFile($this->bot, $order, $product, $buyer['telegram_id'], 'admin-send') : false;
            if (!$delivered) {
                $this->bot->sendMessage($buyer['telegram_id'], '⚠️ فایل محصول یافت نشد. با پشتیبانی تماس بگیرید.');
            }
            return;
        }

        if ($action === 'admin_reject') {
            Database::update('orders', ['status' => 'rejected', 'admin_note' => 'رد شد'], 'id=:i', [':i' => $orderId]);
            $this->bot->answerCallbackQuery($this->callback['id'], 'سفارش رد شد ❌');
            $this->bot->sendMessage($this->chatId, "❌ سفارش <code>" . e($order['order_code']) . "</code> رد شد.");
            $this->bot->sendMessage($buyer['telegram_id'],
                "❌ سفارش شما با کد <code>" . e($order['order_code']) . "</code> متأسفانه رد شد.\nبرای پیگیری با پشتیبانی در تماس باشید.",
                mainMenu());
            return;
        }

        if ($action === 'admin_info') {
            Database::update('orders', ['status' => 'need_info', 'admin_note' => 'درخواست توضیح بیشتر'], 'id=:i', [':i' => $orderId]);
            // Put the buyer back into the receipt-upload flow so they can re-send
            Database::update('users', ['state' => 'receipt:' . $orderId, 'state_data' => null], 'id=:i', [':i' => $buyer['id']]);
            $this->bot->answerCallbackQuery($this->callback['id'], 'درخواست توضیح ارسال شد');
            $this->bot->sendMessage($this->chatId, "❓ از کاربر توضیح بیشتر خواسته شد.");
            $this->bot->sendMessage($buyer['telegram_id'],
                "❓ سفارش شما با کد <code>" . e($order['order_code']) . "</code> نیاز به توضیح بیشتر دارد.\nلطفاً جزئیات بیشتری درباره رسید ارسال کنید.",
                backButton());
        }
    }

    private function handleAdminCommand(string $text): void
    {
        if ($text === '/admin' || $text === '/panel' || $text === '/help') {
            $this->adminMenu();
            return;
        }
        $this->adminMenu();
    }

    // =====================================================
    //  IN-BOT ADMIN PANEL
    //  All admin functions live in the bot (no web panel).
    //  Access via /admin or the "🎛 مدیریت" button (admins only).
    // =====================================================

    private function adminMenu(?int $msgId = null): void
    {
        $text = "🎛 <b>پنل مدیریت</b>\n\nیک بخش را انتخاب کنید:";
        $kb = ['inline_keyboard' => [
            [['text' => '📦 محصولات', 'callback_data' => 'adm_prodlist']],
            [['text' => '📁 دسته‌بندی‌ها', 'callback_data' => 'adm_catlist']],
            [['text' => '📋 سفارش‌ها', 'callback_data' => 'adm_orderlist:1']],
            [['text' => '👥 کاربران', 'callback_data' => 'adm_userlist:1']],
            [['text' => '📢 کانال‌های اجباری', 'callback_data' => 'adm_channellist']],
            [['text' => '💳 کارت‌های بانکی', 'callback_data' => 'adm_cardlist']],
            [['text' => '📣 پیام همگانی', 'callback_data' => 'adm_broadcast_menu']],
            [['text' => '⚙️ تنظیمات', 'callback_data' => 'adm_settings']],
            [['text' => '🐛 لاگ خطاها', 'callback_data' => 'adm_logs:1']],
            [['text' => '🏠 منوی ربات', 'callback_data' => 'home']],
        ]];
        if ($msgId) {
            $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
        } else {
            $this->bot->sendMessage($this->chatId, $text, $kb);
        }
    }

    /** Router for all adm_* callbacks. */
    private function handleAdminCallback(string $data, int $msgId): void
    {
        $parts = explode(':', $data);
        $cmd = $parts[0] ?? '';
        switch ($cmd) {
            case 'adm_menu':       $this->adminMenu($msgId); break;
            case 'adm_prodlist':   $this->adminProductList($msgId, (int) ($parts[1] ?? 1)); break;
            case 'adm_prodadd':    $this->adminProductAddStep($msgId); break;
            case 'adm_pcatset':     $this->adminProductSetCategory((int) ($parts[1] ?? 0), $msgId); break;
            case 'adm_pvipset':     $this->adminProductSetVip((int) ($parts[1] ?? 0), $msgId); break;
            case 'adm_psave':       $this->adminProductSave((int) ($parts[1] ?? 1), $msgId); break;
            case 'adm_pcancel':     $this->adminProductCancel($msgId); break;
            case 'adm_proddel':    $this->adminProductDelete((int) $parts[1], $msgId); break;
            case 'adm_prodtoggle': $this->adminProductToggle((int) $parts[1], $msgId); break;
            case 'adm_proddetails':$this->adminProductDetails((int) $parts[1], $msgId); break;
            case 'adm_prodpage':   $this->adminProductList($msgId, (int) ($parts[1] ?? 1)); break;

            case 'adm_catlist':    $this->adminCategoryList($msgId); break;
            case 'adm_catadd':     $this->adminCategoryAdd($msgId); break;
            case 'adm_catdel':     $this->adminCategoryDelete((int) $parts[1], $msgId); break;
            case 'adm_catdelconfirm': $this->adminCategoryDeleteConfirm((int) $parts[1], $msgId); break;
            case 'adm_cattoggle':  $this->adminCategoryToggle((int) $parts[1], $msgId); break;

            case 'adm_orderlist':  {
                // adm_orderlist:<status>:<page> or adm_orderlist:<page>
                $a = $parts[1] ?? 'pending';
                if (ctype_digit((string) $a) { $os = 'pending'; $op = (int) $a; }
                else { $os = $a; $op = (int) ($parts[2] ?? 1); }
                $this->adminOrderListByStatus($msgId, $os, $op);
                break;
            }
            case 'adm_orderpage':  $this->adminOrderListByStatus($msgId, $parts[1] ?? 'pending', (int) ($parts[2] ?? 1)); break;
            case 'adm_order':      $this->adminOrderShow((int) $parts[1], $msgId); break;
            case 'adm_orderview':  $this->adminOrderView((int) $parts[1], $msgId); break;
            case 'adm_orderstatus': $this->adminOrderListByStatus($msgId, (string) ($parts[1] ?? 'pending'), 1); break;

            case 'adm_userlist':   $this->adminUserList($msgId, (int) ($parts[1] ?? 1)); break;
            case 'adm_usershow':   $this->adminUserShow((int) $parts[1], $msgId); break;
            case 'adm_userban':    $this->adminUserToggleBan((int) $parts[1], $msgId); break;
            case 'adm_useradmin':  $this->adminUserToggleAdmin((int) $parts[1], $msgId); break;

            case 'adm_channellist':$this->adminChannelList($msgId); break;
            case 'adm_channeladd': $this->adminChannelAdd($msgId); break;
            case 'adm_channeldel': $this->adminChannelDelete((int) $parts[1], $msgId); break;
            case 'adm_channeltoggle': $this->adminChannelToggle((int) $parts[1], $msgId); break;

            case 'adm_cardlist':   $this->adminCardList($msgId); break;
            case 'adm_cardadd':    $this->adminCardAdd($msgId); break;
            case 'adm_carddel':    $this->adminCardDelete((int) $parts[1], $msgId); break;
            case 'adm_cardtoggle': $this->adminCardToggle((int) $parts[1], $msgId); break;

            case 'adm_broadcast_menu': $this->adminBroadcastMenu($msgId); break;
            case 'adm_broadcast_text': $this->adminBroadcastStart('text', $msgId); break;
            case 'adm_broadcast_photo':$this->adminBroadcastStart('photo', $msgId); break;
            case 'adm_broadcast_file':$this->adminBroadcastStart('document', $msgId); break;

            case 'adm_settings':   $this->adminSettings($msgId); break;
            case 'adm_setstart':    $this->adminSetSetting('welcome_text', 'متن خوش‌آمدگویی', $msgId); break;
            case 'adm_setrules':    $this->adminSetSetting('rules_text', 'متن قوانین', $msgId); break;
            case 'adm_setsupport':  $this->adminSetSetting('support_text', 'متن پشتیبانی', $msgId); break;
            case 'adm_setpay':      $this->adminSetSetting('payment_text', 'متن پرداخت', $msgId); break;
            case 'adm_setreward':   $this->adminSetSetting('referral_reward', 'پاداش دعوت (تومان)', $msgId); break;
            case 'adm_setstore':    $this->adminSetSetting('store_name', 'نام فروشگاه', $msgId); break;
            case 'adm_setnotifier': $this->adminSetSetting('admin_notify_id', 'آیدی عددی ادمین', $msgId); break;
            case 'adm_setperpage':  $this->adminSetSetting('per_page', 'تعداد محصول در هر صفحه', $msgId); break;

            case 'adm_logs':       $this->adminLogs($msgId, (int) ($parts[1] ?? 1)); break;
            case 'adm_logsclear':  $this->adminLogsClear($msgId); break;
            case 'adm_logsdel':    $this->adminLogsDelete((int) $parts[1], $msgId); break;

            default:
                $this->adminMenu($msgId);
        }
    }

    // ---------------- Admin: Products ----------------
    private function adminProductList(int $msgId, int $page = 1): void
    {
        $perPage = 8;
        $offset = ($page - 1) * $perPage;
        $total = (int) Database::fetchColumn('SELECT COUNT(*) FROM products');
        $products = Database::fetchAll('SELECT * FROM products ORDER BY id DESC LIMIT :o,:l',
            [':o' => $offset, ':l' => $perPage]);
        $rows = [];
        foreach ($products as $p) {
            $rows[] = [[
                'text' => ($p['is_active'] ? '✅ ' : '⬜ ') . $p['name'] . ($p['is_vip'] ? ' ⭐' : ''),
                'callback_data' => 'adm_proddetails:' . $p['id'],
            ]];
        }
        $pages = (int) ceil($total / $perPage);
        if ($pages > 1) {
            $nav = [];
            for ($i = 1; $i <= $pages; $i++) {
                $nav[] = ['text' => $i === $page ? '●' . faNum($i) : faNum($i), 'callback_data' => 'adm_prodpage:' . $i];
            }
            $rows[] = $nav;
        }
        $rows[] = [['text' => '➕ افزودن محصول', 'callback_data' => 'adm_prodadd']];
        $rows[] = [['text' => '⬅️ پنل مدیریت', 'callback_data' => 'adm_menu']];
        $kb = ['inline_keyboard' => $rows];
        $text = "📦 <b>محصولات</b> (" . faNum($total) . ")";
        $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
    }

    private function adminProductAddStep(int $msgId): void
    {
        $this->bot->editMessageText($this->chatId, $msgId,
            "➕ <b>افزودن محصول جدید</b>\n\nبرای افزودن محصول:\n۱. یک فایل (Document) یا عکس به‌عنوان فایل اصلی محصول بفرستید.\n۲. سپس نام، قیمت و سایر اطلاعات را وارد می‌کنید.\n\nبرای لغو: /cancel",
            backButton());
        $this->setState('admin_pfile');
    }

    private function adminProductDetails(int $prodId, int $msgId): void
    {
        $p = Database::fetch('SELECT * FROM products WHERE id=:i', [':i' => $prodId]);
        if (!$p) { $this->adminProductList($msgId, 1); return; }
        $cat = Database::fetch('SELECT name FROM categories WHERE id=:c', [':c' => $p['category_id']]);
        $text = "📦 <b>" . e($p['name']) . "</b>\n\n" .
            "💰 قیمت: " . ($p['price'] > 0 ? toman($p['price']) : 'رایگان') . "\n" .
            "📁 دسته: " . e($cat['name'] ?? '—') . "\n" .
            "📦 حجم: " . ($p['file_size'] ? humanSize((int)$p['file_size']) : '-') . "\n" .
            "🏷 برچسب: " . e($p['tags'] ?: '—') . "\n" .
            "⬇️ دانلودها: " . faNum($p['download_count']) . "\n" .
            "📜 توضیح: " . e($p['description'] ?: '—') . "\n" .
            "وضعیت: " . ($p['is_active'] ? 'فعال' : 'غیرفعال') . ($p['is_vip'] ? ' | VIP' : '');
        $kb = ['inline_keyboard' => [
            [['text' => $p['is_active'] ? '⬜ غیرفعال' : '✅ فعال', 'callback_data' => 'adm_prodtoggle:' . $p['id']]],
            [['text' => '🗑 حذف محصول', 'callback_data' => 'adm_proddel:' . $p['id']]],
            [['text' => '⬅️ لیست محصولات', 'callback_data' => 'adm_prodlist:1'], ['text' => '🎛 پنل', 'callback_data' => 'adm_menu']],
        ]];
        $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
    }

    private function adminProductToggle(int $prodId, int $msgId): void
    {
        Database::query('UPDATE products SET is_active = 1 - is_active WHERE id=:i', [':i' => $prodId]);
        $this->adminProductDetails($prodId, $msgId);
    }

    private function adminProductDelete(int $prodId, int $msgId): void
    {
        $p = Database::fetch('SELECT * FROM products WHERE id=:i', [':i' => $prodId]);
        if ($p) {
            if ($p['file_path']) @unlink(UPLOAD_PATH . '/' . $p['file_path']);
            if ($p['preview_image']) @unlink(UPLOAD_PATH . '/' . $p['preview_image']);
            $imgs = Database::fetchAll('SELECT * FROM product_images WHERE product_id=:i', [':i' => $prodId]);
            foreach ($imgs as $g) @unlink(UPLOAD_PATH . '/' . $g['image_path']);
            Database::delete('product_images', 'product_id=:i', [':i' => $prodId]);
            Database::delete('products', 'id=:i', [':i' => $prodId]);
        }
        $this->adminProductList($msgId, 1);
    }

    // ---------------- Product wizard steps ----------------
    private function buildCatChoiceKb(): array
    {
        $cats = Database::fetchAll('SELECT * FROM categories ORDER BY sort_order, id');
        $rows = [];
        $cols = [];
        foreach ($cats as $c) {
            $cols[] = ['text' => ($c['icon'] ?: '') . $c['name'], 'callback_data' => 'adm_pcatset:' . $c['id']];
            if (count($cols) === 2) { $rows[] = $cols; $cols = []; }
        }
        if ($cols) $rows[] = $cols;
        $rows[] = [['text' => '➖ بدون دسته', 'callback_data' => 'adm_pcatset:0']];
        $rows[] = [['text' => '❌ لغو', 'callback_data' => 'adm_pcancel']];
        return ['inline_keyboard' => $rows];
    }

    private function buildVipChoiceKb(): array
    {
        return ['inline_keyboard' => [
            [['text' => '📦 معمولی', 'callback_data' => 'adm_pvipset:0']],
            [['text' => '⭐ VIP', 'callback_data' => 'adm_pvipset:1']],
            [['text' => '❌ لغو', 'callback_data' => 'adm_pcancel']],
        ]];
    }

    private function wizProductFile(array $message): void
    {
        $fileId = null; $fileType = null; $fileName = 'file';
        if (!empty($message['document'])) {
            $fileId = $message['document']['file_id'];
            $fileType = 'document';
            $fileName = $message['document']['file_name'] ?? 'file';
        } elseif (!empty($message['photo'])) {
            $photo = end($message['photo']);
            $fileId = $photo['file_id'];
            $fileType = 'photo';
        } elseif (!empty($message['video']) && !empty($message['video']['file_id'])) {
            $fileId = $message['video']['file_id']; $fileType = 'video';
        }
        if (!$fileId) {
            $this->bot->sendMessage($this->chatId, '❗ لطفاً یک فایل (Document) یا عکس به‌عنوان فایل محصول بفرستید. یا /cancel برای لغو.', backButton());
            return;
        }
        $ext = strtolower(pathinfo($fileName, PATHINFO_EXTENSION));
        if ($ext === '') $ext = $fileType === 'photo' ? 'jpg' : 'bin';
        $name = bin2hex(random_bytes(8)) . '.' . $ext;
        $dest = UPLOAD_PATH . '/files/' . $name;
        if (!is_dir(dirname($dest))) @mkdir(dirname($dest), 0775, true);
        if (!$this->bot->downloadFile($fileId, $dest)) {
            $this->bot->sendMessage($this->chatId, '❌ دانلود فایل از تلگرام ناموفق بود. دوباره فایل را بفرستید یا /cancel.');
            return;
        }
        $size = (int) @filesize($dest);
        $this->setWizard([
            'file_path' => 'files/' . $name,
            'file_name' => $fileName,
            'file_size' => $size,
            'file_ext'  => $ext,
        ]);
        $this->setState('admin_pname');
        $this->bot->sendMessage($this->chatId,
            "✅ فایل دریافت شد (" . humanSize($size) . ")\n\n📝 نام محصول را بفرستید:", backButton());
    }

    private function wizProductName(string $text): void
    {
        $text = trim($text);
        if ($text === '') {
            $this->bot->sendMessage($this->chatId, '❗ نام نمی‌تواند خالی باشد. /cancel برای لغو.', backButton());
            return;
        }
        $w = $this->getWizard(); $w['name'] = $text; $this->setWizard($w);
        $this->setState('admin_pprice');
        $this->bot->sendMessage($this->chatId, '💰 حالا قیمت محصول را به تومان بفرستید (۰ = رایگان):', backButton());
    }

    private function wizProductPrice(string $text): void
    {
        $price = (int) preg_replace('/\D/', '', $text);
        $w = $this->getWizard(); $w['price'] = $price; $this->setWizard($w);
        $this->setState('admin_pcat');
        $this->bot->sendMessage($this->chatId, '📁 دسته‌بندی محصول را انتخاب کنید:', $this->buildCatChoiceKb());
    }


    private function adminProductSetCategory(int $catId, int $msgId): void
    {
        $w = $this->getWizard();
        $w['category_id'] = $catId > 0 ? $catId : null;
        $this->setWizard($w);
        $this->setState('admin_ptags');
        $this->bot->sendMessage($this->chatId, '🏷 برچسب‌ها را بفرستید (با ویرگول جدا کنید، یا - برای خالی):', backButton());
    }

    private function wizProductTags(string $text): void
    {
        $text = trim($text);
        $w = $this->getWizard();
        $w['tags'] = ($text === '' || $text === '-') ? '' : $text;
        $this->setWizard($w);
        $this->setState('admin_pdesc');
        $this->bot->sendMessage($this->chatId, '📜 توضیحات محصول را بفرستید (یا - برای خالی):', backButton());
    }

    private function wizProductDesc(string $text): void
    {
        $text = trim($text);
        $w = $this->getWizard();
        $w['description'] = ($text === '' || $text === '-') ? '' : $text;
        $this->setWizard($w);
        $kb = ['inline_keyboard' => [
            [['text' => '📦 معمولی', 'callback_data' => 'adm_pvipset:0']],
            [['text' => '⭐ VIP', 'callback_data' => 'adm_pvipset:1']],
            [['text' => '❌ لغو', 'callback_data' => 'adm_pcancel']],
        ]];
        $this->setState('admin_pvip');
        $this->bot->sendMessage($this->chatId, '⭐ آیا این محصول VIP است؟', $kb);
    }

    private function adminProductCancel(int $msgId): void
    {
        $this->clearState();
        $this->adminMenu($msgId);
    }

    private function adminProductSetVip(int $vip, int $msgId): void
    {
        $w = $this->getWizard();
        $w['is_vip'] = $vip;
        $this->setWizard($w);
        $kb = ['inline_keyboard' => [
            [['text' => '🌍 عمومی (فعال)', 'callback_data' => 'adm_psave:1']],
            [['text' => '🔒 غیرفعال (پیش‌نویس)', 'callback_data' => 'adm_psave:0']],
            [['text' => '❌ لغو', 'callback_data' => 'adm_pcancel']],
        ]];
        $this->bot->sendMessage($this->chatId, '✅ وضعیت انتشار محصول:', $kb);
    }

    private function adminProductSave(int $active, int $msgId): void
    {
        $w = $this->getWizard();
        if (empty($w['name']) || empty($w['file_path'])) {
            $this->clearState();
            $this->adminMenu($msgId);
            return;
        }
        Database::insert('products', [
            'name'           => $w['name'],
            'description'    => $w['description'] ?? '',
            'price'          => $w['price'] ?? 0,
            'category_id'    => $w['category_id'] ?? null,
            'preview_image'  => $w['preview_image'] ?? null,
            'file_path'      => $w['file_path'],
            'file_name'      => $w['file_name'] ?? '',
            'file_size'      => $w['file_size'] ?? 0,
            'tags'           => $w['tags'] ?? '',
            'is_vip'         => $w['is_vip'] ?? 0,
            'is_active'      => $active,
        ]);
        $this->clearState();
        $this->bot->sendMessage($this->chatId, '✅ محصول «' . e($w['name']) . '» با موفقیت ذخیره شد.');
        $this->adminProductList($msgId, 1);
    }

    // ---------------- Admin: Categories ----------------
    private function adminCategoryList(int $msgId): void
    {
        $cats = Database::fetchAll('SELECT * FROM categories ORDER BY sort_order, id');
        $rows = [];
        foreach ($cats as $c) {
            $rows[] = [
                ['text' => ($c['is_active'] ? '✅ ' : '⬜ ') . ($c['icon'] ?: '') . $c['name'], 'callback_data' => 'adm_catdel:' . $c['id']],
                ['text' => $c['is_active'] ? '⬜' : '✅', 'callback_data' => 'adm_cattoggle:' . $c['id']],
            ];
        }
        $rows[] = [['text' => '➕ افزودن دسته', 'callback_data' => 'adm_catadd']];
        $rows[] = [['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']];
        $kb = ['inline_keyboard' => $rows];
        $this->bot->editMessageText($this->chatId, $msgId, '📁 <b>دسته‌بندی‌ها</b>', $kb);
    }

    private function adminCategoryAdd(int $msgId): void
    {
        $this->bot->editMessageText($this->chatId, $msgId,
            "➕ نام دسته‌بندی جدید را بفرستید:\n(می‌توانید در ابتدای نام یک ایموجی به‌عنوان آیکن بگذارید، مثلا: 🎨 پس‌زمینه)\n\n/cancel برای لغو.",
            backButton());
        $this->setWizard([]);
        $this->setState('admin_catname');
    }

    private function wizCategoryName(string $text): void
    {
        $text = trim($text);
        if ($text === '') {
            $this->bot->sendMessage($this->chatId, '❗ نام خالی است. /cancel برای لغو.', backButton());
            return;
        }
        $icon = '';
        if (preg_match('/^(\S+)\s+(.+)$/u', $text, $m)) {
            $icon = $m[1]; $text = $m[2];
        }
        $max = (int) Database::fetchColumn('SELECT MAX(sort_order) FROM categories');
        Database::insert('categories', ['name' => $text, 'icon' => $icon, 'sort_order' => $max + 1, 'is_active' => 1]);
        $this->clearState();
        $this->bot->sendMessage($this->chatId, '✅ دسته «' . e($text) . '» اضافه شد.');
        // (No msgId here since state reply is a new message) — show fresh list.
        $this->bot->sendMessage($this->chatId, '📁 دسته‌بندی‌ها', $this->buildCatListKb());
    }

    private function buildCatListKb(): array
    {
        $cats = Database::fetchAll('SELECT * FROM categories ORDER BY sort_order, id');
        $rows = [];
        foreach ($cats as $c) {
            $rows[] = [
                ['text' => ($c['is_active'] ? '✅ ' : '⬜ ') . ($c['icon'] ?: '') . $c['name'], 'callback_data' => 'adm_catdel:' . $c['id']],
                ['text' => $c['is_active'] ? '⬜' : '✅', 'callback_data' => 'adm_cattoggle:' . $c['id']],
            ];
        }
        $rows[] = [['text' => '➕ افزودن دسته', 'callback_data' => 'adm_catadd']];
        $rows[] = [['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']];
        return ['inline_keyboard' => $rows];
    }

    private function adminCategoryDelete(int $catId, int $msgId): void
    {
        // If we send inline keyboard on post creation, always render the last step with a button
        $c = Database::fetch('SELECT name FROM categories WHERE id=:i', [':i' => $catId]);
        $this->bot->editMessageText($this->chatId, $msgId,
            '🗑 حذف دسته «' . e($c['name'] ?? '') . '»؟ محصولاتِ این دسته حذف نمی‌شوند ولی «بدون دسته» می‌شوند.',
            ['inline_keyboard' => [
                [['text' => '✅ بله، حذف کن', 'callback_data' => 'adm_catdelconfirm:' . $catId]],
                [['text' => '❌ بازگشت', 'callback_data' => 'adm_catlist']],
            ]]);
    }

    private function adminCategoryToggle(int $catId, int $msgId): void
    {
        Database::query('UPDATE categories SET is_active = 1 - is_active WHERE id=:i', [':i' => $catId]);
        $this->adminCategoryList($msgId);
    }

    private function adminCategoryDeleteConfirm(int $catId, int $msgId): void
    {
        Database::query('UPDATE products SET category_id=NULL WHERE category_id=:i', [':i' => $catId]);
        Database::delete('categories', 'id=:i', [':i' => $catId]);
        $this->adminCategoryList($msgId);
    }

    // ---------------- Admin: Orders ----------------
    private function adminOrderListByStatus(int $msgId, string $status, int $page): void
    {
        $valid = ['pending', 'approved', 'rejected', 'need_info', 'all'];
        if (!in_array($status, $valid, true)) $status = 'pending';
        $perPage = 8;
        $offset = ($page - 1) * $perPage;
        $params = [];
        if ($status === 'all') {
            $total = (int) Database::fetchColumn('SELECT COUNT(*) FROM orders');
            $orders = Database::fetchAll('SELECT o.*, p.name pname FROM orders o JOIN products p ON p.id=o.product_id ORDER BY o.id DESC LIMIT :o,:l',
                [':o' => $offset, ':l' => $perPage]);
        } else {
            $total = (int) Database::fetchColumn('SELECT COUNT(*) FROM orders WHERE status=:s', [':s' => $status]);
            $orders = Database::fetchAll('SELECT o.*, p.name pname FROM orders o JOIN products p ON p.id=o.product_id WHERE o.status=:s ORDER BY o.id DESC LIMIT :o,:l',
                [':s' => $status, ':o' => $offset, ':l' => $perPage]);
        }
        // Status filter row
        $labels = ['pending' => '⏳ در انتظار', 'approved' => '✅ تأیید', 'rejected' => '❌ رد', 'need_info' => '❓ نیاز توضیح', 'all' => '📋 همه'];
        $filterRow = [];
        foreach ($labels as $k => $lbl) {
            $filterRow[] = ['text' => ($k === $status ? '● ' : '') . $lbl, 'callback_data' => 'adm_orderpage:' . $k . ':1'];
        }
        $rows = [$filterRow];
        if (!$orders) {
            $rows[] = [['text' => '— موردی نیست —', 'callback_data' => 'adm_orderpage:' . $status . ':1']];
        } else {
            foreach ($orders as $o) {
                $rows[] = [['text' => '🧾 ' . $o['order_code'] . ' — ' . $o['pname'] . ' (' . faNum(number_format($o['price'])) . 'ت)', 'callback_data' => 'adm_order:' . $o['id']]];
            }
            $pages = (int) ceil($total / $perPage);
            if ($pages > 1) {
                $nav = [];
                for ($i = 1; $i <= $pages; $i++) {
                    $nav[] = ['text' => $i === $page ? '●' . faNum($i) : faNum($i), 'callback_data' => 'adm_orderpage:' . $status . ':' . $i];
                }
                $rows[] = $nav;
            }
        }
        $rows[] = [['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']];
        $kb = ['inline_keyboard' => $rows];
        $this->bot->editMessageText($this->chatId, $msgId, '📋 <b>سفارش‌ها</b> (' . faNum($total) . ')', $kb);
    }

    private function adminOrderShow(int $orderId, int $msgId): void
    {
        $o = Database::fetch('SELECT o.*, p.name pname, p.file_path FROM orders o JOIN products p ON p.id=o.product_id WHERE o.id=:i', [':i' => $orderId]);
        if (!$o) { $this->adminOrderListByStatus($msgId, 'pending', 1); return; }
        $u = Database::fetch('SELECT * FROM users WHERE id=:i', [':i' => $o['user_id']]);
        $statusBadge = ['pending' => '⏳ در انتظار', 'approved' => '✅ تأیید', 'rejected' => '❌ رد', 'need_info' => '❓ نیاز توضیح'];
        $text = "📋 <b>سفارش</b> " . e($o['order_code']) . "\n\n" .
            "📦 محصول: " . e($o['pname']) . "\n" .
            "💰 مبلغ: " . toman($o['price']) . "\n" .
            "👤 خریدار: " . e($u['first_name'] ?? '') . ($u['username'] ? ' @' . e($u['username']) : '') . "\n" .
            "📱 تلگرام: <code>" . faNum($u['telegram_id'] ?? '') . "</code>\n" .
            "📌 وضعیت: " . ($statusBadge[$o['status']] ?? $o['status']) . "\n";
        if (!empty($o['receipt_message'])) $text .= "📝 توضیح: " . e($o['receipt_message']) . "\n";
        if (!empty($o['admin_note'])) $text .= "🔖 یادداشت مدیر: " . e($o['admin_note']) . "\n";
        if (!empty($o['receipt_file_id'])) $text .= "\n📎 رسید نزد مدیر ارسال شد.";

        $rows = [
            [['text' => '✅ تأیید و ارسال', 'callback_data' => 'admin_approve:' . $o['id']],
             ['text' => '❌ رد', 'callback_data' => 'admin_reject:' . $o['id']]],
            [['text' => '❓ درخواست توضیح', 'callback_data' => 'admin_info:' . $o['id']]],
        ];
        if (!empty($o['receipt_file_id'])) {
            $rows[] = [['text' => '👁 نمایش رسید', 'callback_data' => 'adm_orderview:' . $o['id']]];
        }
        $rows[] = [['text' => '⬅️ بازگشت', 'callback_data' => 'adm_orderlist:pending:1']];
        $kb = ['inline_keyboard' => $rows];
        // try edit; if it fails (e.g. message had a file), send new.
        $r = $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
        if (empty($r['ok'])) {
            $this->bot->sendMessage($this->chatId, $text, $kb);
        }
        // Auto-send the receipt to the admin chat so they can see it.
        if (!empty($o['receipt_file_id']) && in_array($o['receipt_file_type'] ?? '', ['photo', 'document'], true)) {
            $this->bot->copyFile($this->chatId, $o['receipt_file_id'], $o['receipt_file_type'], '🧾 رسید سفارش ' . $o['order_code']);
        }
    }

    private function adminOrderView(int $orderId, int $msgId): void
    {
        $o = Database::fetch('SELECT * FROM orders WHERE id=:i', [':i' => $orderId]);
        if ($o && !empty($o['receipt_file_id']) && in_array($o['receipt_file_type'] ?? '', ['photo', 'document'], true)) {
            $this->bot->answerCallbackQuery((string) $this->callback['id'], '📩 رسید ارسال شد');
            $this->bot->copyFile($this->chatId, $o['receipt_file_id'], $o['receipt_file_type'], '🧾 رسید ' . $o['order_code']);
        } else {
            $this->bot->answerCallbackQuery((string) $this->callback['id'], 'رسید وجود ندارد', true);
        }
    }

    // ---------------- Admin: Users ----------------
    private function adminUserList(int $msgId, int $page = 1): void
    {
        $perPage = 10;
        $offset = ($page - 1) * $perPage;
        $total = (int) Database::fetchColumn('SELECT COUNT(*) FROM users');
        $users = Database::fetchAll('SELECT * FROM users ORDER BY id DESC LIMIT :o,:l', [':o' => $offset, ':l' => $perPage]);
        $rows = [];
        foreach ($users as $u) {
            $badge = '';
            if ((int) $u['is_admin'] === 1) $badge .= '🛡';
            if ((int) $u['is_blocked'] === 1) $badge .= '🚫';
            $rows[] = [['text' => '#' . faNum($u['id']) . ' ' . e(($u['first_name'] ?: '')) . $badge, 'callback_data' => 'adm_usershow:' . $u['id']]];
        }
        $pages = (int) ceil($total / $perPage);
        if ($pages > 1) {
            $nav = [];
            for ($i = 1; $i <= $pages; $i++) {
                $nav[] = ['text' => $i === $page ? '●' . faNum($i) : faNum($i), 'callback_data' => 'adm_userlist:' . $i];
            }
            $rows[] = $nav;
        }
        $rows[] = [['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']];
        $kb = ['inline_keyboard' => $rows];
        $this->bot->editMessageText($this->chatId, $msgId, '👥 <b>کاربران</b> (' . faNum($total) . ')', $kb);
    }

    private function adminUserShow(int $userId, int $msgId): void
    {
        $u = Database::fetch('SELECT * FROM users WHERE id=:i', [':i' => $userId]);
        if (!$u) { $this->adminUserList($msgId, 1); return; }
        $orders = (int) Database::fetchColumn('SELECT COUNT(*) FROM orders WHERE user_id=:u', [':u' => $userId]);
        $refs   = (int) Database::fetchColumn('SELECT COUNT(*) FROM users WHERE referred_by=:i', [':i' => $userId]);
        $text = "👤 <b>کاربر</b> #" . faNum($u['id']) . "\n\n" .
            "🆔 تلگرام: <code>" . faNum($u['telegram_id']) . "</code>\n" .
            "👋 نام: " . e($u['first_name'] ?? '-') . "\n" .
            "🧾 سفارش‌ها: " . faNum($orders) . "\n" .
            "👥 زیرمجموعه: " . faNum($refs) . "\n" .
            "💰 موجودی: " . toman($u['referral_balance']) . "\n" .
            "🛡 ادمین: " . ((int)$u['is_admin'] ? 'بله' : 'خیر') . "\n" .
            "🚫 مسدود: " . ((int)$u['is_blocked'] ? 'بله' : 'خیر');
        $kb = ['inline_keyboard' => [
            [['text' => (int)$u['is_blocked'] ? '✅ رفع مسدود' : '🚫 مسدود کن', 'callback_data' => 'adm_userban:' . $u['id']],
             ['text' => (int)$u['is_admin'] ? '➖ حذف ادمین' : '➕ ادمین کن', 'callback_data' => 'adm_useradmin:' . $u['id']]],
            [['text' => '⬅️ لیست کاربران', 'callback_data' => 'adm_userlist:1']],
        ]];
        $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
    }

    private function adminUserToggleBan(int $userId, int $msgId): void
    {
        Database::query('UPDATE users SET is_blocked = 1 - is_blocked WHERE id=:i', [':i' => $userId]);
        $this->adminUserShow($userId, $msgId);
    }

    private function adminUserToggleAdmin(int $userId, int $msgId): void
    {
        Database::query('UPDATE users SET is_admin = 1 - is_admin WHERE id=:i', [':i' => $userId]);
        $this->adminUserShow($userId, $msgId);
    }

    // ---------------- Admin: Channels ----------------
    private function adminChannelList(int $msgId): void
    {
        $channels = Database::fetchAll('SELECT * FROM channels ORDER BY id');
        $rows = [];
        foreach ($channels as $ch) {
            $rows[] = [
                ['text' => ($ch['is_active'] ? '✅ ' : '⬜ ') . e($ch['channel_username']), 'callback_data' => 'adm_channeldel:' . $ch['id']],
                ['text' => $ch['is_active'] ? '⬜' : '✅', 'callback_data' => 'adm_channeltoggle:' . $ch['id']],
            ];
        }
        $rows[] = [['text' => '➕ افزودن کانال', 'callback_data' => 'adm_channeladd']];
        $rows[] = [['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']];
        $kb = ['inline_keyboard' => $rows];
        $this->bot->editMessageText($this->chatId, $msgId, '📢 <b>کانال‌های اجباری</b>', $kb);
    }

    private function adminChannelAdd(int $msgId): void
    {
        $this->bot->editMessageText($this->chatId, $msgId,
            "➕ <b>افزودن کانال اجباری</b>\n\nیوزرنیم کانال را بفرستید (با یا بدون @).\nمثلا: mychannel یا @mychannel\n\nاول مطمئن شوید ربات در کانال عضو و ادمین است.\n/cancel برای لغو.",
            backButton());
        $this->setState('admin_channeluser');
    }

    private function wizChannelUser(string $text): void
    {
        $text = ltrim(trim($text), '@');
        if ($text === '') {
            $this->bot->sendMessage($this->chatId, '❗ یوزرنیم خالی است. /cancel برای لغو.', backButton());
            return;
        }
        // Ask bot to resolve channel info (optional — keeps title/invite_link)
        $info = $this->bot->request('getChat', ['chat_id' => '@' . $text]);
        $title = $info['result']['title'] ?? $text;
        $invite = null;
        $resInvite = $this->bot->request('createChatInviteLink', ['chat_id' => '@' . $text]);
        if (!empty($resInvite['result']['invite_link'])) $invite = $resInvite['result']['invite_link'];
        Database::insert('channels', [
            'channel_username' => $text,
            'channel_id' => null,
            'title' => $title,
            'invite_link' => $invite,
            'is_active' => 1,
        ]);
        $this->clearState();
        $this->bot->sendMessage($this->chatId, '✅ کانال «' . e($text) . '» اضافه شد.');
    }

    private function adminChannelDelete(int $chId, int $msgId): void
    {
        Database::delete('channels', 'id=:i', [':i' => $chId]);
        $this->adminChannelList($msgId);
    }

    private function adminChannelToggle(int $chId, int $msgId): void
    {
        Database::query('UPDATE channels SET is_active = 1 - is_active WHERE id=:i', [':i' => $chId]);
        $this->adminChannelList($msgId);
    }

    // ---------------- Admin: Cards ----------------
    private function adminCardList(int $msgId): void
    {
        $cards = Database::fetchAll('SELECT * FROM cards ORDER BY sort_order, id');
        $rows = [];
        foreach ($cards as $c) {
            $rows[] = [
                ['text' => ($c['is_active'] ? '✅ ' : '⬜ ') . faNum($c['card_number']) . ' — ' . e($c['holder_name']), 'callback_data' => 'adm_carddel:' . $c['id']],
                ['text' => $c['is_active'] ? '⬜' : '✅', 'callback_data' => 'adm_cardtoggle:' . $c['id']],
            ];
        }
        $rows[] = [['text' => '➕ افزودن کارت', 'callback_data' => 'adm_cardadd']];
        $rows[] = [['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']];
        $kb = ['inline_keyboard' => $rows];
        $this->bot->editMessageText($this->chatId, $msgId, '💳 <b>کارت‌های بانکی</b>', $kb);
    }

    private function adminCardAdd(int $msgId): void
    {
        $this->bot->editMessageText($this->chatId, $msgId,
            "➕ <b>افزودن کارت بانکی</b>\n\nشماره کارت (۱۶ رقمی) را بفرستید:\n/cancel برای لغو.",
            backButton());
        $this->setWizard([]);
        $this->setState('admin_cardnum');
    }

    private function wizCardNum(string $text): void
    {
        $num = preg_replace('/\D/', '', $text);
        if (strlen($num) < 16) {
            $this->bot->sendMessage($this->chatId, '❗ شماره کارت باید حداقل ۱۶ رقم باشد. /cancel برای لغو.', backButton());
            return;
        }
        $w = $this->getWizard(); $w['card_number'] = $num; $this->setWizard($w);
        $this->setState('admin_cardholder');
        $this->bot->sendMessage($this->chatId, '👤 نام صاحب کارت را بفرستید:', backButton());
    }

    private function wizCardHolder(string $text): void
    {
        $text = trim($text);
        if ($text === '') { $this->bot->sendMessage($this->chatId, '❗ نام خالی است. /cancel برای لغو.', backButton()); return; }
        $w = $this->getWizard(); $w['holder_name'] = $text; $this->setWizard($w);
        $this->setState('admin_cardbank');
        $this->bot->sendMessage($this->chatId, '🏦 نام بانک را بفرستید (یا - برای خالی):', backButton());
    }

    private function wizCardBank(string $text): void
    {
        $text = trim($text);
        $w = $this->getWizard();
        Database::insert('cards', [
            'card_number' => $w['card_number'],
            'holder_name' => $w['holder_name'],
            'bank_name'   => ($text === '' || $text === '-') ? null : $text,
            'is_active'   => 1,
            'sort_order'   => 0,
        ]);
        $this->clearState();
        $this->bot->sendMessage($this->chatId, '✅ کارت «' . e($w['holder_name']) . '» اضافه شد.');
    }

    private function adminCardDelete(int $cardId, int $msgId): void
    {
        Database::delete('cards', 'id=:i', [':i' => $cardId]);
        $this->adminCardList($msgId);
    }

    private function adminCardToggle(int $cardId, int $msgId): void
    {
        Database::query('UPDATE cards SET is_active = 1 - is_active WHERE id=:i', [':i' => $cardId]);
        $this->adminCardList($msgId);
    }

    // ---------------- Admin: Settings ----------------
    private function adminSettings(int $msgId): void
    {
        $storeName = e(setting('store_name', 'فروشگاه'));
        $reward = (int) setting('referral_reward', '0');
        $perPage = (int) setting('per_page', '8');
        $notify = (int) setting('admin_notify_id', '0');
        $rows = [
            [['text' => '👋 متن خوش‌آمدگویی', 'callback_data' => 'adm_setstart']],
            [['text' => '📖 متن قوانین', 'callback_data' => 'adm_setrules']],
            [['text' => '📞 متن پشتیبانی', 'callback_data' => 'adm_setsupport']],
            [['text' => '💳 متن پرداخت', 'callback_data' => 'adm_setpay']],
            [['text' => '🎁 پاداش دعوت: ' . faNum(number_format($reward)) . ' ت', 'callback_data' => 'adm_setreward']],
            [['text' => '🏷 نام فروشگاه: ' . $storeName, 'callback_data' => 'adm_setstore']],
            [['text' => '🔢 آیدی عددی مدیریت: ' . faNum($notify), 'callback_data' => 'adm_setnotifier']],
            [['text' => '📦 تعداد در هر صفحه: ' . faNum($perPage), 'callback_data' => 'adm_setperpage']],
            [['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']],
        ];
        $this->bot->editMessageText($this->chatId, $msgId, '⚙️ <b>تنظیمات</b>', ['inline_keyboard' => $rows]);
    }

    private function adminSetSetting(string $key, string $label, int $msgId): void
    {
        $current = setting($key, '');
        $preview = mb_substr((string) $current, 0, 500);
        $this->bot->editMessageText($this->chatId, $msgId,
            "✏️ <b>ویرایش:</b> " . e($label) . "\n\n📝 مقدار فعلی:\n<code>" . e($preview) . "</code>\n\nمقدار جدید را بفرستید:\n/cancel برای لغو.",
            backButton());
        $this->setWizard(['setting_key' => $key]);
        $this->setState('admin_set_' . $key);
    }

    private function wizSettingValue(string $key, string $text): void
    {
        $text = trim($text);
        if ($text === '' || $text === '-') $text = '';
        setSetting($key, $text);
        $this->clearState();
        $this->bot->sendMessage($this->chatId, '✅ تنظیم «' . e($key) . '» ذخیره شد.', $this->buildSettingsKb());
    }

    private function buildSettingsKb(): array
    {
        $storeName = e(setting('store_name', 'فروشگاه'));
        $reward = (int) setting('referral_reward', '0');
        $perPage = (int) setting('per_page', '8');
        $notify = (int) setting('admin_notify_id', '0');
        return ['inline_keyboard' => [
            [['text' => '👋 متن خوش‌آمدگویی', 'callback_data' => 'adm_setstart']],
            [['text' => '📖 متن قوانین', 'callback_data' => 'adm_setrules']],
            [['text' => '📞 متن پشتیبانی', 'callback_data' => 'adm_setsupport']],
            [['text' => '💳 متن پرداخت', 'callback_data' => 'adm_setpay']],
            [['text' => '🎁 پاداش دعوت: ' . faNum(number_format($reward)) . ' ت', 'callback_data' => 'adm_setreward']],
            [['text' => '🏷 نام فروشگاه: ' . $storeName, 'callback_data' => 'adm_setstore']],
            [['text' => '🔢 آیدی عددی مدیریت: ' . faNum($notify), 'callback_data' => 'adm_setnotifier']],
            [['text' => '📦 تعداد در هر صفحه: ' . faNum($perPage), 'callback_data' => 'adm_setperpage']],
            [['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']],
        ]];
    }

    // ---------------- Admin: Broadcast ----------------
    private function adminBroadcastMenu(int $msgId): void
    {
        $kb = ['inline_keyboard' => [
            [['text' => '📝 پیام متنی', 'callback_data' => 'adm_broadcast_text']],
            [['text' => '🖼 عکس + کپشن', 'callback_data' => 'adm_broadcast_photo']],
            [['text' => '📎 فایل + کپشن', 'callback_data' => 'adm_broadcast_file']],
            [['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']],
        ]];
        // Show last broadcast status if any
        $last = Database::fetch('SELECT * FROM broadcasts ORDER BY id DESC LIMIT 1');
        $text = '📣 <b>پیام همگانی</b>';
        if ($last) {
            $text .= "\n\nآخرین پیام (#" . faNum($last['id']) . "): ارسال‌شده " . faNum($last['sent']) . " | ناموفق " . faNum($last['failed']) . " از " . faNum($last['total']);
        }
        $text .= "\n\nنوع پیام را انتخاب کنید:";
        $this->bot->editMessageText($this->chatId, $msgId, $text, $kb);
    }

    private function adminBroadcastStart(string $type, int $msgId): void
    {
        $hint = ['text' => 'متن پیام همگانی را بفرستید', 'photo' => 'یک عکس بفرستید (کپشن آن پیام همگانی خواهد بود)', 'document' => 'یک فایل بفرستید (کپشن آن پیام همگانی خواهد بود)'][$type] ?? 'پیام را بفرستید';
        $this->bot->editMessageText($this->chatId, $msgId,
            "📣 <b>پیام همگانی</b> ($type)\n\n" . e($hint) . ":\n\n⚠️ ارسال به همه کاربران ممکن است طول بکشد. /cancel برای لغو.",
            backButton());
        $this->setWizard(['bc_type' => $type]);
        $this->setState('admin_bc_text');
    }

    private function wizBroadcastText(array $message): void
    {
        $w = $this->getWizard();
        $type = $w['bc_type'] ?? 'text';
        $content = $caption = null;
        $fileId = null;
        if ($type === 'text') {
            $content = trim((string) ($message['text'] ?? ''));
            if ($content === '') { $this->bot->sendMessage($this->chatId, '❗ متن خالی است. /cancel برای لغو.', backButton()); return; }
        } elseif ($type === 'photo') {
            if (empty($message['photo'])) { $this->bot->sendMessage($this->chatId, '❗ عکس بفرستید. /cancel برای لغو.', backButton()); return; }
            $photo = end($message['photo']);
            $fileId = $photo['file_id'];
            $caption = trim((string) ($message['caption'] ?? ''));
        } else { // document
            if (empty($message['document']['file_id'])) { $this->bot->sendMessage($this->chatId, '❗ فایل بفرستید. /cancel برای لغو.', backButton()); return; }
            $fileId = $message['document']['file_id'];
            $caption = trim((string) ($message['caption'] ?? ''));
        }
        $bcId = Database::insert('broadcasts', [
            'type' => $type, 'content' => $content, 'file_id' => $fileId, 'caption' => $caption, 'total' => 0, 'sent' => 0, 'failed' => 0, 'status' => 'running',
        ]);
        $this->clearState();
        $this->bot->sendMessage($this->chatId, '🚀 پیام همگانی آغاز شد…');

        $users = Database::fetchAll('SELECT telegram_id, is_blocked FROM users WHERE is_blocked=0');
        Database::update('broadcasts', ['total' => count($users)], 'id=:i', [':i' => $bcId]);
        $sent = 0; $failed = 0;
        foreach ($users as $idx => $u) {
            $res = match ($type) {
                'text' => $this->bot->sendMessage((int) $u['telegram_id'], $content),
                'photo' => $this->bot->sendPhoto((int) $u['telegram_id'], $fileId, $caption),
                default => $this->bot->sendDocument((int) $u['telegram_id'], $fileId, $caption),
            };
            if (!empty($res['ok'])) { $sent++; } else { $failed++; }
            Database::update('broadcasts', ['sent' => $sent, 'failed' => $failed], 'id=:i', [':i' => $bcId]);
            // Telegram rate limit ~30 msg/s; sleep a little every 25 recipients
            if ($idx > 0 && $idx % 25 === 0) usleep(500000);
        }
        Database::update('broadcasts', ['status' => 'done'], 'id=:i', [':i' => $bcId]);
        $this->bot->sendMessage($this->chatId,
            "✅ پیام همگانی تمام شد.\n📨 ارسال‌شده: " . faNum($sent) . "\n❌ ناموفق: " . faNum($failed) . " از " . faNum(count($users)),
            ['inline_keyboard' => [[['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']]]]);
    }

    // ---------------- Admin: Logs ----------------
    private function adminLogs(int $msgId, int $page = 1): void
    {
        $perPage = 10;
        $offset = ($page - 1) * $perPage;
        $total = (int) Database::fetchColumn('SELECT COUNT(*) FROM logs');
        $logs = Database::fetchAll('SELECT * FROM logs ORDER BY id DESC LIMIT :o,:l', [':o' => $offset, ':l' => $perPage]);
        $rows = [];
        foreach ($logs as $l) {
            $rows[] = [['text' => '[' . $l['level'] . '] ' . mb_substr((string) $l['message'], 0, 60), 'callback_data' => 'adm_logsdel:' . $l['id']]];
        }
        $pages = (int) ceil($total / $perPage);
        if ($pages > 1) {
            $nav = [];
            for ($i = 1; $i <= $pages; $i++) {
                $nav[] = ['text' => $i === $page ? '●' . faNum($i) : faNum($i), 'callback_data' => 'adm_logs:' . $i];
            }
            $rows[] = $nav;
        }
        $rows[] = [['text' => '🗑 پاک کردن همه', 'callback_data' => 'adm_logsclear'], ['text' => '⬅️ پنل', 'callback_data' => 'adm_menu']];
        $kb = ['inline_keyboard' => $rows];
        $this->bot->editMessageText($this->chatId, $msgId, '🐛 <b>لاگ خطاها</b> (' . faNum($total) . ')', $kb);
    }

    private function adminLogsDelete(int $logId, int $msgId): void
    {
        Database::delete('logs', 'id=:i', [':i' => $logId]);
        $this->adminLogs($msgId, 1);
    }

    private function adminLogsClear(int $msgId): void
    {
        Database::query('TRUNCATE TABLE logs');
        $this->adminLogs($msgId, 1);
    }

    /** Admin wizard state machine — driven by states returned by handleState. */
    private function handleAdminState(string $state, string $text, array $message): void
    {
        // Product add wizard: admin_pfile -> admin_pname -> admin_pprice ->
        // admin_pcat -> admin_ptags -> admin_pdesc -> admin_pvip
        if ($state === 'admin_pfile')  { $this->wizProductFile($message); return; }
        if ($state === 'admin_pname')  { $this->wizProductName($text); return; }
        if ($state === 'admin_pprice') { $this->wizProductPrice($text); return; }
        if ($state === 'admin_pcat')   { $this->bot->sendMessage($this->chatId, '📁 لطفاً دسته‌بندی را از دکمه‌های زیر انتخاب کنید (یا /cancel):', $this->buildCatChoiceKb()); return; }
        if ($state === 'admin_ptags')  { $this->wizProductTags($text); return; }
        if ($state === 'admin_pdesc')  { $this->wizProductDesc($text); return; }
        if ($state === 'admin_pvip')   { $this->bot->sendMessage($this->chatId, '⭐ لطفاً از دکمه‌های زیر انتخاب کنید (یا /cancel):', $this->buildVipChoiceKb()); return; }

        // Category wizard
        if ($state === 'admin_catname') { $this->wizCategoryName($text); return; }

        // Channel wizard
        if ($state === 'admin_channeluser') { $this->wizChannelUser($text); return; }

        // Card wizard
        if ($state === 'admin_cardnum')   { $this->wizCardNum($text); return; }
        if ($state === 'admin_cardholder'){ $this->wizCardHolder($text); return; }
        if ($state === 'admin_cardbank')  { $this->wizCardBank($text); return; }

        // Settings wizard
        if (str_starts_with($state, 'admin_set_')) {
            $this->wizSettingValue(substr($state, 10), $text);
            return;
        }

        // Broadcast wizard
        if ($state === 'admin_bc_text') { $this->wizBroadcastText($message); return; }

        $this->clearState();
        $this->adminMenu();
    }
}
