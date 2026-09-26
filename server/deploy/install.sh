#!/usr/bin/env bash
# One-command install / update of RuskiMaxxing Cloud on Ubuntu or Debian, next to any sites already
# on the server. Safe to re-run (it updates the code and keeps your database and settings).
#
#   sudo bash install.sh api.your-domain.com you@your-domain.com
#
# What it does: installs PostgreSQL + nginx + certbot if missing, creates a 'ruskimaxxing' system user,
# database and random password, installs the app in /opt/ruskimaxxing-cloud, runs it on 127.0.0.1:8110
# with systemd, adds an nginx server block for YOUR API DOMAIN ONLY, tests nginx before reloading,
# gets an HTTPS certificate for that domain, and schedules nightly backups.
set -euo pipefail
DOMAIN=${1:?usage: sudo bash install.sh api.your-domain.com you@your-domain.com}
EMAIL=${2:?usage: sudo bash install.sh api.your-domain.com you@your-domain.com}
REPO=${REPO:-https://github.com/andrewsdillon-design/ruskimaxxing.git}
BASE=/opt/ruskimaxxing-cloud
ENV=/etc/ruskimaxxing-cloud.env
HERE=$(cd "$(dirname "$0")" && pwd)

[ "$(id -u)" = 0 ] || { echo "Run with sudo"; exit 1; }

echo "==> Checking ports (nothing already running is changed)"
for port in 80 443; do
  owner=$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'users:(("[^"]*' | head -1 | cut -d'"' -f2 || true)
  if [ -n "$owner" ] && [ "$owner" != nginx ]; then
    echo "Port $port is already used by '$owner' (not nginx). This installer uses nginx on 80/443."
    echo "If that's Caddy, Apache, Traefik or a Docker container, point it at 127.0.0.1:8110 instead -"
    echo "see server/README.md 'Running it next to the site you already host'. Nothing was changed."
    exit 1
  fi
done
if ss -ltnH "sport = :8110" 2>/dev/null | grep -q . && ! systemctl is-active --quiet ruskimaxxing-cloud; then
  echo "Port 8110 is taken by something else; change it in ruskimaxxing-cloud.service and ruskimaxxing-proxy.conf."
  exit 1
fi

echo "==> Packages"
apt-get update -q
apt-get install -y -q python3 python3-venv postgresql nginx certbot python3-certbot-nginx git

echo "==> System user and code"
id ruskimaxxing >/dev/null 2>&1 || useradd --system --home "$BASE" --shell /usr/sbin/nologin ruskimaxxing
mkdir -p "$BASE"
if [ -d "$BASE/app/.git" ]; then git -c safe.directory="$BASE/app" -C "$BASE/app" pull -q; else git clone -q --depth 1 "$REPO" "$BASE/app"; fi
python3 -m venv "$BASE/venv"
"$BASE/venv/bin/pip" install -q --upgrade pip
"$BASE/venv/bin/pip" install -q -r "$BASE/app/server/requirements.txt"
chown -R ruskimaxxing:ruskimaxxing "$BASE"

echo "==> Database"
if [ ! -f "$ENV" ]; then
  DBPASS=$(openssl rand -hex 24)
  sudo -u postgres psql -q -c "CREATE USER ruskimaxxing WITH PASSWORD '$DBPASS';" || true
  sudo -u postgres psql -q -c "CREATE DATABASE ruskimaxxing OWNER ruskimaxxing;" || true
  sed -e "s#CHANGE_ME#$DBPASS#" -e "s#https://api.example.com#https://$DOMAIN#" -e "s#you@example.com#$EMAIL#" \
      "$HERE/env.example" > "$ENV"
  chmod 600 "$ENV"
  echo "    wrote $ENV (add SMTP settings there to enable password-reset emails)"
fi

echo "==> Service"
cp "$HERE/ruskimaxxing-cloud.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ruskimaxxing-cloud
systemctl restart ruskimaxxing-cloud

echo "==> nginx (new server block for $DOMAIN only)"
cp "$HERE/ruskimaxxing-proxy.conf" /etc/nginx/snippets/
sed "s/API_DOMAIN/$DOMAIN/" "$HERE/nginx-ruskimaxxing-cloud.conf" > /etc/nginx/sites-available/ruskimaxxing-cloud
ln -sf /etc/nginx/sites-available/ruskimaxxing-cloud /etc/nginx/sites-enabled/ruskimaxxing-cloud
nginx -t   # stops here, before touching the running server, if anything is wrong
systemctl reload nginx

echo "==> HTTPS certificate for $DOMAIN (your other site's certificate is not touched)"
certbot --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos --non-interactive --redirect || \
  echo "    certbot failed - check that $DOMAIN's DNS A record points at this server, then re-run"

echo "==> Nightly backups"
install -m 700 "$HERE/backup.sh" /usr/local/sbin/ruskimaxxing-backup
( crontab -l 2>/dev/null | grep -v ruskimaxxing-backup; echo "17 3 * * * /usr/local/sbin/ruskimaxxing-backup" ) | crontab -

echo "==> Daily renewal-reminder emails (required before yearly auto-renewals)"
install -m 700 "$HERE/reminders.sh" /usr/local/sbin/ruskimaxxing-reminders
( crontab -l 2>/dev/null | grep -v ruskimaxxing-reminders; \
  echo "41 15 * * * /usr/local/sbin/ruskimaxxing-reminders >> /var/log/ruskimaxxing-reminders.log 2>&1" ) | crontab -

sleep 2
curl -fsS "http://127.0.0.1:8110/health" >/dev/null && echo "==> Done. Server is up: https://$DOMAIN/health" \
  || { echo "Service didn't answer - see: journalctl -u ruskimaxxing-cloud -n 50"; exit 1; }
echo "    In the apps: Setup / Start tab -> Cloud backup -> server address https://$DOMAIN"
