"""Daily job: email plans that renew in 30-45 days (run by cron - see deploy/reminders.sh)."""

import os
import sys

os.environ["RUSKIMAXXING_CLOUD_AUTOSTART"] = "0"

from ruskimaxxing_cloud.main import billing_on, mail_on, make_engine, send_renewal_reminders  # noqa: E402


def main() -> int:
    if not billing_on():
        return 0
    if not mail_on():
        print("SMTP_HOST isn't set: renewal reminders can't be sent. Fill in the SMTP settings in "
              "/etc/ruskimaxxing-cloud.env - several U.S. states require these reminders.", file=sys.stderr)
        return 1
    print(f"Sent {send_renewal_reminders(make_engine())} renewal reminder(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
