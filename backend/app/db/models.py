"""Database models.

Retention is a first-class column, not an afterthought. Applicant data is
sensitive personal data under GDPR/CCPA, so every row that holds it carries an
explicit expiry the purge job can act on, and erasure is supported without
destroying the audit trail that proves erasure happened.

Design notes:

* Passwords are Argon2id hashes; the plaintext never reaches the database
  layer at all.
* Session tokens are stored as SHA-256 hashes. A database leak therefore does
  not hand out live sessions.
* `User.deleted_at` implements soft erasure: identifying fields are actively
  scrubbed (see `User.erase`), while the row survives so audit records keep
  referential integrity.
"""

import enum
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


#: Default applicant-data retention. Overridable per deployment; 24 months is
#: a common HR default, but it is a policy choice, not a technical one.
DEFAULT_RETENTION_DAYS = 730

#: Cover letters get their own, shorter clock. They are unbounded free text
#: and routinely contain GDPR Article 9 special-category data (health,
#: immigration status, caring responsibilities) that was never asked for.
#: Holding that for two years is unnecessary exposure, so the text is cleared
#: well before the application record itself expires.
COVER_LETTER_RETENTION_DAYS = 180


class AuthProvider(str, enum.Enum):
    password = "password"
    oidc = "oidc"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    auth_provider: Mapped[AuthProvider] = mapped_column(
        Enum(AuthProvider, native_enum=False, length=20),
        default=AuthProvider.password,
    )
    #: Argon2id hash. Null for OIDC users -- they have no local password.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Stable subject claim from the identity provider, for OIDC users.
    oidc_subject: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    oidc_issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Failed-login throttling. Cheap, and stops credential stuffing cold.
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- retention ---
    #: When this user's personal data becomes eligible for purge.
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Set when the user exercises erasure. Identifying fields are scrubbed.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    consents: Mapped[list["Consent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reports: Mapped[list["SavedReport"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    profile: Mapped["ApplicantProfile | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    applications: Mapped[list["Application"]] = relationship(
        back_populates="applicant", cascade="all, delete-orphan"
    )

    @property
    def is_erased(self) -> bool:
        return self.deleted_at is not None

    def set_retention(self, days: int = DEFAULT_RETENTION_DAYS) -> None:
        self.retention_until = utcnow() + timedelta(days=days)

    def erase(self) -> None:
        """Scrub identifying data while keeping the row for audit integrity.

        The email is replaced with a non-reversible placeholder rather than
        nulled, because the column is unique and NOT NULL.
        """
        self.email = f"erased-{self.id}@invalid"
        self.full_name = None
        self.password_hash = None
        self.oidc_subject = None
        self.oidc_issuer = None
        self.is_active = False
        self.deleted_at = utcnow()


class UserSession(Base):
    """A logged-in session. The raw token is never stored."""

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    #: SHA-256 of the session token. A DB leak yields no usable sessions.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Coarse client info for the user's own "active sessions" view. Deliberately
    #: not a fingerprint: truncated UA string, no full IP.
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    @property
    def is_valid(self) -> bool:
        if self.revoked_at is not None:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:  # SQLite round-trips as naive
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > utcnow()


class ConsentKind(str, enum.Enum):
    terms = "terms"
    data_retention = "data_retention"
    #: Explicitly separate: choosing a paid engine sends applicant data to a
    #: third party, whereas the local model does not. That is a distinct
    #: disclosure and needs its own affirmative consent.
    third_party_ai = "third_party_ai"


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ConsentKind] = mapped_column(Enum(ConsentKind, native_enum=False, length=32))
    granted: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Version of the policy text agreed to, so a policy change can re-prompt.
    policy_version: Mapped[str] = mapped_column(String(32), default="1.0")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="consents")


class SavedReport(Base):
    """A pathway or future-of-work report the user chose to keep."""

    __tablename__ = "saved_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # "career_pathway" | "future_of_work"
    title: Mapped[str] = mapped_column(String(300))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="reports")


