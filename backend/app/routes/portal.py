"""Candidate portal: profile and self-tracked applications to external postings.

Authorisation rules enforced here (never in the client):

* An applicant sees and mutates only their own profile and applications.
* Every status transition belongs to the applicant -- this is a candidate-side
  tool, recording what happened to applications they sent elsewhere.
* Transitions are still validated against ALLOWED_TRANSITIONS so a timeline
  cannot become incoherent (withdrawn back to submitted, say).
* Every application is to an external job, tracked by content fingerprint.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentUser, DbSession
from app.auth.sessions import audit
from app.db.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    ApplicantProfile,
    DEFAULT_RETENTION_DAYS,
    utcnow,
)
from datetime import timedelta

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


class ProfileIn(BaseModel):
    current_role: str | None = Field(None, max_length=200)
    industry: str | None = Field(None, max_length=200)
    years_experience: int | None = Field(None, ge=0, le=70)
    location: str | None = Field(None, max_length=200)
    skills: list[str] = Field(default_factory=list)
    summary: str | None = Field(None, max_length=4000)


class ProfileOut(BaseModel):
    current_role: str | None = None
    industry: str | None = None
    years_experience: int | None = None
    location: str | None = None
    skills: list[str] = []
    summary: str | None = None
    updated_at: str | None = None

    @classmethod
    def of(cls, p: ApplicantProfile | None) -> "ProfileOut":
        if p is None:
            return cls()
        return cls(
            current_role=p.current_role,
            industry=p.industry,
            years_experience=p.years_experience,
            location=p.location,
            skills=p.skill_list(),
            summary=p.summary,
            updated_at=p.updated_at.isoformat() if p.updated_at else None,
        )


@router.get("/me/profile", response_model=ProfileOut)
def get_profile(user: CurrentUser):
    return ProfileOut.of(user.profile)


@router.put("/me/profile", response_model=ProfileOut)
def put_profile(payload: ProfileIn, user: CurrentUser, db: DbSession):
    profile = user.profile
    if profile is None:
        profile = ApplicantProfile(user_id=user.id)
        db.add(profile)
        user.profile = profile

    profile.current_role = payload.current_role
    profile.industry = payload.industry
    profile.years_experience = payload.years_experience
    profile.location = payload.location
    profile.skills = ", ".join(s.strip() for s in payload.skills if s.strip()) or None
    profile.summary = payload.summary
    profile.updated_at = utcnow()

    audit(db, "profile.update", user_id=user.id)
    db.flush()
    return ProfileOut.of(profile)


# ---------------------------------------------------------------------------
# Applications (applicant side)
# ---------------------------------------------------------------------------


class TrackJobRequest(BaseModel):
    """Record that you applied to a job found through search."""

    fingerprint: str = Field(..., min_length=8, max_length=32)
    title: str = Field(..., min_length=1, max_length=300)
    company: str | None = Field(None, max_length=200)
    location: str | None = Field(None, max_length=200)
    url: str | None = Field(None, max_length=1000)
    external_id: str | None = Field(None, max_length=120)
    # Floats, not ints: job boards return fractional salaries (Adzuna sends
    # 66979.29). Declaring these as int made every real posting fail
    # validation with a 422 while integer test fixtures passed.
    salary_min: float | None = Field(None, ge=0, le=10_000_000)
    salary_max: float | None = Field(None, ge=0, le=10_000_000)
    source: str = Field("adzuna", max_length=32)
    #: False records it as a draft you mean to finish.
    applied: bool = True


class EventOut(BaseModel):
    from_status: str | None = None
    to_status: str
    note: str | None = None
    occurred_at: str


class ApplicationOut(BaseModel):
    id: str
    position_title: str
    status: str
    company: str | None = None
    job_location: str | None = None
    job_url: str | None = None
    fingerprint: str | None = None
    source: str = "internal"
    cover_letter: str | None = None
    created_at: str
    submitted_at: str | None = None
    events: list[EventOut] = []

    @classmethod
    def of(cls, a: Application) -> "ApplicationOut":
        return cls(
            id=a.id,
            position_title=a.job_title or "",
            company=a.company,
            job_location=a.job_location,
            job_url=a.job_url,
            fingerprint=a.fingerprint,
            source=a.source,
            status=a.status.value,
            cover_letter=a.cover_letter,
            created_at=a.created_at.isoformat(),
            submitted_at=a.submitted_at.isoformat() if a.submitted_at else None,
            events=[
                EventOut(
                    from_status=e.from_status, to_status=e.to_status,
                    note=e.note, occurred_at=e.occurred_at.isoformat(),
                )
                for e in a.events
            ],
        )


def _record(db, application: Application, to_status: ApplicationStatus,
            actor_id: str | None, note: str | None = None) -> None:
    db.add(ApplicationEvent(
        application_id=application.id,
        from_status=application.status.value,
        to_status=to_status.value,
        actor_id=actor_id,
        note=note,
    ))
    application.status = to_status
    application.updated_at = utcnow()


@router.post("/applications/track", response_model=ApplicationOut, status_code=201)
def track_job(payload: TrackJobRequest, user: CurrentUser, db: DbSession):
    """Mark a job found through search as applied to.

    Matching is on the content fingerprint, not the advert id, so reapplying
    to the same job reposted under a new id is caught.
    """
    existing = db.scalar(
        select(Application).where(
            Application.applicant_id == user.id,
            Application.fingerprint == payload.fingerprint,
        )
    )
    if existing is not None:
        raise HTTPException(
            409,
            f"You already tracked this job on "
            f"{existing.created_at.date().isoformat()} "
            f"({existing.status.value.replace('_', ' ')}).",
        )

    application = Application(
        applicant_id=user.id,
        source=payload.source,
        external_id=payload.external_id,
        fingerprint=payload.fingerprint,
        job_title=payload.title,
        company=payload.company,
        job_location=payload.location,
        job_url=payload.url,
        # The column is an integer; salaries do not need cent precision.
        salary_min=round(payload.salary_min) if payload.salary_min is not None else None,
        salary_max=round(payload.salary_max) if payload.salary_max is not None else None,
        status=ApplicationStatus.draft,
        retention_until=utcnow() + timedelta(days=DEFAULT_RETENTION_DAYS),
    )
    db.add(application)
    db.flush()

    db.add(ApplicationEvent(application_id=application.id, from_status=None,
                            to_status=ApplicationStatus.draft.value, actor_id=user.id))
    if payload.applied:
        _record(db, application, ApplicationStatus.submitted, user.id)
        application.submitted_at = utcnow()

    audit(db, "application.track", user_id=user.id, detail=f"source={payload.source}")
    db.flush()
    db.refresh(application)
    return ApplicationOut.of(application)


class TrackedFingerprints(BaseModel):
    fingerprints: list[str]


@router.get("/applications/tracked", response_model=TrackedFingerprints)
def tracked_fingerprints(user: CurrentUser, db: DbSession):
    """Fingerprints this user has already applied to, for marking search results."""
    rows = db.scalars(
        select(Application.fingerprint).where(
            Application.applicant_id == user.id,
            Application.fingerprint.is_not(None),
        )
    ).all()
    return TrackedFingerprints(fingerprints=[f for f in rows if f])


@router.get("/applications", response_model=list[ApplicationOut])
def my_applications(user: CurrentUser, db: DbSession):
    rows = db.scalars(
        select(Application)
        .where(Application.applicant_id == user.id)
        .order_by(Application.created_at.desc())
    ).all()
    return [ApplicationOut.of(a) for a in rows]


@router.get("/applications/{application_id}", response_model=ApplicationOut)
def get_application(application_id: str, user: CurrentUser, db: DbSession):
    application = db.get(Application, application_id)
    # Ownership check, not just existence: never leak another applicant's row.
    if application is None or application.applicant_id != user.id:
        raise HTTPException(404, "Application not found")
    return ApplicationOut.of(application)


class StatusUpdate(BaseModel):
    status: ApplicationStatus
    note: str | None = Field(None, max_length=500)


@router.post("/applications/{application_id}/status", response_model=ApplicationOut)
def update_status(application_id: str, payload: StatusUpdate,
                  user: CurrentUser, db: DbSession):
    """Record what happened to one of your applications."""
    application = db.get(Application, application_id)
    if application is None or application.applicant_id != user.id:
        raise HTTPException(404, "Application not found")

    if not application.can_transition_to(payload.status):
        raise HTTPException(
            409,
            f"Cannot move from {application.status.value} to {payload.status.value}",
        )

    _record(db, application, payload.status, user.id, payload.note)
    if payload.status is ApplicationStatus.submitted:
        application.submitted_at = utcnow()
    audit(db, "application.status", user_id=user.id,
          detail=f"-> {payload.status.value}")
    db.flush()
    return ApplicationOut.of(application)
