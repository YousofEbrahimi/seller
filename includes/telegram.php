<?php
/**
 * Telegram Bot API helper using cURL (no external libraries).
 *
 * Connectivity options for hosts that block api.telegram.org:
 *  - TELEGRAM_API_BASE: Cloudflare Worker reverse proxy URL (recommended)
 *  - PROXY_*:           HTTP/SOCKS5 proxy server (alternative)
 */
class Telegram
{
    private string $token;
    private string $apiBase;
    private string $fileBase;

    public function __construct(string $token)
    {
        $this->token = $token;
        // Use the Cloudflare Worker URL if configured, otherwise call Telegram directly.
        $base = defined('TELEGRAM_API_BASE') && TELEGRAM_API_BASE !== ''
            ? rtrim(TELEGRAM_API_BASE, '/')
            : 'https://api.telegram.org';
        $this->apiBase  = $base . '/bot' . $token . '/';
        $this->fileBase = $base . '/file/bot' . $token . '/';
    }

    private function curlOptions(bool $forDownload = false): array
    {
        $opts = [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT         => $forDownload ? 120 : 60,
            CURLOPT_CONNECTTIMEOUT  => 30,
            // Force IPv4: many shared hosts have no working IPv6 route.
            CURLOPT_IPRESOLVE       => CURL_IPRESOLVE_V4,
            CURLOPT_SSL_VERIFYPEER  => true,
            CURLOPT_SSL_VERIFYHOST  => 2,
        ];
        // Pick a CA bundle
        $iniCainfo = ini_get('curl.cainfo');
        if ($iniCainfo && is_file($iniCainfo)) {
            $opts[CURLOPT_CAINFO] = $iniCainfo;
        } else {
            $bundled = __DIR__ . '/../assets/cacert.pem';
            if (is_file($bundled)) {
                $opts[CURLOPT_CAINFO] = $bundled;
            }
        }
        // Optional HTTP/SOCKS5 proxy
        if (defined('PROXY_HOST') && PROXY_HOST !== '') {
            $opts[CURLOPT_PROXY] = PROXY_HOST;
            $opts[CURLOPT_PROXYPORT] = (int) PROXY_PORT;
            $opts[CURLOPT_PROXYTYPE] = strtoupper(PROXY_TYPE) === 'SOCKS5' ? CURLPROXY_SOCKS5 : CURLPROXY_HTTP;
            if (PROXY_USER !== '') {
                $opts[CURLOPT_PROXYUSERPWD] = PROXY_USER . ':' . PROXY_PASS;
            }
        }
        return $opts;
    }

    public function request(string $method, array $params = []): array
    {
        $url = $this->apiBase . $method;
        $ch = curl_init($url);
        $opts = $this->curlOptions();
        $hasFile = false;
        foreach ($params as $k => $v) {
            if (is_string($v) && strpos($v, '@') === 0 && file_exists(substr($v, 1))) {
                $params[$k] = new CURLFile(realpath(substr($v, 1)));
                $hasFile = true;
            }
        }
        if (!empty($params)) {
            $opts[CURLOPT_POST] = true;
            $opts[CURLOPT_POSTFIELDS] = $hasFile ? $params : http_build_query($params);
        } else {
            $opts[CURLOPT_POST] = true;
        }
        curl_setopt_array($ch, $opts);
        $raw = curl_exec($ch);
        $err = curl_error($ch);
        $errno = curl_errno($ch);
        $curlInfo = curl_getinfo($ch);
        curl_close($ch);

        if ($raw === false) {
            $msg = 'Telegram cURL error #' . $errno . ': ' . $err;
            if (class_exists('Database', false)) {
                Database::logError($msg, 'HTTP ' . ($curlInfo['http_code'] ?? 0) . ' | ' . $method);
            }
            return [
                'ok'          => false,
                'description' => $msg,
                'error_code'  => $errno,
                '_method'     => $method,
            ];
        }
        $json = json_decode($raw, true);
        // Non-JSON response from Telegram (HTML error page, etc.)
        if (!is_array($json)) {
            $snippet = mb_substr((string) $raw, 0, 300);
            if (class_exists('Database', false)) {
                Database::logError('Telegram invalid response', $snippet);
            }
            return [
                'ok'          => false,
                'description' => 'Telegram returned a non-JSON response (HTTP ' . ($curlInfo['http_code'] ?? 0) . '): ' . $snippet,
                'error_code'  => ($curlInfo['http_code'] ?? 0),
                '_method'     => $method,
            ];
        }
        return $json;
    }

    public function sendMessage(int|string $chatId, string $text, $keyboard = null, string $parseMode = 'HTML', bool $disablePreview = true): array
    {
        $params = [
            'chat_id'                  => $chatId,
            'text'                     => $text,
            'parse_mode'               => $parseMode,
            'disable_web_page_preview' => $disablePreview,
        ];
        if ($keyboard !== null) {
            $params['reply_markup'] = is_string($keyboard) ? $keyboard : json_encode($keyboard, JSON_UNESCAPED_UNICODE);
        }
        return $this->request('sendMessage', $params);
    }

