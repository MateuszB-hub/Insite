"""The log redactor must catch the mistakes people actually make."""

import logging

import pytest

from app.logging_filters import RedactingFilter, scrub


@pytest.mark.parametrize("raw,must_not_contain", [
    ("user signed in: sam.rivera@gmail.com", "sam.rivera"),
    ("GET https://api.adzuna.com/v1/api/jobs/us/histogram?app_id=0a1b2c3d&app_key=e5347fe8",
     "e5347fe8"),
    ("connecting to postgresql+psycopg://insite:s3cr3tpw@localhost:5433/insite", "s3cr3tpw"),
    ("Authorization: Bearer sk-ant-abc123xyz", "sk-ant-abc123xyz"),
    ("registrationkey=abcdef0123456789", "abcdef0123456789"),
])
def test_secrets_are_scrubbed(raw, must_not_contain):
    assert must_not_contain not in scrub(raw)


def test_email_keeps_debuggable_shape():
    out = scrub("failed login for jane.doe@example.com")
    assert "jane.doe" not in out
    assert "j***@example.com" in out


def test_user_ids_survive():
    """Opaque ids are needed to correlate; they are not PII on their own."""
    uid = "c659a198-2015-4ce7-ad9b-98e76f197e7d"
    assert uid in scrub(f"application.create user_id={uid} position={uid}")


def test_filter_scrubs_lazy_args(caplog):
    handler = logging.getLogger().handlers
    rec = logging.LogRecord("t", logging.INFO, __file__, 1,
                            "login failed for %s", ("jane@example.com",), None)
    RedactingFilter().filter(rec)
    assert "jane@example.com" not in rec.getMessage()


def test_filter_never_raises():
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, None, None, None)
    assert RedactingFilter().filter(rec) is True
