"""Future of Work endpoints."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.providers import (
    ProviderError,
    ProviderUnavailable,
    available_providers,
    paid_enabled,
)
from app.services.search_service import search_industry_trends
from app.services.synthesis_service import synthesize_findings

logger = logging.getLogger(__name__)
router = APIRouter()


class FutureOfWorkRequest(BaseModel):
    industry: str = Field(..., min_length=1, max_length=200)
    job_title: str | None = Field(None, max_length=200)
    #: Override the configured provider for this request ("ollama",
    #: "anthropic", "mock"). None means use the server's policy.
    provider: str | None = Field(None, max_length=50)


class TrendFinding(BaseModel):
    title: str
    summary: str
    source: str | None = None
    source_url: str | None = None


class FutureOfWorkResponse(BaseModel):
    industry: str
    job_title: str | None = None
    #: Which backend actually produced this report.
    provider: str
    provider_label: str
    executive_summary: str
    trends: list[TrendFinding]
    skills_in_demand: list[str]
    outlook: str


class ProviderInfo(BaseModel):
    name: str
    label: str
    tier: str
    available: bool
    locked: bool
    reason: str | None = None


class ProvidersResponse(BaseModel):
    providers: list[ProviderInfo]
    paid_enabled: bool


@router.get("/providers", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    """Which synthesis backends exist and which are usable right now."""
    return ProvidersResponse(
        providers=[ProviderInfo(**p) for p in await available_providers()],
        paid_enabled=paid_enabled(),
    )


@router.post("/future-of-work", response_model=FutureOfWorkResponse)
async def future_of_work(request: FutureOfWorkRequest) -> FutureOfWorkResponse:
    """Search industry trends, then synthesize them into a report."""
    try:
        raw_findings = await search_industry_trends(
            industry=request.industry,
            job_title=request.job_title,
        )
        report = await synthesize_findings(
            industry=request.industry,
            job_title=request.job_title,
            raw_findings=raw_findings,
            provider_name=request.provider,
        )
    except ProviderUnavailable as exc:
        # Actionable and safe to surface: "start ollama", "model not pulled".
        logger.warning("provider unavailable: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderError as exc:
        logger.warning("provider error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        # Unknown failures may carry keys or provider internals -- log, redact.
        logger.exception("future-of-work request failed")
        raise HTTPException(
            status_code=502,
            detail="Unable to generate the report right now. Please retry.",
        )

    return FutureOfWorkResponse(**report)