    public function sendPhoto(int|string $chatId, string $photo, ?string $caption = null, $keyboard = null): array
    {
        $params = ['chat_id' => $chatId, 'photo' => $photo];
        if ($caption !== null) {
            $params['caption'] = $caption;
            $params['parse_mode'] = 'HTML';
        }
        if ($keyboard !== null) {
            $params['reply_markup'] = is_string($keyboard) ? $keyboard : json_encode($keyboard, JSON_UNESCAPED_UNICODE);
        }
        return $this->request('sendPhoto', $params);
    }

    public function sendDocument(int|string $chatId, string $document, ?string $caption = null, $keyboard = null): array
    {
        $params = ['chat_id' => $chatId, 'document' => $document];
        if ($caption !== null) {
            $params['caption'] = $caption;
            $params['parse_mode'] = 'HTML';
        }
        if ($keyboard !== null) {
            $params['reply_markup'] = is_string($keyboard) ? $keyboard : json_encode($keyboard, JSON_UNESCAPED_UNICODE);
        }
        return $this->request('sendDocument', $params);
    }

    public function answerCallbackQuery(string $id, ?string $text = null, bool $alert = false): array
    {
        return $this->request('answerCallbackQuery', [
            'callback_query_id' => $id,
            'text'              => $text,
            'show_alert'        => $alert,
        ]);
    }

    public function editMessageText(int|string $chatId, int $messageId, string $text, $keyboard = null, string $parseMode = 'HTML'): array
    {
        $params = [
            'chat_id'      => $chatId,
            'message_id'   => $messageId,
            'text'         => $text,
            'parse_mode'   => $parseMode,
            'disable_web_page_preview' => true,
        ];
        if ($keyboard !== null) {
            $params['reply_markup'] = is_string($keyboard) ? $keyboard : json_encode($keyboard, JSON_UNESCAPED_UNICODE);
        }
        return $this->request('editMessageText', $params);
    }

    public function editMessageReplyMarkup(int|string $chatId, int $messageId, $keyboard): array
    {
        return $this->request('editMessageReplyMarkup', [
            'chat_id'      => $chatId,
            'message_id'  => $messageId,
            'reply_markup' => is_string($keyboard) ? $keyboard : json_encode($keyboard, JSON_UNESCAPED_UNICODE),
        ]);
    }

    public function deleteMessage(int|string $chatId, int $messageId): array
    {
        return $this->request('deleteMessage', ['chat_id' => $chatId, 'message_id' => $messageId]);
    }

    public function setWebhook(string $url, string $secretToken = ''): array
    {
        $params = ['url' => $url];
        if ($secretToken !== '') {
            $params['secret_token'] = $secretToken;
        }
        return $this->request('setWebhook', $params);
    }

    public function deleteWebhook(): array
    {
        return $this->request('deleteWebhook');
    }

    /**
     * Long-polling: get pending updates.
     * Returns ['ok'=>true,'result'=>[...updates]] on success.
     */
    public function getUpdates(int $offset = 0, int $limit = 50, int $timeout = 30): array
    {
        return $this->request('getUpdates', [
            'offset'  => $offset,
            'limit'   => $limit,
            'timeout' => $timeout,
            'allowed_updates' => json_encode([
                'message', 'edited_message', 'callback_query', 'channel_post',
            ]),
        ]);
    }

    /**
     * Download a Telegram file by file_id into a local path.
     * Returns the absolute path on success, null on failure.
     * Used by the in-bot admin to save uploaded product files / previews
     * (there is no web panel to upload through HTTP anymore).
     */
    public function downloadFile(string $fileId, string $destPath): ?string
    {
        $res = $this->request('getFile', ['file_id' => $fileId]);
        if (empty($res['ok']) || empty($res['result']['file_path'])) {
            return null;
        }
        $filePath = $res['result']['file_path'];
        $fileUrl  = $this->fileBase . $filePath;
        $dir = dirname($destPath);
        if (!is_dir($dir)) {
            @mkdir($dir, 0755, true);
        }
        $fp = @fopen($destPath, 'wb');
        if (!$fp) {
            return null;
        }
        $ch = curl_init($fileUrl);
        curl_setopt_array($ch, $this->curlOptions(true));
        curl_setopt($ch, CURLOPT_FILE, $fp);
        curl_exec($ch);
        $err = curl_error($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        fclose($fp);
        if ($err || $httpCode !== 200 || !filesize($destPath)) {
            @unlink($destPath);
            return null;
        }
        return $destPath;
    }

    /**
     * Get a readable file size for a Telegram file (via getFile).
     */
    public function getFileSize(string $fileId): int
    {
        $res = $this->request('getFile', ['file_id' => $fileId]);
        return $res['result']['file_size'] ?? 0;
    }

    /**
     * Forward a file (by file_id) to a chat — useful to show admins the
     * uploaded receipt without needing a web viewer.
     */
    public function copyFile(int|string $chatId, string $fileId, string $fileType, ?string $caption = null): array
    {
        if ($fileType === 'photo') {
            return $this->sendPhoto($chatId, $fileId, $caption);
        }
        return $this->sendDocument($chatId, $fileId, $caption);
    }

    public function getChatMember(int|string $chatId, int $userId): ?array
    {
        $res = $this->request('getChatMember', ['chat_id' => $chatId, 'user_id' => $userId]);
        return $res['ok'] ? $res['result'] : null;
    }
}
