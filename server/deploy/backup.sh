#!/usr/bin/env bash
# Nightly database backup. install.sh adds it to root's crontab (03:17 every day).
# Copy /var/backups/ruskimaxxing somewhere OFF this server too (e.g. rclone to cloud storage) -
# a backup on the same disk won't survive the VPS dying.
set -euo pipefail
DIR=/var/backups/ruskimaxxing
KEEP_DAYS=14
mkdir -p "$DIR"
chmod 700 "$DIR"
sudo -u postgres pg_dump --format=custom ruskimaxxing > "$DIR/ruskimaxxing-$(date +%F).dump"
find "$DIR" -name 'ruskimaxxing-*.dump' -mtime +"$KEEP_DAYS" -delete
# Restore: sudo -u postgres pg_restore --clean -d ruskimaxxing /var/backups/ruskimaxxing/ruskimaxxing-YYYY-MM-DD.dump
