"""Admin bootstrap CLI: create, promote and manage admin accounts for RuskiMaxxing Cloud.

Run with the app's environment loaded (DATABASE_URL etc. - see deploy/*.env) from server/:

    python -m ruskimaxxing_cloud.admin_cli create-admin you@example.com
    python -m ruskimaxxing_cloud.admin_cli reset-totp you@example.com
    python -m ruskimaxxing_cloud.admin_cli demote you@example.com
    python -m ruskimaxxing_cloud.admin_cli report --days 30

See server/README.md "Admin" for the exact command to run against a live install.
"""

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import totp
from .main import User, make_engine, ph

MIN_PASSWORD = 12


def _show_secret(email: str, secret: str) -> None:
    uri = totp.otpauth_uri(email, secret)
    print("\nScan this into your authenticator app (Google Authenticator, 1Password, Authy, ...):\n")
    try:
        import segno
        segno.make(uri).terminal(compact=True)
    except Exception as e:  # pragma: no cover - terminal/segno quirks vary by platform
        print(f"(couldn't draw a QR code in this terminal: {e})")
    print(f"\nCan't scan it? Enter this manually:\n  Secret: {secret}\n  Type: Time-based, 6 digits, 30 seconds")
    print(f"\notpauth URI: {uri}\n")


def _read_new_password() -> str:
    while True:
        pw1 = getpass.getpass(f"New password ({MIN_PASSWORD}+ characters): ")
        if len(pw1) < MIN_PASSWORD:
            print(f"Too short - use at least {MIN_PASSWORD} characters.")
            continue
        pw2 = getpass.getpass("Confirm password: ")
        if pw1 != pw2:
            print("Passwords didn't match - try again.")
            continue
        return pw1


def create_admin(email: str) -> None:
    email = email.strip().lower()
    engine = make_engine()
    with Session(engine) as s:
        user = s.scalar(select(User).where(User.email == email))
        if user is None:
            password = _read_new_password()
            user = User(email=email, password_hash=ph.hash(password), is_admin=True)
            s.add(user)
            print(f"Created new admin account for {email}.")
        else:
            user.is_admin = True
            print(f"Promoted existing account {email} to admin.")
        secret = totp.new_secret()
        user.totp_secret, user.totp_last_step = secret, None
        s.commit()
        _show_secret(email, secret)


def reset_totp(email: str) -> None:
    email = email.strip().lower()
    engine = make_engine()
    with Session(engine) as s:
        user = s.scalar(select(User).where(User.email == email))
        if not user or not user.is_admin:
            print(f"No admin account for {email}.", file=sys.stderr)
            sys.exit(1)
        secret = totp.new_secret()
        user.totp_secret, user.totp_last_step = secret, None
        s.commit()
        print(f"Two-factor code reset for {email}.")
        _show_secret(email, secret)


def demote(email: str) -> None:
    email = email.strip().lower()
    engine = make_engine()
    with Session(engine) as s:
        user = s.scalar(select(User).where(User.email == email))
        if not user:
            print(f"No account for {email}.", file=sys.stderr)
            sys.exit(1)
        user.is_admin, user.totp_secret, user.totp_last_step = False, None, None
        from .main import AdminSession
        from sqlalchemy import delete
        s.execute(delete(AdminSession).where(AdminSession.user_id == user.id))
        s.commit()
        print(f"{email} is no longer an admin (signed out of /admin everywhere).")


def report(days: int = 30) -> None:
    """Accounts only: sign-ups, syncs and plans. Training data stays private unless a lifter gives coaching consent."""
    from datetime import timedelta

    from .main import ProgramPurchase, utcnow

    since = utcnow() - timedelta(days=days)
    with Session(make_engine()) as s:
        users = list(s.scalars(select(User).order_by(User.created.desc())))
        new = [u for u in users if u.created and u.created >= since]
        synced = [u for u in users if u.last_sync_at and u.last_sync_at >= since]
        bought = list(s.scalars(select(ProgramPurchase).where(ProgramPurchase.purchased_at >= since,
                                                              ProgramPurchase.refunded_at.is_(None))))
        paying = [u for u in users if u.plan_status in ("active", "trialing")]
        print(f"RUSKIMAXXING APP (last {days} days)")
        print("=" * 60)
        print(f"Accounts: {len(users)} total, {len(new)} new, {len(synced)} synced the app, "
              f"{len(paying)} on a paid plan, {len(bought)} program purchases")
        print(f"\nNew sign-ups ({len(new)}):")
        for u in new:
            seen = u.last_sync_at.date().isoformat() if u.last_sync_at else "hasn't synced yet"
            plan = f", plan: {u.plan_status}" if u.plan_status else ""
            print(f"  - {u.email}, joined {u.created.date().isoformat()}, last sync: {seen}{plan}")
        if not new:
            print("  (none)")
        quiet = [u for u in new if not u.last_sync_at]
        if quiet:
            print(f"\nSigned up but never synced the app ({len(quiet)}) - they may need help getting started:")
            for u in quiet:
                print(f"  - {u.email}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m ruskimaxxing_cloud.admin_cli",
                                     description="Manage RuskiMaxxing Cloud admin accounts.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn, help_text in (
        ("create-admin", create_admin, "create (or promote) an admin account and set up two-factor login"),
        ("reset-totp", reset_totp, "generate a new two-factor secret for an existing admin"),
        ("demote", demote, "remove admin access from an account"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("email")
        p.set_defaults(fn=lambda a, fn=fn: fn(a.email))
    p = sub.add_parser("report", help="accounts: new sign-ups, who synced, paid plans")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(fn=lambda a: report(a.days))
    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
