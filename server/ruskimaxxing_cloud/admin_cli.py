"""Admin bootstrap CLI: create, promote and manage admin accounts for RuskiMaxxing Cloud.

Run with the app's environment loaded (DATABASE_URL etc. - see deploy/*.env) from server/:

    python -m ruskimaxxing_cloud.admin_cli create-admin you@example.com
    python -m ruskimaxxing_cloud.admin_cli reset-totp you@example.com
    python -m ruskimaxxing_cloud.admin_cli demote you@example.com

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
        p.set_defaults(fn=fn)
    args = parser.parse_args(argv)
    args.fn(args.email)


if __name__ == "__main__":
    main()
