<?php
/**
 * Database connection (PDO) with prepared statements.
 */
class Database
{
    private static ?PDO $instance = null;
    private static bool $connecting = false;
    private static bool $logFailed = false;

    public static function conn(): PDO
    {
        if (self::$instance !== null) {
            return self::$instance;
        }
        // Prevent re-entry: if we are already trying to connect, bail out hard.
        if (self::$connecting) {
            throw new RuntimeException('Database connection loop detected');
        }
        self::$connecting = true;

        $dsn = 'mysql:host=' . DB_HOST . ';dbname=' . DB_NAME . ';charset=' . DB_CHARSET;
        $options = [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ];
        try {
            self::$instance = new PDO($dsn, DB_USER, DB_PASS, $options);
            // Align MySQL session with PHP: timezone + safe SQL mode
            self::$instance->exec("SET time_zone = '+03:30'");
            self::$instance->exec("SET sql_mode = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'");
        } catch (PDOException $e) {
            // Write the REAL error to a file so it is never masked by recursion.
            $detail = '[' . date('Y-m-d H:i:s') . '] DB connection failed: '
                . $e->getMessage()
                . ' | DSN=' . $dsn
                . ' | user=' . DB_USER
                . ' | db=' . DB_NAME
                . PHP_EOL;
            @file_put_contents(__DIR__ . '/../error.log', $detail, FILE_APPEND);
            // Show a helpful error and stop.
            if (!headers_sent()) {
                http_response_code(500);
                header('Content-Type: text/plain; charset=utf-8');
            }
            echo 'خطا در اتصال به دیتابیس.' . PHP_EOL
               . 'علت: ' . $e->getMessage() . PHP_EOL
               . 'بررسی کنید:' . PHP_EOL
               . '1) دیتابیس "' . DB_NAME . '" ساخته شده باشد (با bash install.sh).' . PHP_EOL
               . '2) کاربر "' . DB_USER . '" به دیتابیس متصل و دارای ALL PRIVILEGES باشد.' . PHP_EOL
               . '3) رمز دیتابیس در includes/config.local.php درست باشد.' . PHP_EOL
               . '4) فایل database.sql ایمپورت شده باشد.' . PHP_EOL
               . 'جزئیات در error.log ثبت شد.';
            exit(1);
        } finally {
            self::$connecting = false;
        }
        return self::$instance;
    }

    public static function query(string $sql, array $params = []): PDOStatement
    {
        $stmt = self::conn()->prepare($sql);
        $stmt->execute($params);
        return $stmt;
    }

    public static function fetch(string $sql, array $params = [])
    {
        return self::query($sql, $params)->fetch();
    }

    public static function fetchAll(string $sql, array $params = []): array
    {
        return self::query($sql, $params)->fetchAll();
    }

    public static function fetchColumn(string $sql, array $params = [])
    {
        return self::query($sql, $params)->fetchColumn();
    }

    public static function insert(string $table, array $data): int
    {
        $fields = array_keys($data);
        $placeholders = array_map(fn($f) => ':' . $f, $fields);
        $sql = 'INSERT INTO `' . $table . '` (`' . implode('`,`', $fields) . '`)
                VALUES (' . implode(',', $placeholders) . ')';
        self::query($sql, $data);
        return (int) self::conn()->lastInsertId();
    }

    public static function update(string $table, array $data, string $where, array $whereParams = []): int
    {
        $set = [];
        foreach (array_keys($data) as $field) {
            $set[] = '`' . $field . '` = :' . $field;
        }
        $sql = 'UPDATE `' . $table . '` SET ' . implode(',', $set) . ' WHERE ' . $where;
        return self::query($sql, array_merge($data, $whereParams))->rowCount();
    }

    public static function delete(string $table, string $where, array $params = []): int
    {
        return self::query('DELETE FROM `' . $table . '` WHERE ' . $where, $params)->rowCount();
    }

    public static function logError(string $message, string $context = ''): void
    {
        if (!ENABLE_LOGGING) {
            return;
        }
        // Prevent recursion: if we are still mid-connection or a previous log
        // attempt already failed, write straight to file and stop.
        if (self::$connecting || self::$instance === null || self::$logFailed) {
            $line = '[' . date('Y-m-d H:i:s') . '] ' . $message . ' | ' . $context . PHP_EOL;
            @file_put_contents(__DIR__ . '/../error.log', $line, FILE_APPEND);
            return;
        }
        try {
            self::insert('logs', [
                'level'   => 'error',
                'message' => mb_substr($message, 0, 5000),
                'context' => mb_substr($context, 0, 5000),
            ]);
        } catch (Throwable $e) {
            self::$logFailed = true;
            $line = '[' . date('Y-m-d H:i:s') . '] ' . $message . ' | ' . $context . PHP_EOL;
            @file_put_contents(__DIR__ . '/../error.log', $line, FILE_APPEND);
        }
    }
}
