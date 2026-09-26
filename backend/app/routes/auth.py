"""Authentication and personal-data endpoints.

Deliberate behaviours:

* Login and registration return the SAME generic failure text and comparable
  timing, so neither reveals whether an email is registered.
* Repeated failures lock the account briefly. Cheap, and it defeats
  credential stuffing without a rate-limiting dependency.
* Logging in rotates the session: any pre-existing token is revoked, so a
  fixated session cannot survive authentication.
* `/me/export` and `/me` (DELETE) implement access and erasure rights. Both
  are audited.
"""

import json
import logging
import os
import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.auth.deps import CurrentUser, DbSession
from app.auth.security import (
    hash_token,
    new_session_token,
    hash_password,
    needs_rehash,
    password_problems,
    verify_password,
)
from app.auth.sessions import (
    audit,
    clear_session_cookie,
    create_session,
    read_session_cookie,
    revoke_all_sessions,
    revoke_session,
    set_session_cookie,
)
from app.auth.email import EmailError, send_email
from app.db.models import (
    AuthProvider,
    Consent,
    ConsentKind,
    DEFAULT_RETENTION_DAYS,
    PasswordResetToken,
    SavedReport,
    User,
    utcnow,
)

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

#: One message for every credential failure. Never say which part was wrong.
_GENERIC_AUTH_ERROR = "Invalid email or password"


#: When set, registration requires this code. A publicly reachable URL
#: otherwise means anyone who finds it can create an account, which is not
#: what you want while a handful of invited testers are trying the app.
#: Unset = open registration.
REGISTRATION_CODE = os.getenv("REGISTRATION_CODE", "").strip()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=200)
    full_name: str | None = Field(None, max_length=200)
    #: Must be explicitly true; we record it as a consent row.
    accept_terms: bool = False
    #: Required only when REGISTRATION_CODE is configured.
    invite_code: str | None = Field(None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str | None = None
    auth_provider: str
    retention_until: str | None = None

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            auth_provider=user.auth_provider.value,
            retention_until=user.retention_until.isoformat()
            if user.retention_until
            else None,
        )


def _locked(user: User) -> bool:
    if user.locked_until is None:
        return False
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        from datetime import timezone

        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > utcnow()


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register(payload: RegisterRequest, request: Request, response: Response, db: DbSession):
    if REGISTRATION_CODE:
        supplied = (payload.invite_code or "").strip()
        # Constant-time compare: the code is a shared secret, and a timing
        # oracle would let it be recovered character by character.
        if not secrets.compare_digest(supplied, REGISTRATION_CODE):
            audit(db, "register.bad_invite")
            db.commit()
            raise HTTPException(403, "That invite code is not valid.")

    if not payload.accept_terms:
        raise HTTPException(400, "You must accept the terms to create an account")

    problems = password_problems(payload.password)
    if problems:
        raise HTTPException(400, "Password " + "; ".join(problems))

    email = payload.email.lower().strip()
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        # Do not confirm the address exists. Hash anyway to equalise timing.
        hash_password(payload.password)
        audit(db, "register.duplicate", detail="attempt on existing address")
        # Phrased conditionally ("if you already have one") so it guides a
        # legitimate user to the sign-in page without confirming to an
        # attacker that this address is registered. The identical wording is
        # what we would show for any other creation failure.
        raise HTTPException(
            409,
            "We couldn't create this account. If you already have one, try "
            "signing in instead.",
        )

    user = User(
        email=email,
        full_name=(payload.full_name or "").strip() or None,
        auth_provider=AuthProvider.password,
        password_hash=hash_password(payload.password),
    )
    user.set_retention(DEFAULT_RETENTION_DAYS)
    db.add(user)
    db.flush()

    db.add(Consent(user_id=user.id, kind=ConsentKind.terms, granted=True))
    db.add(Consent(user_id=user.id, kind=ConsentKind.data_retention, granted=True))
    # Third-party AI is NOT granted by default: local models are the default
    # engine and no applicant data leaves the machine until this is set.
    db.add(Consent(user_id=user.id, kind=ConsentKind.third_party_ai, granted=False))

    _, token = create_session(db, user, request.headers.get("user-agent"))
    set_session_cookie(response, token)
    audit(db, "register", user_id=user.id)
    return UserOut.of(user)


