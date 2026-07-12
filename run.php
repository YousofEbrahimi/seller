#!/usr/bin/env php
<?php
/**
 * Long-polling bot runner.
 *
 * Usage on a Linux VPS (no root needed):
 *   php run.php
 *
 * Or as a background service (nohup / systemd-user):
 *   nohup php run.php >> bot.log 2>&1 &
 *
 * This loop calls getUpdates() and feeds each update to the Bot class.
 * It is designed to run forever and recover from transient Telegram errors.
 */

require __DIR__ . '/config.php';
require __DIR__ . '/includes/db.php';
require __DIR__ . '/includes/telegram.php';
require __DIR__ . '/includes/helpers.php';
require __DIR__ . '/includes/bot.php';

// Make sure no leftover webhook blocks getUpdates.
$bot = new Telegram(BOT_TOKEN);
$whInfo = $bot->request('getWebhookInfo');
if (!empty($whInfo['result']['url'])) {
    fwrite(STDERR, "A webhook is still set; removing it so long polling works…\n");
    $bot->deleteWebhook();
}

fwrite(STDERR, "Bot started in long-polling mode.\n");
Database::logError('Bot started (long polling)', '');

$offset = 0;
$emptyLoops = 0;

while (true) {
    try {
        $res = $bot->getUpdates($offset, (int) (defined('POLL_LIMIT') ? POLL_LIMIT : 50), (int) (defined('POLL_TIMEOUT') ? POLL_TIMEOUT : 30));
    } catch (Throwable $e) {
        // Should not happen (request() catches internally) but keep the loop alive.
        fwrite(STDERR, '[' . date('c') . "] getUpdates threw: " . $e->getMessage() . "\n");
        sleep(5);
        continue;
    }

    if (empty($res['ok'])) {
        $desc = $res['description'] ?? json_encode($res);
        fwrite(STDERR, '[' . date('c') . "] getUpdates failed: " . $desc . "\n");
        Database::logError('getUpdates failed', $desc);
        // Backoff on repeated failures to avoid hammering Telegram.
        $emptyLoops++;
        sleep(min(30, $emptyLoops * 3));
        continue;
    }

    $updates = $res['result'] ?? [];
    if ($updates) {
        $emptyLoops = 0;
    } else {
        // No updates: light sleep so we don't busy-loop when POLL_TIMEOUT is 0.
        if ((int) (defined('POLL_TIMEOUT') ? POLL_TIMEOUT : 30) === 0) {
            usleep(300000); // 0.3s
        }
        continue;
    }

    foreach ($updates as $update) {
        // Advance offset past this update so Telegram acks (drops) it.
        $updId = $update['update_id'] ?? 0;
        if ($updId >= $offset) {
            $offset = $updId + 1;
        }

        try {
            (new Bot($bot, $update))->run();
        } catch (Throwable $e) {
            Database::logError('Bot error (poll): ' . $e->getMessage(), $e->getTraceAsString());
            fwrite(STDERR, '[' . date('c') . "] Bot error: " . $e->getMessage() . "\n");
        }
    }
}
