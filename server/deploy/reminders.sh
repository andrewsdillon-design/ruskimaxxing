#!/usr/bin/env bash
# Daily: email lifters whose Cloud Backup plan renews in 30-45 days (installed by install.sh).
set -euo pipefail
set -a; . /etc/ruskimaxxing-cloud.env; set +a
cd /opt/ruskimaxxing-cloud/app/server
exec runuser -u ruskimaxxing -- /opt/ruskimaxxing-cloud/venv/bin/python -m ruskimaxxing_cloud.reminders