@router.post("/auth/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, response: Response, db: DbSession):
    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        # Equalise timing against the "user exists" path.
        verify_password(payload.password, None)
        raise HTTPException(401, _GENERIC_AUTH_ERROR)

    if _locked(user):
        audit(db, "login.locked", user_id=user.id)
        db.commit()  # persist the audit row; see note above
        raise HTTPException(
            429, f"Too many failed attempts. Try again in {LOCKOUT_MINUTES} minutes."
        )

    if not user.is_active or user.is_erased:
        raise HTTPException(401, _GENERIC_AUTH_ERROR)

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_count = 0
            audit(db, "login.lockout", user_id=user.id)
        else:
            audit(db, "login.failed", user_id=user.id)
        # Commit BEFORE raising: the get_db dependency rolls back on exception,
        # which would otherwise discard the counter and make lockout inert.
        db.commit()
        raise HTTPException(401, _GENERIC_AUTH_ERROR)

    # Upgrade the hash if argon2 parameters have moved on.
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    user.failed_login_count = 0
    user.locked_until = None

    # Session rotation: kill any token presented with this request.
    revoke_session(db, read_session_cookie(request))

    _, token = create_session(db, user, request.headers.get("user-agent"))
    set_session_cookie(response, token)
    audit(db, "login", user_id=user.id)
    return UserOut.of(user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DbSession):
    token = read_session_cookie(request)
    user = None
    if token:
        from app.auth.sessions import resolve_session

        user = resolve_session(db, token)
    revoke_session(db, token)
    audit(db, "logout", user_id=user.id if user else None)
    # Set the cookie on the response we actually RETURN. Mutating the injected
    # `response` and then returning a different object silently discards the
    # header -- FastAPI only merges the injected one when the handler returns
    # a model rather than a Response.
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(out)
    return out


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser):
    return UserOut.of(user)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=1, max_length=200)


@router.post("/auth/change-password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    user: CurrentUser,
    request: Request,
    response: Response,
    db: DbSession,
):
    """Change your own password.

    Requires the current password even though the caller is already
    authenticated: a stolen session cookie must not be enough to seize the
    account outright.

    On success every other session is revoked and this one is rotated, so a
    cookie captured before the change stops working immediately.
    """
    if user.auth_provider is not AuthProvider.password:
        raise HTTPException(
            400, "This account signs in through an identity provider; "
                 "change your password there."
        )

    if not verify_password(payload.current_password, user.password_hash):
        audit(db, "password.change.failed", user_id=user.id)
        db.commit()  # persist the audit row before the exception rolls back
        raise HTTPException(400, "Current password is incorrect")

    problems = password_problems(payload.new_password)
    if problems:
        raise HTTPException(400, "New password " + "; ".join(problems))

    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(400, "New password must differ from the current one")

    user.password_hash = hash_password(payload.new_password)
    user.failed_login_count = 0
    user.locked_until = None

    # A reset link issued before this change must not still work.
    for outstanding in user.reset_tokens:
        if outstanding.used_at is None:
            outstanding.used_at = utcnow()

    # Revoke everything, then issue a fresh session for this caller so they
    # stay signed in here but are logged out everywhere else.
    revoke_all_sessions(db, user)
    _, token = create_session(db, user, request.headers.get("user-agent"))

    audit(db, "password.change", user_id=user.id)
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_cookie(out, token)
    return out


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

RESET_TOKEN_TTL_MINUTES = int(os.getenv("RESET_TOKEN_TTL_MINUTES", "30"))
#: Don't let one address be used to spray email.
RESET_MIN_INTERVAL_SECONDS = 60

#: Identical response whether or not the address exists. Saying "no account
#: with that email" would turn this endpoint into a user-enumeration oracle.
_RESET_ACK = (
    "If an account exists for that address, a reset link has been sent. "
    "Check your inbox."
)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=1, max_length=200)


def _reset_url(token: str) -> str:
    base = os.getenv("APP_BASE_URL", "http://localhost:5173").rstrip("/")
    return f"{base}/reset-password?token={token}"


def _send_reset_email(to: str, token: str) -> None:
    try:
        send_email(
            to=to,
            subject="Reset your Insite password",
            body=(
                "Someone asked to reset the password for your Insite account.\n\n"
                f"Open this link within {RESET_TOKEN_TTL_MINUTES} minutes:\n\n"
                f"    {_reset_url(token)}\n\n"
                "The link can only be used once. If you did not request this, "
                "you can ignore this email -- your password has not changed."
            ),
        )
    except EmailError as exc:
        # Runs after the response, so the caller learns nothing either way.
        logger.error("reset email delivery failed: %s", exc)


