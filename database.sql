-- =====================================================
-- File Store Telegram Bot - Database Schema
-- Import this file in phpMyAdmin (cPanel) on MySQL 5.7+/8+
-- =====================================================
SET NAMES utf8mb4;
SET time_zone = '+03:30';
SET FOREIGN_KEY_CHECKS = 0;
SET sql_mode = '';

-- ---------------- Admins ----------------
CREATE TABLE IF NOT EXISTS `admins` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(50) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Users (Telegram) ----------------
CREATE TABLE IF NOT EXISTS `users` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `telegram_id` BIGINT UNSIGNED NOT NULL,
  `username` VARCHAR(100) DEFAULT NULL,
  `first_name` VARCHAR(100) DEFAULT NULL,
  `last_name` VARCHAR(100) DEFAULT NULL,
  `referral_code` VARCHAR(20) NOT NULL,
  `referred_by` INT UNSIGNED DEFAULT NULL,
  `referral_balance` BIGINT NOT NULL DEFAULT 0,
  `is_blocked` TINYINT(1) NOT NULL DEFAULT 0,
  `is_admin` TINYINT(1) NOT NULL DEFAULT 0,
  `state` VARCHAR(100) DEFAULT NULL,
  `state_data` VARCHAR(255) DEFAULT NULL,
  `last_activity` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `telegram_id` (`telegram_id`),
  UNIQUE KEY `referral_code` (`referral_code`),
  KEY `referred_by` (`referred_by`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Categories ----------------
CREATE TABLE IF NOT EXISTS `categories` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(150) NOT NULL,
  `icon` VARCHAR(50) DEFAULT NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Products ----------------
CREATE TABLE IF NOT EXISTS `products` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(200) NOT NULL,
  `description` TEXT,
  `price` BIGINT NOT NULL DEFAULT 0,
  `category_id` INT UNSIGNED DEFAULT NULL,
  `preview_image` VARCHAR(255) DEFAULT NULL,
  `file_path` VARCHAR(255) DEFAULT NULL,
  `file_name` VARCHAR(255) DEFAULT NULL,
  `file_size` BIGINT DEFAULT 0,
  `tags` VARCHAR(500) DEFAULT NULL,
  `download_count` INT NOT NULL DEFAULT 0,
  `download_limit` INT NOT NULL DEFAULT 0,
  `is_vip` TINYINT(1) NOT NULL DEFAULT 0,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `category_id` (`category_id`),
  KEY `is_active` (`is_active`),
  FULLTEXT KEY `search_idx` (`name`, `description`, `tags`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Product gallery images ----------------
CREATE TABLE IF NOT EXISTS `product_images` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `product_id` INT UNSIGNED NOT NULL,
  `image_path` VARCHAR(255) NOT NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `product_id` (`product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Required channels ----------------
CREATE TABLE IF NOT EXISTS `channels` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `channel_username` VARCHAR(100) NOT NULL,
  `channel_id` VARCHAR(100) DEFAULT NULL,
  `title` VARCHAR(150) DEFAULT NULL,
  `invite_link` VARCHAR(255) DEFAULT NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Bank cards ----------------
CREATE TABLE IF NOT EXISTS `cards` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `card_number` VARCHAR(32) NOT NULL,
  `holder_name` VARCHAR(100) NOT NULL,
  `bank_name` VARCHAR(100) DEFAULT NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `sort_order` INT NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Orders ----------------
CREATE TABLE IF NOT EXISTS `orders` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `order_code` VARCHAR(20) NOT NULL,
  `user_id` INT UNSIGNED NOT NULL,
  `product_id` INT UNSIGNED NOT NULL,
  `price` BIGINT NOT NULL DEFAULT 0,
  `status` ENUM('pending','approved','rejected','need_info') NOT NULL DEFAULT 'pending',
  `receipt_file_id` VARCHAR(255) DEFAULT NULL,
  `receipt_file_type` VARCHAR(20) DEFAULT NULL,
  `receipt_message` TEXT,
  `admin_note` TEXT,
  `downloaded` INT NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `order_code` (`order_code`),
  KEY `user_id` (`user_id`),
  KEY `product_id` (`product_id`),
  KEY `status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Downloads log ----------------
CREATE TABLE IF NOT EXISTS `downloads` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `order_id` INT UNSIGNED DEFAULT NULL,
  `user_id` INT UNSIGNED NOT NULL,
  `product_id` INT UNSIGNED NOT NULL,
  `ip` VARCHAR(45) DEFAULT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  KEY `product_id` (`product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Broadcasts ----------------
CREATE TABLE IF NOT EXISTS `broadcasts` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `type` ENUM('text','photo','document') NOT NULL DEFAULT 'text',
  `content` MEDIUMTEXT,
  `file_id` VARCHAR(255) DEFAULT NULL,
  `caption` TEXT,
  `total` INT NOT NULL DEFAULT 0,
  `sent` INT NOT NULL DEFAULT 0,
  `failed` INT NOT NULL DEFAULT 0,
  `status` ENUM('pending','running','done') NOT NULL DEFAULT 'pending',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Settings (key/value) ----------------
CREATE TABLE IF NOT EXISTS `settings` (
  `key_name` VARCHAR(100) NOT NULL,
  `value` MEDIUMTEXT,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`key_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Error logs ----------------
CREATE TABLE IF NOT EXISTS `logs` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `level` VARCHAR(20) NOT NULL DEFAULT 'error',
  `message` TEXT NOT NULL,
  `context` TEXT,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- Default admin ----------------
-- The admin account is created/updated by install.php with a real bcrypt hash.
-- Run install.php in your browser after importing this file.

-- ---------------- Default settings ----------------
INSERT INTO `settings` (`key_name`, `value`) VALUES
('welcome_text', 'سلام به فروشگاه فایل ما خوش آمدید!\nبرای ادامه روی /start بزنید و یا دکمه‌های منو را استفاده کنید.'),
('rules_text', 'قوانین فروشگاه:\n1. پس از پرداخت رسید را ارسال کنید.\n2. فایل‌ها فقط از طریق ربات قابل دانلود است.\n3. اشتراک‌گذاری فایل‌ها ممنوع است.'),
('support_text', 'برای پشتیبانی به آیدی زیر پیام دهید:\n@your_support'),
('payment_text', 'نام محصول: {product_name}\nقیمت: {price} تومان\n\nلطفاً مبلغ فوق را به کارت زیر واریز نمایید:\n\n{card_number}\n{holder_name}\n\nپس از پرداخت، رسید واریز را ارسال کنید.'),
('referral_reward', '0'),
('referral_text', 'با دعوت دوستان خود از لینک زیر، پاداش دریافت کنید!\n\nلینک شما:\n{referral_link}'),
('store_name', 'فروشگاه فایل'),
('footer', 'فروشگاه فایل'),
('admin_notify_id', '0'),
('per_page', '8');

SET FOREIGN_KEY_CHECKS = 1;
