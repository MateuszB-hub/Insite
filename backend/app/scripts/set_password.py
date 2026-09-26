"""Set a user's password from the command line.

A stopgap until self-service reset exists (see TODO.md). Passwords cannot be
recovered -- they are Argon2id hashes -- so this sets a new one.

The password is read interactively and never appears in shell history, the
process list, or any log:

    .venv/bin/python -m app.scripts.set_password you@example.com

Also clears any failed-login lockout, and revokes every existing session so a
stolen cookie cannot outlive the password change.
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.auth.security import hash_password, password_problems
from app.db.base import SessionLocal
from app.db.models import AuditLog, User, utcnow


def set_password(email: str, password: str) -> int:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email.lower().strip()))
        if user is None:
            print(f"  no account found for {email}")
            return 1
        if user.deleted_at is not None:
            print(f"  account {email} has been erased and cannot be restored")
            return 1

        problems = password_problems(password)
        if problems:
            print("  password " + "; ".join(problems))
            return 1

        user.password_hash = hash_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        user.is_active = True

        revoked = 0
        for session in user.sessions:
            if session.revoked_at is None:
                session.revoked_at = utcnow()
                revoked += 1

        db.add(AuditLog(user_id=user.id, action="password.admin_reset",
                        detail="set via CLI"))
        db.commit()

        print(f"  password updated for {email}")
        print(f"  lockout cleared, {revoked} existing session(s) revoked")
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Set a user's password.")
    parser.add_argument("email")
    parser.add_argument("--stdin", action="store_true",
                        help="read the password from stdin instead of prompting")
    args = parser.parse_args()

    if args.stdin:
        password = sys.stdin.readline().rstrip("\n")
    elif sys.stdin.isatty():
        password = getpass.getpass("  New password (min 12 chars, not echoed): ")
        if password != getpass.getpass("  Confirm: "):
            print("  passwords did not match")
            return 1
    else:
        print("  no terminal available; pipe the password in with --stdin")
        return 1

    return set_password(args.email, password)


if __name__ == "__main__":
    raise SystemExit(main())