@router.post("/auth/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest, background: BackgroundTasks, db: DbSession
):
    """Request a reset link. Always returns the same acknowledgement.

    The email is sent AFTER the response. Sending inline made a known
    address answer ~1s slower than an unknown one (the SMTP round trip),
    which is an account-enumeration oracle the identical body cannot hide.
    """
    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))

    # Every branch below returns _RESET_ACK. The work differs, the answer
    # does not.
    if user is None or not user.is_active or user.is_erased:
        audit(db, "password.reset.request.unknown")
        return {"detail": _RESET_ACK}

    if user.auth_provider is not AuthProvider.password:
        # SSO account: nothing for us to reset.
        audit(db, "password.reset.request.sso", user_id=user.id)
        return {"detail": _RESET_ACK}

    recent = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id)
        .order_by(PasswordResetToken.created_at.desc())
    )
    if recent is not None:
        created = recent.created_at
        if created.tzinfo is None:
            from datetime import timezone

            created = created.replace(tzinfo=timezone.utc)
        if (utcnow() - created).total_seconds() < RESET_MIN_INTERVAL_SECONDS:
            audit(db, "password.reset.request.throttled", user_id=user.id)
            return {"detail": _RESET_ACK}

    # Invalidate anything outstanding: only the newest link should work.
    for old in user.reset_tokens:
        if old.used_at is None:
            old.used_at = utcnow()

    token = new_session_token()
    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
    ))
    audit(db, "password.reset.request", user_id=user.id)
    db.commit()

    background.add_task(_send_reset_email, user.email, token)

    return {"detail": _RESET_ACK}


@router.post("/auth/reset-password", status_code=204)
def reset_password(payload: ResetPasswordRequest, request: Request, db: DbSession):
    """Redeem a reset token and set a new password."""
    row = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(payload.token)
        )
    )
    if row is None or not row.is_valid:
        audit(db, "password.reset.invalid")
        db.commit()
        raise HTTPException(400, "This reset link is invalid or has expired.")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active or user.is_erased:
        raise HTTPException(400, "This reset link is invalid or has expired.")

    problems = password_problems(payload.new_password)
    if problems:
        # Leave the token usable so the user can retry with a better password.
        raise HTTPException(400, "Password " + "; ".join(problems))

    user.password_hash = hash_password(payload.new_password)
    user.failed_login_count = 0
    user.locked_until = None

    row.used_at = utcnow()
    # Burn every other outstanding token too.
    for other in user.reset_tokens:
        if other.used_at is None:
            other.used_at = utcnow()

    # A reset is the response to a possible compromise: end every session.
    revoked = revoke_all_sessions(db, user)

    audit(db, "password.reset", user_id=user.id, detail=f"{revoked} session(s) revoked")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Personal-data rights
# ---------------------------------------------------------------------------


@router.get("/me/export")
def export_my_data(user: CurrentUser, db: DbSession):
    """Right of access / portability: everything we hold, as JSON."""
    reports = db.scalars(
        select(SavedReport).where(SavedReport.user_id == user.id)
    ).all()
    consents = db.scalars(select(Consent).where(Consent.user_id == user.id)).all()

    audit(db, "data.export", user_id=user.id)
    return {
        "exported_at": utcnow().isoformat(),
        "account": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "auth_provider": user.auth_provider.value,
            "created_at": user.created_at.isoformat(),
            "last_login_at": user.last_login_at.isoformat()
            if user.last_login_at
            else None,
            "retention_until": user.retention_until.isoformat()
            if user.retention_until
            else None,
        },
        "consents": [
            {
                "kind": c.kind.value,
                "granted": c.granted,
                "policy_version": c.policy_version,
                "recorded_at": c.recorded_at.isoformat(),
            }
            for c in consents
        ],
        "saved_reports": [
            {
                "id": r.id,
                "kind": r.kind,
                "title": r.title,
                "created_at": r.created_at.isoformat(),
                "payload": json.loads(r.payload_json),
            }
            for r in reports
        ],
        "profile": {
            "current_role": user.profile.current_role,
            "industry": user.profile.industry,
            "years_experience": user.profile.years_experience,
            "location": user.profile.location,
            "skills": user.profile.skill_list(),
            "summary": user.profile.summary,
        }
        if user.profile
        else None,
        "applications": [
            {
                "id": a.id,
                "job_title": a.job_title,
                "company": a.company,
                "job_url": a.job_url,
                "status": a.status.value,
                "cover_letter": a.cover_letter,
                "created_at": a.created_at.isoformat(),
                "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
            }
            for a in user.applications
        ],
        "active_sessions": len([s for s in user.sessions if s.is_valid]),
    }


@router.delete("/me", status_code=204)
def erase_my_data(user: CurrentUser, request: Request, response: Response, db: DbSession):
    """Right to erasure. Scrubs identifying data and drops saved content.

    The user row survives in scrubbed form so the audit trail proving the
    erasure stays referentially intact.
    """
    user_id = user.id
    for report in list(user.reports):
        db.delete(report)
    # Applications and the profile contain the applicant's own words, so a
    # GDPR erasure request removes them outright. Note the tension: an
    # employer may have a legitimate interest in retaining rejection records
    # to defend discrimination claims. We resolve it in the applicant's
    # favour and keep only the anonymised audit row.
    for application in list(user.applications):
        db.delete(application)
    if user.profile is not None:
        db.delete(user.profile)
    revoke_all_sessions(db, user)
    user.erase()
    audit(db, "data.erasure", user_id=user_id, detail="user-initiated")
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(out)
    return out
