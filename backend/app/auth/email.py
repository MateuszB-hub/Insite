"""Outbound email, pluggable by provider.

  console -- writes the message to stdout. Default. No account, no network,
             so the reset flow is fully testable today.
  smtp    -- any SMTP server, including Resend/Postmark/SES SMTP endpoints.

Deliberately NOT routed through `logging`: the redaction filter scrubs
`token=` from log records (correctly), which would make the dev console
sender useless. Console output goes straight to stdout instead.
"""

import os
import smtplib
import sys
from email.message import EmailMessage

EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "console").strip().lower()
EMAIL_FROM = os.getenv("EMAIL_FROM", "Insite <no-reply@insite.local>")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}


class EmailError(RuntimeError):
    """Delivery failed."""


def send_email(to: str, subject: str, body: str) -> None:
    if EMAIL_PROVIDER == "smtp":
        _send_smtp(to, subject, body)
    else:
        _send_console(to, subject, body)


def _send_console(to: str, subject: str, body: str) -> None:
    print(
        "\n" + "=" * 68
        + f"\n  EMAIL (console provider -- not actually sent)"
        + f"\n  To:      {to}"
        + f"\n  Subject: {subject}\n"
        + "-" * 68 + f"\n{body}\n" + "=" * 68 + "\n",
        file=sys.stdout,
        flush=True,
    )


def _send_smtp(to: str, subject: str, body: str) -> None:
    if not SMTP_HOST:
        raise EmailError("EMAIL_PROVIDER=smtp but SMTP_HOST is not set")

    message = EmailMessage()
    message["From"] = EMAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        # 465 is implicit TLS (the connection is encrypted from the first
        # byte); 587 starts plain and upgrades with STARTTLS. Resend,
        # Postmark and SES accept both.
        if SMTP_PORT == 465:
            server_cm = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
        else:
            server_cm = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)
        with server_cm as server:
            if SMTP_STARTTLS and SMTP_PORT != 465:
                server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    except Exception as exc:
        # Never let the provider's message reach the caller: it can contain
        # the recipient address and, on some servers, credentials.
        raise EmailError(f"SMTP delivery failed ({type(exc).__name__})") from exc
