"""Scheduled data retention.

Two jobs, both idempotent and safe to run repeatedly:

  purge_expired_data -- erase users past `retention_until`, drop expired
                        saved reports, and delete dead sessions.
  trim_audit_log     -- audit entries are kept longer than personal data
                        (they hold only a user id and an action), but not
                        forever.

Run from the API's startup scheduler, or standalone:
    python -m app.services.retention
"""

import logging
import os
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.db.models import (
    Application,
    AuditLog,
    COVER_LETTER_RETENTION_DAYS,
    SavedReport,
    User,
    UserSession,
    utcnow,
)

logger = logging.getLogger(__name__)

AUDIT_RETENTION_DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "1095"))  # 3 years


def purge_expired_data(db: Session) -> dict[str, int]:
    """Erase anything past its retention date. Returns counts per category."""
    now = utcnow()
    counts = {
        "users_erased": 0,
        "reports_deleted": 0,
        "applications_deleted": 0,
        "sessions_deleted": 0,
        "cover_letters_cleared": 0,
    }

    expired_users = db.scalars(
        select(User).where(
            User.retention_until.is_not(None),
            User.retention_until < now,
            User.deleted_at.is_(None),
        )
    ).all()
    for user in expired_users:
        for report in list(user.reports):
            db.delete(report)
        for application in list(user.applications):
            db.delete(application)
        if user.profile is not None:
            db.delete(user.profile)
        for session in user.sessions:
            if session.revoked_at is None:
                session.revoked_at = now
        user.erase()
        db.add(
            AuditLog(
                user_id=user.id,
                action="data.erasure",
                detail="automatic: retention period elapsed",
            )
        )
        counts["users_erased"] += 1

    # synchronize_session=False: let the database do the comparison. SQLite
    # round-trips datetimes as naive, and in-Python evaluation then trips over
    # naive-vs-aware. The DB handles it correctly on both backends.
    result = db.execute(
        delete(SavedReport).where(
            SavedReport.retention_until.is_not(None),
            SavedReport.retention_until < now,
        ),
        execution_options={"synchronize_session": False},
    )
    counts["reports_deleted"] += result.rowcount or 0

    result = db.execute(
        delete(Application).where(
            Application.retention_until.is_not(None),
            Application.retention_until < now,
        ),
        execution_options={"synchronize_session": False},
    )
    counts["applications_deleted"] += result.rowcount or 0

    # Clear cover-letter text on its own shorter clock. The application row
    # survives -- the candidate still sees where they applied and what came of
    # it -- but the free text they wrote is gone.
    cover_cutoff = now - timedelta(days=COVER_LETTER_RETENTION_DAYS)
    stale = db.scalars(
        select(Application).where(
            Application.cover_letter.is_not(None),
            Application.created_at < cover_cutoff,
        )
    ).all()
    for application in stale:
        application.cover_letter = None
        counts["cover_letters_cleared"] += 1

    # Expired/revoked sessions carry no value once dead.
    result = db.execute(
        delete(UserSession).where(UserSession.expires_at < now),
        execution_options={"synchronize_session": False},
    )
    counts["sessions_deleted"] = result.rowcount or 0

    return counts


def trim_audit_log(db: Session) -> int:
    cutoff = utcnow() - timedelta(days=AUDIT_RETENTION_DAYS)
    result = db.execute(
        delete(AuditLog).where(AuditLog.occurred_at < cutoff),
        execution_options={"synchronize_session": False},
    )
    return result.rowcount or 0


def run_retention() -> dict[str, int]:
    db = SessionLocal()
    try:
        counts = purge_expired_data(db)
        counts["audit_trimmed"] = trim_audit_log(db)
        db.commit()
        logger.info("retention sweep: %s", counts)
        return counts
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_retention())
