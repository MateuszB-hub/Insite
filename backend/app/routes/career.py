"""Career pathway endpoints."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import CurrentUser
from app.services.career_service import build_career_pathway, narrate_career_pathway
from app.services.labor import labor_status

logger = logging.getLogger(__name__)
router = APIRouter()


class CareerPathwayRequest(BaseModel):
    current_role: str = Field(..., min_length=1, max_length=200)
    industry: str | None = Field(None, max_length=200)
    #: How far ahead to look. 12 = "after a year".
    horizon_months: int = Field(12, ge=1, le=120)
    location: str | None = Field(None, max_length=200)
    #: Attach model-written guidance over the facts. Off = facts only, fast.
    include_narrative: bool = True
    #: Override the synthesis engine for the narrative ("ollama"/"mock"/...).
    provider: str | None = Field(None, max_length=50)


class WageInfo(BaseModel):
    annual_median: float | None = None
    annual_mean: float | None = None
    employment: int | None = None
    year: str | None = None
    area: str | None = None
    source: str | None = None


class OccupationInfo(BaseModel):
    code: str
    title: str
    description: str = ""
    skills: list[str] = []
    job_zone: int | None = None
    wage: WageInfo | None = None
    # --- narrative overlay (model-written, joined on SOC code) ---
    rationale: str | None = None
    readiness: str | None = None
    steps: list[str] = []


class SkillGap(BaseModel):
    skill: str
    gap: float


class TransferableRole(BaseModel):
    code: str
    title: str
    description: str = ""
    #: Cosine similarity of the 35-dimension O*NET skill profile.
    similarity: float
    #: True when O*NET places this in a higher Job Zone than the current role.
    requires_more_training: bool
    job_zone: int | None = None
    skill_gaps: list[SkillGap] = []
    wage: WageInfo | None = None


class EmployerInfo(BaseModel):
    name: str
    postings: int
    average_salary: float | None = None


class SalaryBandInfo(BaseModel):
    lower: float
    upper: float | None = None
    count: int


class HiringInfo(BaseModel):
    query: str
    total_postings: int | None = None
    top_employers: list[EmployerInfo] = []
    salary_distribution: list[SalaryBandInfo] = []
    salary_history: dict[str, float] = {}


class DataSourceInfo(BaseModel):
    capability: str
    name: str
    label: str
    live: bool
    reason: str | None = None
    signup_url: str | None = None


class NarrativeInfo(BaseModel):
    summary: str
    skill_gaps: list[str] = []
    risks: list[str] = []
    provider: str
    provider_label: str


class CareerPathwayResponse(BaseModel):
    current_role: str
    industry: str | None = None
    horizon_months: int
    current_occupation: OccupationInfo
    pathways: list[OccupationInfo]
    #: Occupations whose skill profile resembles the current role.
    transferable: list[TransferableRole] = []
    hiring: HiringInfo | None = None
    #: Which sources were live for this report. The UI uses this to mark
    #: sections as measured vs. scaffolded -- never present a fallback as fact.
    data_sources: list[DataSourceInfo]
    #: Model-written guidance over the facts. None when the model was
    #: unavailable -- the facts above are still valid.
    narrative: NarrativeInfo | None = None
    narrative_status: str = "not requested"


@router.get("/labor/status", response_model=list[DataSourceInfo])
async def get_labor_status() -> list[DataSourceInfo]:
    """Which labour-market sources are configured, and where to register."""
    return [DataSourceInfo(**s) for s in labor_status()]


# Both pathway routes need a signed-in user: each call spends BLS/Adzuna
# quota and, for the narrative, minutes of model time.
@router.post("/career-pathway", response_model=CareerPathwayResponse)
async def career_pathway(request: CareerPathwayRequest, user: CurrentUser) -> CareerPathwayResponse:
    """Adjacent roles, wages and hiring evidence for a role and horizon."""
    try:
        report = await build_career_pathway(
            current_role=request.current_role,
            industry=request.industry,
            horizon_months=request.horizon_months,
            location=request.location,
            include_narrative=request.include_narrative,
            provider_name=request.provider,
        )
    except Exception:
        logger.exception("career-pathway request failed")
        raise HTTPException(
            status_code=502,
            detail="Unable to build the career pathway right now. Please retry.",
        )

    return CareerPathwayResponse(**report)


@router.post("/career-pathway/narrative", response_model=CareerPathwayResponse)
async def career_pathway_narrative(
    request: CareerPathwayRequest, user: CurrentUser
) -> CareerPathwayResponse:
    """The same report with the model-written summary attached.

    The page asks for the facts first (include_narrative=false) and shows
    them at once; this slower call follows. A model failure still returns
    the facts, with `narrative_status` saying why there is no summary.
    """
    try:
        report = await narrate_career_pathway(
            current_role=request.current_role,
            industry=request.industry,
            horizon_months=request.horizon_months,
            location=request.location,
            provider_name=request.provider,
        )
    except Exception:
        logger.exception("career-pathway narrative request failed")
        raise HTTPException(
            status_code=502,
            detail="Unable to write the summary right now. Please retry.",
        )

    return CareerPathwayResponse(**report)
