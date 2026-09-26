"""Narrative overlay for career pathways.

The governing rule: **the model never produces a number.**

Every wage, posting count and employer name comes from the deterministic
labour-market layer. The model receives those as a read-only fact sheet and
returns prose keyed by SOC code. We then join its prose back onto our facts.
Anything it says about an occupation we did not send is discarded.

That makes the failure mode safe. A confused model produces vague prose or
gets dropped; it cannot invent a salary an applicant might act on.

Flow:
    facts (deterministic)  ->  fact sheet  ->  one constrained model call
                                           ->  validate codes
                                           ->  merge prose onto facts
"""

import logging
import re
from typing import Any

from app.services.providers import ProviderUnavailable, get_provider

logger = logging.getLogger(__name__)

READINESS = ("ready", "stretch", "long-term")

#: Models restate readiness in prose even when told not to, in varied
#: phrasings ("Readiness: Long-term.", "This transition is considered
#: 'stretch'.", "This role is considered a stretch."). Left in, it is
#: redundant with the badge and can outright disagree with it. We drop any
#: sentence that states readiness; the structured field is authoritative.
#:
#: Sentence-splitting beats one clever regex here: the phrasings vary too much
#: to enumerate, but they always live in their own sentence.
_READINESS_MARKERS = (
    "readiness",
    "considered ready",
    "considered a ready",
    "considered 'ready'",
    "considered stretch",
    "considered a stretch",
    "considered 'stretch'",
    "considered long-term",
    "considered a long-term",
    "considered 'long-term'",
    "this transition is",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _strip_readiness_restatement(text: str) -> str:
    """Drop sentences that restate readiness, whatever the phrasing."""
    if not text:
        return ""
    kept = [
        sentence
        for sentence in _SENTENCE_SPLIT.split(text.strip())
        if not any(marker in sentence.lower() for marker in _READINESS_MARKERS)
    ]
    return " ".join(kept).strip().rstrip(" ,;:")


NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "3-4 sentences on where this role leads over the horizon.",
        },
        "pathways": {
            "type": "array",
            "description": "One entry per occupation code supplied. Do not invent codes.",
            "items": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "SOC code, copied exactly from the fact sheet.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "1-2 sentences: why this move is plausible from the current role.",
                    },
                    "readiness": {
                        "type": "string",
                        "enum": list(READINESS),
                        "description": "ready = within horizon; stretch = needs deliberate effort; long-term = beyond horizon.",
                    },
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-3 concrete actions to become a credible candidate.",
                    },
                },
                "required": ["code", "rationale", "readiness"],
            },
        },
        "skill_gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-6 named skills to build, most valuable first.",
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "1-3 honest risks or headwinds for this direction.",
        },
    },
    "required": ["summary", "pathways", "skill_gaps"],
}


def build_fact_sheet(report: dict[str, Any]) -> str:
    """Render the deterministic facts as text for the model to reason over.

    Only facts we actually have. Missing wage data is stated as missing rather
    than omitted, so the model does not fill the silence with a guess.
    """
    current = report["current_occupation"]
    horizon = report["horizon_months"]
    lines: list[str] = []

    lines.append(f"CURRENT ROLE (as entered): {report['current_role']}")
    if report.get("industry"):
        lines.append(f"INDUSTRY: {report['industry']}")
    lines.append(f"HORIZON: {horizon} months")
    lines.append("")
    lines.append(
        f"MATCHED OCCUPATION: {current['title']}"
        + (f" (SOC {current['code']})" if current["code"] else " (no SOC match)")
    )
    lines.append(_wage_line("  current pay", current.get("wage")))
    lines.append("")

    lines.append("CANDIDATE DESTINATIONS (use these SOC codes verbatim):")
    if not report["pathways"]:
        lines.append("  (none mapped)")
    for p in report["pathways"]:
        lines.append(f"  - {p['code']}: {p['title']}")
        if p.get("description"):
            lines.append(f"      {p['description']}")
        lines.append(_wage_line("      pay", p.get("wage")))
        if p.get("readiness"):
            lines.append(f"      readiness (from O*NET data, final): {p['readiness']}")
        if p.get("training"):
            lines.append(f"      training: {p['training']}")

    hiring = report.get("hiring") or {}
    employers = hiring.get("top_employers") or []
    lines.append("")
    if employers:
        lines.append(f"EMPLOYERS HIRING FOR '{hiring.get('query', '')}':")
        for e in employers[:8]:
            extra = (
                f", avg advertised ${e['average_salary']:,.0f}"
                if e.get("average_salary")
                else ""
            )
            lines.append(f"  - {e['name']}: {e['postings']} postings{extra}")
        if hiring.get("total_postings"):
            lines.append(f"  total postings: {hiring['total_postings']:,}")
    else:
        lines.append("EMPLOYER DATA: not available (job-market source not connected).")

    return "\n".join(lines)