class AuditLog(Base):
    """Who did what, when. Survives erasure by design.

    Holds no personal data beyond the user id -- the point is to prove an
    action occurred, not to retain a second copy of the applicant's details.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    #: Nullable and not a hard FK cascade: audit outlives the data it describes.
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_audit_user_action", AuditLog.user_id, AuditLog.action)
Index("ix_sessions_expiry", UserSession.expires_at)


# ---------------------------------------------------------------------------
# Applicant portal (#1)
# ---------------------------------------------------------------------------


class ApplicantProfile(Base):
    """What the applicant tells us about themselves.

    Kept separate from `User` on purpose: `User` is identity and is needed to
    authenticate, whereas this is self-declared personal data with a shorter
    natural life. Erasure clears this outright while the scrubbed User row
    survives for audit integrity.
    """

    __tablename__ = "applicant_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )

    current_role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    years_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Comma-separated. A join table is overkill until we need to query by skill.
    skills: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="profile")

    def skill_list(self) -> list[str]:
        return [s.strip() for s in (self.skills or "").split(",") if s.strip()]


class ApplicationStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    in_review = "in_review"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    withdrawn = "withdrawn"


#: Which transitions are legal.
#:
#: This is a candidate-side tool, so every transition belongs to the
#: applicant: they are recording what happened to an application they sent to
#: someone else ("I heard back", "I interviewed", "they passed"). There is no
#: recruiter here to drive the pipeline. The graph is still enforced so the
#: timeline stays coherent -- you cannot go from withdrawn back to submitted.
ALLOWED_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.draft: {ApplicationStatus.submitted, ApplicationStatus.withdrawn},
    ApplicationStatus.submitted: {
        ApplicationStatus.in_review,
        ApplicationStatus.rejected,
        ApplicationStatus.withdrawn,
    },
    ApplicationStatus.in_review: {
        ApplicationStatus.interview,
        ApplicationStatus.rejected,
        ApplicationStatus.withdrawn,
    },
    ApplicationStatus.interview: {
        ApplicationStatus.offer,
        ApplicationStatus.rejected,
        ApplicationStatus.withdrawn,
    },
    ApplicationStatus.offer: {ApplicationStatus.rejected, ApplicationStatus.withdrawn},
    ApplicationStatus.rejected: set(),
    ApplicationStatus.withdrawn: set(),
}


class Application(Base):
    """A job the candidate applied to, found anywhere."""

    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    applicant_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # --- job snapshot --------------------------------------------------
    # Every application is to a job found elsewhere, so the posting is
    # captured at the moment of applying. External adverts disappear, get edited, and get
    # reposted; without a snapshot the record would rot within weeks.
    source: Mapped[str] = mapped_column(String(32), default="internal")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Content fingerprint. THE key for "have I already applied to this?" --
    #: matching on advert text catches the same job reposted under a new id,
    #: which is exactly the case that catches people out.
    fingerprint: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    job_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    job_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, native_enum=False, length=16),
        default=ApplicationStatus.draft,
        index=True,
    )
    cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    applicant: Mapped[User] = relationship(back_populates="applications")
    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application", cascade="all, delete-orphan",
        order_by="ApplicationEvent.occurred_at",
    )

    def can_transition_to(self, target: ApplicationStatus) -> bool:
        return target in ALLOWED_TRANSITIONS.get(self.status, set())


class ApplicationEvent(Base):
    """Status history. Gives the applicant a timeline and HR a paper trail."""

    __tablename__ = "application_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16))
    #: Who moved it. Null for system transitions.
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: This event reverses the previous change (a misclick fix). History is
    #: kept rather than rewritten; replaying the events, with each undo
    #: popping the stack, gives the status to return to.
    is_undo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    application: Mapped[Application] = relationship(back_populates="events")


Index("ix_applications_applicant_status", Application.applicant_id, Application.status)
#: The lookup behind "you already applied to this".
Index("ix_applications_applicant_fingerprint",
      Application.applicant_id, Application.fingerprint)


class PasswordResetToken(Base):
    """A single-use, short-lived password reset token.

    Same discipline as sessions: only the SHA-256 of the token is stored, so a
    database leak yields no usable reset links. Tokens are single-use and every
    outstanding token for a user is invalidated as soon as one is redeemed or
    the password changes by any other route.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="reset_tokens")

    @property
    def is_valid(self) -> bool:
        if self.used_at is not None:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:  # SQLite round-trips naive
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > utcnow()


Index("ix_reset_tokens_expiry", PasswordResetToken.expires_at)


class JobSighting(Base):
    """When we first saw a given job advert, by content rather than by id.

    Exists to defeat re-upping. An employer or agency takes a stale advert
    down and reposts it; the board issues a new id and a fresh "posted" date,
    so the ad looks brand new when it has been circulating for a year. The
    posting's own date is therefore not evidence of anything.

    Fingerprinting the *text* survives that: the same advert reposted under a
    new id lands on the same fingerprint, and `first_seen` is the date we
    actually first encountered it. That is a fact about our observation, not
    a claim from the advertiser -- which is the only kind of age signal worth
    showing.
    """

    __tablename__ = "job_sightings"

    #: SHA-256 prefix of the normalised advert text.
    fingerprint: Mapped[str] = mapped_column(String(32), primary_key=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    times_seen: Mapped[int] = mapped_column(Integer, default=1)
    #: Kept only to render "first seen as X" -- no personal data involved.
    sample_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sample_company: Mapped[str | None] = mapped_column(String(200), nullable=True)


Index("ix_sightings_first_seen", JobSighting.first_seen)
