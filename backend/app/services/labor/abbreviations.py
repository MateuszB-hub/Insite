"""Job-title abbreviations, learned from O*NET's own titles.

O*NET writes many titles twice: "Quality Assurance Analyst (QA Analyst)",
"Registered Nurse (RN)", "CEO (Chief Executive Officer)". Lining up each
pair gives the abbreviation and what it stands for ("QA" <-> "Quality
Assurance") for every field at once -- no hand-kept lists.

A pair is kept only when the short form is one word whose letters are the
initials of the words it replaces, so "Quality Assurance Analyst (QA
Analyst)" teaches QA but a paraphrase ("Agency Owner (Owner)") teaches
nothing.

    derive(pairs) -> {"qa": ["quality assurance"], "rn": ["registered nurse"], ...}
"""

import json
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent.parent / "data" / "abbreviations.json"

#: English words that look like acronyms in a typed query ("it", "or", "us").
#: They are never treated as abbreviations when expanding a query.
_NOT_ACRONYMS = {
    "a", "an", "and", "as", "at", "by", "for", "in", "is", "it", "of", "on", "or",
    "the", "to", "us", "we", "me", "my", "no", "so", "up", "do", "go", "be",
}

_WORD = re.compile(r"[a-z0-9]+(?:['&/][a-z0-9]+)*")
_PAIR = re.compile(r"^(?P<outer>[^()]+?)\s*\((?P<inner>[^()]+)\)\s*$")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _align(long_title: str, short_title: str) -> tuple[str, str] | None:
    """("Quality Assurance Analyst", "QA Analyst") -> ("qa", "quality assurance")."""
    long_w, short_w = _words(long_title), _words(short_title)
    if not long_w or not short_w or len(short_w) >= len(long_w):
        return None
    # Strip the words both forms share at the start and the end.
    while long_w and short_w and long_w[0] == short_w[0]:
        long_w, short_w = long_w[1:], short_w[1:]
    while long_w and short_w and long_w[-1] == short_w[-1]:
        long_w, short_w = long_w[:-1], short_w[:-1]
    if len(short_w) != 1 or len(long_w) < 2:
        return None
    acronym = short_w[0]
    if not acronym.isalpha() or not 2 <= len(acronym) <= 6:
        return None
    if "".join(w[0] for w in long_w) != acronym:
        return None
    return acronym, " ".join(long_w)


def pairs_from_titles(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(title, short title or "") rows -> (long, short) candidate pairs."""
    out: list[tuple[str, str]] = []
    for title, short in rows:
        if short and short.lower() != "n/a":
            out.append((title, short))
        m = _PAIR.match(title)
        if m:
            outer, inner = m.group("outer").strip(), m.group("inner").strip()
            # Either order: "Registered Nurse (RN)" and "CEO (Chief Executive Officer)".
            out.append((outer, inner) if len(outer) > len(inner) else (inner, outer))
    return out


def derive(pairs: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Acronym -> expansions, most frequently attested first."""
    seen: dict[str, Counter] = defaultdict(Counter)
    for long_title, short_title in pairs:
        # A parenthetical long title ("Quality Assurance Analyst (QA Analyst)")
        # is compared without its brackets.
        long_title = _PAIR.sub(lambda m: m.group("outer"), long_title)
        found = _align(long_title, short_title)
        if found:
            acronym, expansion = found
            seen[acronym][expansion] += 1
    return {a: [e for e, _ in c.most_common()] for a, c in sorted(seen.items())}


@lru_cache(maxsize=1)
def _table() -> dict[str, list[str]]:
    try:
        with _DATA.open() as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


@lru_cache(maxsize=1)
def _reverse() -> dict[str, str]:
    """Expansion -> acronym, only for acronyms with a single meaning.

    Spelling out is safe; abbreviating is not: "project manager" -> "PM" would
    also find "PM Technician" (preventive maintenance). So an acronym is used
    only when every meaning O*NET gives it starts with the same word
    (RN: registered nurse / registered nursing).
    """
    out: dict[str, str] = {}
    for acronym, expansions in _table().items():
        if acronym in _NOT_ACRONYMS:
            continue
        if len({e.split()[0] for e in expansions}) != 1:
            continue
        out.setdefault(expansions[0], acronym)
    return out


def variants(query: str, limit: int = 2) -> list[str]:
    """Other ways the same title is written: "qa lead" -> ["quality assurance lead"].

    Each abbreviation in the query is spelled out (its best-attested meaning
    first), and each spelled-out form is abbreviated. Other words are kept.
    """
    words = _words(query)
    if not words:
        return []
    table, reverse = _table(), _reverse()
    out: list[str] = []

    for i, word in enumerate(words):
        if word in _NOT_ACRONYMS:
            continue
        for expansion in table.get(word, [])[:limit]:
            out.append(" ".join(words[:i] + [expansion] + words[i + 1:]))

    joined = " ".join(words)
    for expansion, acronym in reverse.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(expansion)}(?![a-z0-9])", joined):
            out.append(re.sub(rf"(?<![a-z0-9]){re.escape(expansion)}(?![a-z0-9])", acronym, joined))

    unique = []
    for v in out:
        if v != joined and v not in unique:
            unique.append(v)
    return unique[:limit]
