"""Measure how well Find Roles' matching finds the role that was asked for.

    python -m app.scripts.search_eval [strategy ...]      (default: all)

Runs the real search pipeline (search_jobs) for a fixed set of role x place
cases across fields, and scores each result title against a lenient test of
"is this that role" -- synonyms and abbreviations count, so a strategy is not
penalised for finding "Quality Assurance Lead" when asked for "QA lead".

Mostly smaller places on purpose: off-topic results appear where real
matches run out (a mentor's "QA lead" search returned "lead" jobs), not in
nationwide searches, where every strategy looks perfect.

  on-topic   shown results that are the role asked for
  precision  on-topic / shown
  loose      results shown apart, labelled as loose matches (not scored)

Each strategy costs ~12-25 Adzuna requests, from the same daily quota as the
live site, so run it deliberately, not in a loop.
"""

import asyncio
import re
import sys

from dotenv import load_dotenv

load_dotenv()

from app.services import job_search  # noqa: E402

#: (query, place, what an on-topic title contains)
CASES: list[tuple[str, str | None, str]] = [
    ("QA lead", "Dallas", r"\b(qa|quality|test|sdet)"),
    ("QA lead", "Omaha", r"\b(qa|quality|test|sdet)"),
    ("data analyst", "Dallas", r"\bdata\b|analytics"),
    ("data analyst", "Omaha", r"\bdata\b|analytics"),
    ("maintenance technician", "Omaha", r"\bmaint"),
    ("registered nurse", "Omaha", r"\b(nurse|nursing|rn)\b"),
    ("project manager", "Omaha", r"\bproject\b|\bpm\b"),
    ("welder", "Tulsa", r"\bweld"),
    ("software engineer", "Des Moines", r"software|developer|full[- ]?stack|back[- ]?end|front[- ]?end"),
    ("dental hygienist", "Omaha", r"hygien"),
    ("electrician", "Boise", r"electric"),
    ("accountant", "Omaha", r"\baccount"),
]


async def evaluate(strategy: str) -> dict:
    job_search.clear_search_cache()
    rows, shown_all, on_all, loose_all = [], 0, 0, 0
    for query, place, relevant in CASES:
        result = await job_search.search_jobs(
            query, [place] if place else None,
            max_days_old=30, limit=30, strategy=strategy)
        titles = [p.title for p in result.postings]
        on = [t for t in titles if re.search(relevant, t, re.I)]
        off = [t for t in titles if not re.search(relevant, t, re.I)]
        loose = len(getattr(result, "loose_matches", []) or [])
        shown_all += len(titles)
        on_all += len(on)
        loose_all += loose
        rows.append((query, place, len(titles), len(on), loose, off[:2]))
    return {"rows": rows, "shown": shown_all, "on": on_all, "loose": loose_all}


def report(strategy: str, r: dict) -> None:
    print(f"\n=== strategy: {strategy}")
    for query, place, shown, on, loose, off in r["rows"]:
        prec = f"{on / shown:.0%}" if shown else "  -"
        extra = f"  loose {loose}" if loose else ""
        print(f"  {query + ' / ' + (place or 'US'):34} {on:>3}/{shown:<3} {prec:>4}{extra}"
              + (f"   off-topic e.g. {off}" if off else ""))
    prec = r["on"] / r["shown"] if r["shown"] else 0
    print(f"  TOTAL on-topic {r['on']} of {r['shown']} shown  precision {prec:.0%}"
          + (f"  (+{r['loose']} loose, shown apart)" if r["loose"] else ""))


async def main(strategies: list[str]) -> None:
    for strategy in strategies:
        report(strategy, await evaluate(strategy))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or list(job_search.STRATEGIES)))
