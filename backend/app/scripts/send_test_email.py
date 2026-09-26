"""Send one test email through the configured provider.

    python -m app.scripts.send_test_email you@example.com

Run this after setting EMAIL_PROVIDER=smtp and the SMTP_* values, before
relying on password resets. Unlike the reset route, it reports failures,
because here nobody is probing for account existence.
"""

import sys

from dotenv import load_dotenv

# Production email settings live in .env.production (see serve.sh); load it
# first so they win, since load_dotenv never overrides a variable once set.
load_dotenv(".env.production")
load_dotenv()

from app.auth import email  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    to = sys.argv[1]
    print(f"provider: {email.EMAIL_PROVIDER}  from: {email.EMAIL_FROM}")
    if email.EMAIL_PROVIDER == "smtp":
        print(f"server:   {email.SMTP_HOST}:{email.SMTP_PORT}")
    try:
        email.send_email(
            to=to,
            subject="Insite test email",
            body="If you can read this, Insite can deliver password reset emails.",
        )
    except email.EmailError as exc:
        print(f"FAILED: {exc}  (cause: {exc.__cause__!r})")
        return 1
    print("sent." if email.EMAIL_PROVIDER == "smtp" else "printed above (console provider).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
