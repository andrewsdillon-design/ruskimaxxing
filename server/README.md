# RuskiMaxxing Cloud

Optional **cloud backup** for the RuskiMaxxing and RuskiMaxxing Supertotal apps (desktop and phone).
People create an account in the app; their training log, PRs, bodyweight, body fat and settings back
up to **your VPS**. If they lose their phone, they log in on the new one and everything comes back.

- **One server for both apps.** Each record is tagged `standard` or `supertotal`.
- **Offline first.** The apps keep their own local database and work with no signal. They send what
  changed when online. If two devices edit the same thing, the newest edit wins.
- **Stack:** Python **FastAPI** + **SQLAlchemy** (the Python counterpart of Prisma) + **PostgreSQL**,
  run by **uvicorn** under **systemd**, behind **nginx**.
- **Security:**
  - Passwords are hashed with Argon2, and login tokens are stored hashed.
  - HTTPS only via Let's Encrypt, with login attempts rate-limited in nginx.
  - The server listens on `127.0.0.1` only.

## Running it next to the site you already host

nginx picks the site by **domain name**. Your existing site keeps its own `server { server_name ... }`
block, and this one gets its own block for `api.your-domain.com`. The API itself runs on a private local
port (`127.0.0.1:8100`) that nothing outside the VPS can reach. So:

```
                         ┌── server_name your-site.com      → your existing site (unchanged)
internet → nginx :443 ───┤
                         └── server_name api.your-domain.com → 127.0.0.1:8100 (RuskiMaxxing Cloud)
```

Rules that keep both sites safe:
1. Only nginx listens on ports 80/443. If your other site is an app too, give it a different local port.
2. Each site has its own file in `/etc/nginx/sites-available/`. The installer only adds `ruskimaxxing-cloud`.
3. Always run `nginx -t` before `systemctl reload nginx`. The installer does this and stops if the test fails.
4. Certificates are per domain. `certbot --nginx -d api.your-domain.com` doesn't touch your other certificate.
5. If your server uses **Apache** or **Caddy** instead of nginx, the idea is the same (a VirtualHost or site
   block that reverse-proxies to `127.0.0.1:8100`). Ask and I'll write that config.

## Install (Ubuntu / Debian VPS)

1. **DNS:** add an `A` record `api.your-domain.com → your VPS IP`, and `AAAA` too if you use IPv6.
   Wait until `ping api.your-domain.com` shows your IP.
2. **Run the installer** (it's safe to re-run, and later runs update the code):
   ```bash
   git clone --depth 1 https://github.com/andrewsdillon-design/ruskimaxxing.git
   sudo bash ruskimaxxing/server/deploy/install.sh api.your-domain.com you@your-domain.com
   ```
   It installs PostgreSQL / nginx / certbot if missing, creates a `ruskimaxxing` system user and database
   with a random password, runs the API with systemd, adds the nginx site, gets the HTTPS certificate and
   schedules nightly backups.
3. **Check:** open `https://api.your-domain.com/health`. It should show `{"ok":true}`.
4. **Point the apps at it:** in the app go to **Start / Setup → Cloud backup → Server:**
   `https://api.your-domain.com`. To pre-fill it for everyone, set `DEFAULT_SERVER` in
   `src/ruskimaxxing/sync.py` and publish a new release.

### Password-reset emails
Edit `/etc/ruskimaxxing-cloud.env` and fill in `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` and `MAIL_FROM`
from any email provider (Brevo, Mailgun, Postmark, Amazon SES, your own mail server). Then run
`sudo systemctl restart ruskimaxxing-cloud`. Without SMTP settings, "Forgot password" doesn't send anything.

### Backups
`/usr/local/sbin/ruskimaxxing-backup` runs nightly and keeps 14 days in `/var/backups/ruskimaxxing`.
**Also copy that folder off the VPS** (for example with `rclone` to cloud storage). Restore with:
`sudo -u postgres pg_restore --clean -d ruskimaxxing /var/backups/ruskimaxxing/ruskimaxxing-YYYY-MM-DD.dump`

### Everyday commands
```bash
sudo systemctl status ruskimaxxing-cloud        # is it running?
sudo journalctl -u ruskimaxxing-cloud -n 100    # logs
sudo bash /opt/ruskimaxxing-cloud/app/server/deploy/install.sh api.your-domain.com you@your-domain.com  # update
```

## Before you launch: privacy and app stores
- Bodyweight and body fat are **health data**. Review and edit the template privacy page at
  `https://api.your-domain.com/privacy` (the text is in `ruskimaxxing_cloud/main.py`), and set
  `CONTACT_EMAIL`. It's a starting point, not legal advice. If you'll have EU or UK users, GDPR applies.
- Apple and Google both require a privacy policy link for apps with accounts. Apple also requires
  in-app account deletion. That's built in: **Cloud backup → Delete account** removes the account and every
  backup at once.

## API (for reference)
| Method | Path | |
|---|---|---|
| POST | `/api/register`, `/api/login` | `{email, password}` → `{token, email}` |
| POST | `/api/logout` | ends this device's session |
| GET | `/api/me` | account email and record counts |
| POST | `/api/sync` | `{edition, since, changes[]}` → `{changes[], seq}` (newest edit wins) |
| DELETE | `/api/account` | `{password}`, deletes the account and all data |
| POST | `/api/password-reset` | emails a one-hour reset link (`/reset?token=…`) |
| GET | `/health`, `/privacy` | health check, privacy policy |

## Develop / test locally
```bash
pip install -r server/requirements.txt
cd server && uvicorn ruskimaxxing_cloud.main:app --reload   # uses a local SQLite file
pytest server/tests ../tests/test_sync.py                   # includes full two-device sync tests
```
