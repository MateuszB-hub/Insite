"""Where to learn what a role needs: plain training requirements and links.

Tester feedback on "Skills to build": "this means nothing right here, might
be more helpful to link to one of those roadmaps that people do". So every
occupation links to its O*NET OnLine page (tasks, skills, tools, education)
and CareerOneStop's training and certification finder -- both US Department
of Labor, both covering every field -- and tech occupations also link to the
community roadmaps at roadmap.sh.

All links were checked to resolve when this table was written (Sept 2026).
"""

from urllib.parse import quote, urlencode

#: O*NET Job Zones in plain words, following O*NET's own definitions.
ZONE_TRAINING: dict[int, str] = {
    1: "Little or no preparation; some need a high school diploma",
    2: "Usually a high school diploma and some experience",
    3: "Usually vocational training, an associate's degree, or on-the-job experience",
    4: "Usually a bachelor's degree",
    5: "Usually a graduate degree (master's, doctorate, or professional)",
}

#: roadmap.sh paths per SOC code. Only where a roadmap genuinely matches the
#: occupation -- a wrong roadmap is worse than none.
ROADMAPS: dict[str, list[tuple[str, str]]] = {
    "15-1211": [("Software Architect", "software-architect")],
    "15-1212": [("Cyber Security", "cyber-security")],
    "15-1221": [("Machine Learning", "machine-learning"), ("AI and Data Scientist", "ai-data-scientist")],
    "15-1231": [("Linux", "linux")],
    "15-1241": [("DevOps", "devops"), ("AWS", "aws")],
    "15-1242": [("PostgreSQL DBA", "postgresql-dba"), ("SQL", "sql")],
    "15-1243": [("PostgreSQL DBA", "postgresql-dba"), ("SQL", "sql")],
    "15-1244": [("Linux", "linux"), ("DevOps", "devops")],
    "15-1251": [("Backend", "backend"), ("Computer Science", "computer-science")],
    "15-1252": [("Backend", "backend"), ("Frontend", "frontend"), ("Full Stack", "full-stack")],
    "15-1253": [("QA", "qa")],
    "15-1254": [("Frontend", "frontend"), ("Full Stack", "full-stack")],
    "15-1255": [("UX Design", "ux-design"), ("Frontend", "frontend")],
    "15-1299": [("Software Architect", "software-architect"), ("DevOps", "devops")],
    "15-2031": [("Data Analyst", "data-analyst")],
    "15-2041": [("Data Analyst", "data-analyst")],
    "15-2051": [("AI and Data Scientist", "ai-data-scientist"), ("Machine Learning", "machine-learning")],
    "11-3021": [("Engineering Manager", "engineering-manager")],
    "27-3042": [("Technical Writer", "technical-writer")],
}


def training(job_zone: int | None) -> str | None:
    return ZONE_TRAINING.get(job_zone) if job_zone else None


def links(soc: str, onet: str | None, title: str) -> list[dict[str, str]]:
    """Learning links for an occupation, most specific first."""
    if not soc:
        return []
    out: list[dict[str, str]] = [
        {"label": f"{name} roadmap", "url": f"https://roadmap.sh/{slug}", "source": "roadmap.sh"}
        for name, slug in ROADMAPS.get(soc, [])
    ]
    onet = onet or f"{soc}.00"
    out.append({
        "label": "What the job involves",
        "url": f"https://www.onetonline.org/link/summary/{quote(onet)}",
        "source": "O*NET OnLine",
    })
    out.append({
        "label": "Training and certifications",
        "url": "https://www.careeronestop.org/Toolkit/Training/find-certifications.aspx?"
        + urlencode({"keyword": title}),
        "source": "CareerOneStop",
    })
    return out
