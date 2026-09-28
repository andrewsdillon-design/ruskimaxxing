#!/usr/bin/env bash
# Manage admin accounts with the service's own settings and user (installed as /usr/local/sbin/ruskimaxxing-admin).
#   sudo ruskimaxxing-admin create-admin you@example.com   # set password + scan the 2FA QR code
#   sudo ruskimaxxing-admin reset-totp you@example.com     # new 2FA code (lost phone)
#   sudo ruskimaxxing-admin demote you@example.com
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo"; exit 1; }
exec systemd-run --quiet --pty --wait --collect \
  -p EnvironmentFile=/etc/ruskimaxxing-cloud.env -p User=ruskimaxxing \
  -p WorkingDirectory=/opt/ruskimaxxing-cloud/app/server \
  /opt/ruskimaxxing-cloud/venv/bin/python -m ruskimaxxing_cloud.admin_cli "$@"
