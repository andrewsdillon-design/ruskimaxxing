#!/usr/bin/env bash
# One-time: let the "Deploy server" GitHub workflow update this server. DEPLOY_SERVER.bat runs this
# for you over SSH; you can also run it by hand:
#
#   sudo bash enable_github_deploy.sh LOGIN_USER api.your-domain.com you@your-domain.com 'ssh-ed25519 AAAA...'
#
# It deploys the latest version right away (install.sh, which also installs /usr/local/sbin/ruskimaxxing-deploy),
# then adds GitHub's public key to LOGIN_USER's authorized_keys, locked with restrict,command= so that key
# can only run ruskimaxxing-deploy: no shell, no port forwarding, nothing else. For a non-root LOGIN_USER it
# adds a sudoers rule for that one command. Re-running replaces the old GitHub key.
set -euo pipefail
LOGIN_USER=${1:-} DOMAIN=${2:-} EMAIL=${3:-} PUBKEY=${4:-}
usage="usage: sudo bash enable_github_deploy.sh LOGIN_USER api.your-domain.com you@your-domain.com 'ssh-ed25519 AAAA...'"
[[ $LOGIN_USER =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "Bad login user. $usage"; exit 2; }
[[ $DOMAIN =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || { echo "Bad domain. $usage"; exit 2; }
[[ $EMAIL =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]] || { echo "Bad email. $usage"; exit 2; }
[[ $PUBKEY =~ ^ssh-ed25519\ ([A-Za-z0-9+/]+=*)(\ .*)?$ ]] || { echo "Bad public key. $usage"; exit 2; }
KEYDATA=${BASH_REMATCH[1]}
[ "$(id -u)" = 0 ] || { echo "Run with sudo"; exit 1; }
HOME_DIR=$(getent passwd "$LOGIN_USER" | cut -d: -f6)
[ -n "$HOME_DIR" ] || { echo "No user called $LOGIN_USER on this server"; exit 1; }
APP=/opt/ruskimaxxing-cloud/app
[ -d "$APP/.git" ] || { echo "RuskiMaxxing Cloud isn't installed here yet: install it first (server/README.md)"; exit 1; }

echo "==> Deploying the latest version now"
git -c safe.directory="$APP" -C "$APP" pull -q --ff-only
bash "$APP/server/deploy/install.sh" "$DOMAIN" "$EMAIL"

echo "==> Letting GitHub run ruskimaxxing-deploy (and nothing else) as $LOGIN_USER"
if [ "$LOGIN_USER" = root ]; then
  CMD=/usr/local/sbin/ruskimaxxing-deploy
else
  CMD="sudo -n /usr/local/sbin/ruskimaxxing-deploy"
  rule=/etc/sudoers.d/ruskimaxxing-deploy
  echo "$LOGIN_USER ALL=(root) NOPASSWD: /usr/local/sbin/ruskimaxxing-deploy" > "$rule.tmp"
  chmod 440 "$rule.tmp"
  visudo -cqf "$rule.tmp" && mv "$rule.tmp" "$rule"
fi
SSH_DIR="$HOME_DIR/.ssh"
AUTH="$SSH_DIR/authorized_keys"
install -d -m 700 -o "$LOGIN_USER" -g "$(id -gn "$LOGIN_USER")" "$SSH_DIR"
touch "$AUTH"
{ grep -v ' ruskimaxxing-github-deploy$' "$AUTH" || true
  echo "restrict,command=\"$CMD\" ssh-ed25519 $KEYDATA ruskimaxxing-github-deploy"; } > "$AUTH.tmp"
mv "$AUTH.tmp" "$AUTH"
chown "$LOGIN_USER:$(id -gn "$LOGIN_USER")" "$AUTH"
chmod 600 "$AUTH"
echo "==> Done. GitHub can now deploy this server (Actions -> Deploy server, or DEPLOY_SERVER.bat)."