def _wage_line(label: str, wage: dict[str, Any] | None) -> str:
    if not wage:
        return f"{label}: not available (wage source not connected)"
    parts = []
    if wage.get("annual_median") is not None:
        parts.append(f"median ${wage['annual_median']:,.0f}")
    if wage.get("annual_mean") is not None:
        parts.append(f"mean ${wage['annual_mean']:,.0f}")
    if wage.get("employment") is not None:
        parts.append(f"{wage['employment']:,} employed")
    if wage.get("year"):
        parts.append(f"({wage['year']})")
    return f"{label}: " + (", ".join(parts) if parts else "not available")


def build_prompt(report: dict[str, Any]) -> str:
    horizon = report["horizon_months"]
    return (
        "You are a career adviser writing for a job applicant.\n\n"
        "Below is verified labour-market data. Treat it as the only source of "
        "fact.\n\n"
        f"{build_fact_sheet(report)}\n\n"
        "Write guidance that helps this person decide where to invest the next "
        f"{horizon} months.\n\n"
        "Rules:\n"
        "- Use ONLY the SOC codes listed above, copied exactly. Never invent a code.\n"
        "- Do NOT state any salary, wage, or dollar figure in your text. The "
        "interface displays the real numbers alongside your words.\n"
        "- Where pay or employer data is marked unavailable, do not speculate "
        "about it; focus on skills and role fit instead.\n"
        "- Do NOT mention readiness in the rationale text, in any phrasing. "
        "Readiness is a separate field rendered as a badge; repeating it there "
        "is redundant and causes contradictions.\n"
        "- Each destination's readiness is already decided from O*NET data and "
        "shown to the reader. Copy it into the readiness field unchanged, and "
        "never write anything that contradicts it.\n"
        "- Be specific and honest, including about risks. No filler.\n"
        "- Return a single JSON object matching the required schema."
    )


def _validate(
    parsed: dict[str, Any], valid_codes: set[str]
) -> tuple[dict[str, Any], list[str]]:
    """Drop anything the model made up. Returns (clean, warnings)."""
    warnings: list[str] = []

    clean_pathways: dict[str, dict[str, Any]] = {}
    for item in parsed.get("pathways") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        if code not in valid_codes:
            warnings.append(f"dropped narrative for unknown occupation code {code!r}")
            continue
        readiness = str(item.get("readiness", "")).strip().lower()
        if readiness not in READINESS:
            readiness = "stretch"
        steps = [str(s) for s in (item.get("steps") or []) if str(s).strip()]
        clean_pathways[code] = {
            "rationale": _strip_readiness_restatement(str(item.get("rationale", ""))),
            "readiness": readiness,
            "steps": steps[:4],
        }

    return (
        {
            "summary": str(parsed.get("summary", "")).strip(),
            "by_code": clean_pathways,
            "skill_gaps": [
                str(s) for s in (parsed.get("skill_gaps") or []) if str(s).strip()
            ][:8],
            "risks": [str(s) for s in (parsed.get("risks") or []) if str(s).strip()][:4],
        },
        warnings,
    )


async def attach_narrative(
    report: dict[str, Any],
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Add model-written guidance to a pathway report, in place.

    Never raises: if the model is unavailable the report is returned unchanged
    apart from `narrative_status`, so the caller still gets the facts.
    """
    valid_codes = {p["code"] for p in report["pathways"] if p.get("code")}

    try:
        provider = await get_provider(provider_name)
    except ProviderUnavailable as exc:
        logger.info("narrative skipped, no provider: %s", exc)
        report["narrative"] = None
        report["narrative_status"] = f"unavailable: {exc}"
        return report
    except Exception as exc:
        # Any provider-resolution failure must still yield the facts.
        logger.warning("narrative provider resolution failed: %s", exc)
        report["narrative"] = None
        report["narrative_status"] = f"unavailable: {exc}"
        return report

    try:
        parsed = await provider.generate_json(build_prompt(report), NARRATIVE_SCHEMA)
    except Exception as exc:
        logger.warning("narrative generation failed: %s", exc)
        report["narrative"] = None
        report["narrative_status"] = f"failed: {exc}"
        return report

    clean, warnings = _validate(parsed, valid_codes)
    for warning in warnings:
        logger.warning("narrative validation: %s", warning)

    # Join prose onto the facts. Facts stay authoritative.
    for pathway in report["pathways"]:
        guidance = clean["by_code"].get(pathway.get("code"))
        if guidance:
            pathway["rationale"] = guidance["rationale"]
            # Readiness from O*NET data wins; the model's guess only fills gaps.
            pathway["readiness"] = pathway.get("readiness") or guidance["readiness"]
            pathway["steps"] = guidance["steps"]

    report["narrative"] = {
        "summary": clean["summary"],
        "skill_gaps": clean["skill_gaps"],
        "risks": clean["risks"],
        "provider": provider.name,
        "provider_label": provider.label,
    }
    report["narrative_status"] = "ok"
    if warnings:
        report["narrative_status"] = f"ok ({len(warnings)} item(s) discarded)"
    return report
