"""Synthesis orchestration: findings -> prompt -> provider -> report.

Provider-agnostic. The JSON schema defined here is handed to the provider so
that whichever backend runs (local Ollama, paid Anthropic, mock) is constrained
to the same response shape.
"""

import logging
from typing import Any

from app.services.providers import ProviderUnavailable, get_provider

logger = logging.getLogger(__name__)

#: Shape every provider must return. Mirrors FutureOfWorkResponse.
REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "executive_summary": {
            "type": "string",
            "description": "2-3 sentence summary of the key findings.",
        },
        "trends": {
            "type": "array",
            "description": "3-5 distinct trends.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "source": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["title", "summary"],
            },
        },
        "skills_in_demand": {
            "type": "array",
            "description": "5-8 concrete, named skills.",
            "items": {"type": "string"},
        },
        "outlook": {
            "type": "string",
            "description": "3-5 sentences on growth, compensation, opportunity.",
        },
    },
    "required": ["executive_summary", "trends", "skills_in_demand", "outlook"],
}


def build_prompt(
    industry: str,
    job_title: str | None,
    raw_findings: list[dict[str, Any]],
) -> str:
    """Build the synthesis prompt shared by every provider."""
    findings_text = "\n\n".join(
        "Source: {}\nTitle: {}\nContent: {}".format(
            item.get("source", "Unknown"),
            item.get("title", ""),
            item.get("content", ""),
        )
        for item in raw_findings
    ) or "(no findings returned)"

    job_context = f" for the role of {job_title}" if job_title else ""

    return (
        "You are an expert workforce analyst writing for a job applicant.\n\n"
        f"Using the research findings below about the {industry} industry"
        f"{job_context}, produce a \"Future of Work\" report.\n\n"
        f"Research findings:\n{findings_text}\n\n"
        "Requirements:\n"
        "- Ground every trend in the findings above; do not invent statistics.\n"
        "- Include 3-5 trends and 5-8 concrete, named skills.\n"
        f"- Be specific to {industry}{job_context}, not generic career advice.\n"
        "- Write for a candidate deciding where to invest their time.\n"
        "- Respond with a single JSON object matching the required schema."
    )


async def synthesize_findings(
    industry: str,
    job_title: str | None,
    raw_findings: list[dict[str, Any]],
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Run synthesis and return the full API response payload."""
    provider = await get_provider(provider_name)
    prompt = build_prompt(industry, job_title, raw_findings)

    logger.info(
        "synthesizing industry=%r job_title=%r provider=%s findings=%d",
        industry, job_title, provider.name, len(raw_findings),
    )

    try:
        parsed = await provider.generate_json(prompt, REPORT_SCHEMA)
    except ProviderUnavailable:
        # Let the route translate this into a 503 with a usable message.
        raise

    return {
        "industry": industry,
        "job_title": job_title,
        "provider": provider.name,
        "provider_label": provider.label,
        "executive_summary": parsed.get("executive_summary", ""),
        "trends": parsed.get("trends", []),
        "skills_in_demand": parsed.get("skills_in_demand", []),
        "outlook": parsed.get("outlook", ""),
    }
