"""Redaction applied to every log record.

A filter on the root handler rather than discipline at each call site: the
one `logger.info(f"...{user.email}")` somebody adds in six months is exactly
the case that matters, and it will be caught here.

What gets redacted:
  * email addresses          -- direct identifiers
  * credentials in URLs      -- app_id/app_key/api_key/token/password params
  * Authorization headers    -- Basic and Bearer
  * long hex/base64 secrets  -- API keys pasted into messages

Deliberately NOT redacted: user ids (opaque UUIDs, needed to correlate) and
SOC codes (public taxonomy).
"""

import logging
import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Email -> keep the first character and the domain shape for debugging.
    (re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"),
     r"\1***@\2"),
    # Credentials in query strings.
    (re.compile(r"(?i)\b(app_id|app_key|api_key|apikey|key|token|password|secret|"
                r"registrationkey)=([^&\s\"']+)"), r"\1=REDACTED"),
    # Authorization headers.
    (re.compile(r"(?i)(authorization:\s*)(bearer|basic)\s+\S+"), r"\1\2 REDACTED"),
    # Postgres/other URIs with inline credentials.
    (re.compile(r"(?i)\b([a-z+]+://)([^:/\s]+):([^@/\s]+)@"), r"\1\2:REDACTED@"),
]


def scrub(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Scrubs the formatted message and any string args."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = scrub(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: scrub(v) if isinstance(v, str) else v
                                   for k, v in record.args.items()}
                else:
                    record.args = tuple(
                        scrub(a) if isinstance(a, str) else
                        scrub(str(a)) if isinstance(a, Exception) else a
                        for a in record.args
                    )
        except Exception:
            # A logging filter must never break logging.
            pass
        return True


def install() -> None:
    """Attach the filter to every existing and future root handler."""
    redactor = RedactingFilter()
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(redactor)
    # uvicorn installs its own handlers; cover those too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.addFilter(redactor)
