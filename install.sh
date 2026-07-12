#!/usr/bin/env bash
# =====================================================
# File Store Bot - rootless Linux installer
#
# No sudo/root required. Sets up everything under the current
# user's home directory using existing PHP + MySQL/MariaDB.
#
# What it does:
#  - Checks that php-cli and mysql client exist
#  - Creates the database/user via an existing privileged mysql account
#  - Imports database.sql into the new database
#  - Writes includes/config.local.php with your secrets
#  - Marks first admin and optionally starts the bot
#
# Usage:  bash install.sh
# Re-run is safe; it will not overwrite config.local.php unless you confirm.
# =====================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# ---- helpers ----
b()  { printf '\033[1;36m%s\033[0m\n' "$*"; }
g()  { printf '\033[1;32m%s\033[0m\n' "$*"; }
y()  { printf '\033[1;33m%s\033[0m\n' "$*"; }
r()  { printf '\033[1;31m%s\033[0m\n' "$*"; }
ask() {
  local v
  read -rp "$(b "$1") [$2]: " v
  echo "${v:-$2}"
}
ask_secret() {
  local v
  read -rsp "$(b "$1"): " v
  echo
  echo "$v"
}

b "=== File Store Telegram Bot - rootless installer ==="
echo

# =====================================================
# Step 1: Dependency check
# =====================================================
b "[1/6] Checking dependencies..."
if ! command -v php >/dev/null 2>&1; then
  r "PHP CLI not found. Install php-cli, e.g. (ask your sysadmin):"
  echo "  Debian/Ubuntu: sudo apt install php-cli php-mysql php-curl php-mbstring"
  echo "  RHEL/CentOS:   sudo dnf install php-cli php-mysqlnd php-curl php-mbstring"
  exit 1
fi
if ! php -m | grep -qi curl;        then y "Warning: php-curl extension missing - Telegram API needs it."; fi
if ! php -m | grep -qi 'pdo_mysql'; then y "Warning: pdo_mysql extension missing - DB needs it."; fi
if ! php -m | grep -qi mbstring;    then y "Warning: php-mbstring extension missing - Persian text needs it."; fi

if ! command -v mysql >/dev/null 2>&1 && ! command -v mariadb >/dev/null 2>&1; then
  r "MySQL/MariaDB client not found. Install it:"
  echo "  sudo apt install mariadb-clients  (or default-mysql-client)"
  echo "  sudo dnf install mariadb"
  exit 1
fi
MYSQL_CLI="$(command -v mysql 2>/dev/null || command -v mariadb)"
g "PHP: $(php -v | head -1)"
g "MySQL client: $MYSQL_CLI"
echo

# =====================================================
# Step 2: Gather settings
# =====================================================
b "[2/6] Collecting settings..."
DB_NAME="$(ask 'Database name' 'seller_db')"
DB_USER="$(ask 'Database user' "${DB_NAME}_user')"
g "A random DB password will be generated. Set MYSQL_PASS env var to override."
DB_PASS="${MYSQL_PASS:-$(openssl rand -base64 18 | tr -d '=+/' | head -c 24)}"
BOT_TOKEN="$(ask_secret 'Telegram bot token from BotFather')"
ADMIN_ID="$(ask 'Your Telegram numeric ID from userinfobot')"
ADMIN_ID="${ADMIN_ID:-0}"
WORKER_URL="$(ask 'Telegram proxy URL (Deno/Worker) empty for direct' '')"

echo
b "Summary:"
echo "  DB name   : $DB_NAME"
echo "  DB user   : $DB_USER"
echo "  DB pass   : ${DB_PASS:0:3}****"
echo "  Bot token : ${BOT_TOKEN:0:8}****"
echo "  Admin ID  : $ADMIN_ID"
echo "  Worker    : ${WORKER_URL:-(direct)}"
echo
read -rp "$(b 'Proceed? [y/N] ')" ok
[ "${ok:-N}" = "y" ] || { r "Aborted."; exit 1; }

# =====================================================
# Step 3: Create database + user
# =====================================================
b "[3/6] Creating database..."
PRIV_SQL="$(mktemp)"
cat > "$PRIV_SQL" <<SQLEOF
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
SQLEOF

create_db() {
  local user="$1" pass="$2"
  if [ -z "$pass" ]; then
    "$MYSQL_CLI" -u "$user" < "$PRIV_SQL" && return 0
  else
    "$MYSQL_CLI" -u "$user" -p"$pass" < "$PRIV_SQL" && return 0
  fi
  return 1
}

