#!/usr/bin/env bash
# Update RuskiMaxxing Cloud to the latest main branch and restart it. Installed as
# /usr/local/sbin/ruskimaxxing-deploy by install.sh, which also saves the domain and email it needs in
# /etc/ruskimaxxing-cloud.deploy.
#
#   sudo ruskimaxxing-deploy
#
# The "Deploy server" GitHub workflow runs this over SSH (DEPLOY_SERVER.bat sets that up). GitHub's
# SSH key is locked to this one command, so it can't do anything else on the server.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo"; exit 1; }
CONF=/etc/ruskimaxxing-cloud.deploy
APP=/opt/ruskimaxxing-cloud/app
[ -f "$CONF" ] || { echo "Missing $CONF: run install.sh once by hand (see server/README.md)"; exit 1; }
# shellcheck source=/dev/null
. "$CONF"   # DOMAIN=... EMAIL=...

echo "==> Getting the latest code"
git -c safe.directory="$APP" -C "$APP" pull -q --ff-only
bash "$APP/server/deploy/install.sh" "$DOMAIN" "$EMAIL"
echo "DEPLOYED_COMMIT=$(git -c safe.directory="$APP" -C "$APP" rev-parse HEAD)"
echo "DEPLOYED_DOMAIN=$DOMAIN"