created=false
if create_db "$(whoami)" "" 2>/dev/null; then
  created=true
elif create_db "root" "" 2>/dev/null; then
  created=true
else
  y "Could not create the database automatically."
  echo "A privileged MySQL account is needed (root or a user with CREATE privileges)."
  PRIV_USER="$(ask 'Privileged MySQL user' 'root')"
  PRIV_PASS="$(ask_secret "Password for $PRIV_USER - empty if none")"
  if create_db "$PRIV_USER" "$PRIV_PASS"; then
    created=true
  else
    r "Failed to create database with '$PRIV_USER'."
    echo "You can create it manually, then re-run. SQL to run:"
    cat "$PRIV_SQL"
    rm -f "$PRIV_SQL"
    exit 1
  fi
fi
rm -f "$PRIV_SQL"
[ "$created" = true ] && g "Database '$DB_NAME' and user '$DB_USER' ready."

# =====================================================
# Step 4: Import schema
# =====================================================
b "[4/6] Importing database.sql..."
if "$MYSQL_CLI" -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" < "$DIR/database.sql"; then
  g "Schema imported."
else
  r "Import failed. Check credentials. The DB/user were created; SQL import may need retry."
  exit 1
fi

# =====================================================
# Step 5: Write includes/config.local.php
# =====================================================
b "[5/6] Generating includes/config.local.php..."
LOCAL="$DIR/includes/config.local.php"
skip_cfg=0

if [ -f "$LOCAL" ]; then
  read -rp "$(y "config.local.php exists. Overwrite? [y/N] ")" ov
  [ "${ov:-N}" = "y" ] || { y "Keeping existing config."; skip_cfg=1; }
fi

if [ "$skip_cfg" = "0" ]; then
  SALT="$(openssl rand -hex 16)"
  STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat > "$LOCAL" <<CFGEOF
<?php
// Generated by install.sh on $STAMP. DO NOT COMMIT.
define('DB_HOST_LOCAL', 'localhost');
define('DB_NAME_LOCAL', '$DB_NAME');
define('DB_USER_LOCAL', '$DB_USER');
define('DB_PASS_LOCAL', '$DB_PASS');
define('BOT_TOKEN_LOCAL', '$BOT_TOKEN');
define('ADMIN_IDS_LOCAL', '$ADMIN_ID');
define('DOWNLOAD_TOKEN_SALT_LOCAL', '$SALT');

// Telegram access:
define('TELEGRAM_API_BASE_LOCAL', '$WORKER_URL');
define('PROXY_HOST_LOCAL', '');
define('PROXY_PORT_LOCAL', 0);
define('PROXY_TYPE_LOCAL', 'HTTP');
define('PROXY_USER_LOCAL', '');
define('PROXY_PASS_LOCAL', '');
CFGEOF
  chmod 600 "$LOCAL"
  g "config.local.php written (0600)."
fi

chmod -R u+rwX "$DIR/uploads" 2>/dev/null || true
mkdir -p "$DIR/uploads/files" "$DIR/uploads/previews"

# =====================================================
# Step 6: Mark first admin in DB
# =====================================================
b "[6/6] Marking first admin..."
if [ "$ADMIN_ID" != "0" ]; then
  ADMIN_REF="ADMIN$(openssl rand -hex 3)"
  "$MYSQL_CLI" -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" \
    -e "INSERT INTO users (telegram_id, referral_code, is_admin) VALUES ($ADMIN_ID, '$ADMIN_REF', 1) ON DUPLICATE KEY UPDATE is_admin=1;" \
    2>/dev/null || true
  g "Admin ID $ADMIN_ID flagged (will take effect on /start)."
fi

echo
g "==============================================="
g "  Installation complete!"
g "==============================================="
echo
echo "Start the bot (long polling, no root needed):"
b "  cd $DIR && bash run.sh start"
echo
echo "Check status / logs:"
echo "  bash run.sh status"
echo "  bash run.sh logs"
echo
echo "Stop:"
echo "  bash run.sh stop"
echo
echo "Then open Telegram, send /start to your bot, and /admin to manage everything."
echo
echo "If Telegram is blocked from your server, set TELEGRAM_API_BASE_LOCAL"
echo "to a Deno Deploy proxy URL in:"
echo "  $LOCAL"
echo "Then restart with: bash run.sh restart"
