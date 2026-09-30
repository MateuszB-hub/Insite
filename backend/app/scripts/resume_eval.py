"""Measure résumé import against made-up résumés with known answers.

    python -m app.scripts.resume_eval [ollama-model ...]   (default: OLLAMA_MODEL)

Five invented résumés -- nurse, electrician, QA lead, a LinkedIn "Save to
PDF"-style export, and a long 12-job one with its certifications at the end
(the shape that broke import live) -- built as real PDFs in code (no real
people). Each runs through the whole pipeline (read PDF, local model, check
against the text) and is scored on:

  fields    role, location, years of experience, and whether every expected
            skill and certification was found
  invented  items the model returned that aren't in the résumé -- caught
            and dropped by the check (should never reach the form)
  seconds   how long the person waits

Uses the local model only (Ollama); no quotas, nothing leaves the machine.
"""

import asyncio
import os
import sys
import time
from datetime import date

MODELS = sys.argv[1:]

# (name, résumé lines, expected)
RESUMES = [
    ("nurse", [
        "Dana Whitfield",
        "Omaha, NE | dana.w@example.com",
        "EXPERIENCE",
        "Registered Nurse, Nebraska Medical Center, Jun 2019 - Present",
        "Triage, patient assessment, IV therapy, Epic charting.",
        "Licensed Practical Nurse, Bellevue Care Home, Jan 2015 - May 2019",
        "Medication administration and wound care.",
        "SKILLS: Triage; IV therapy; Wound care; Epic",
        "CERTIFICATIONS: BLS, ACLS",
    ], {"role": "registered nurse", "location": "omaha", "years": 11,
        "skills": {"triage", "iv therapy", "wound care", "epic"}, "certs": {"bls", "acls"}}),

    ("electrician", [
        "Marcus Reyes - Journeyman Electrician",
        "Boise, ID",
        "WORK HISTORY",
        "Journeyman Electrician | Treasure Valley Electric | 2018 - present",
        "Commercial wiring, conduit bending, panel upgrades, troubleshooting.",
        "Apprentice Electrician | Snake River Contractors | 2014 - 2018",
        "Residential wiring and service calls.",
        "Skills: Conduit bending, Blueprint reading, NEC code, Troubleshooting",
        "Licenses: Idaho Journeyman Electrician License, OSHA 30",
    ], {"role": "journeyman electrician", "location": "boise", "years": 12,
        "skills": {"conduit bending", "blueprint reading", "nec code", "troubleshooting"},
        "certs": {"idaho journeyman electrician license", "osha 30"}}),

    ("qa lead", [
        "Priya Natarajan",
        "Dallas, TX",
        "PROFESSIONAL EXPERIENCE",
        "QA Lead - Lonestar Payments (03/2021 - Present)",
        "Led a team of 4 testers; built Selenium and Cypress suites; Jira; API testing.",
        "Senior QA Engineer - Brightline Software (06/2016 - 02/2021)",
        "Test automation in Python; performance testing with JMeter.",
        "TECHNICAL SKILLS",
        "Selenium, Cypress, Python, JMeter, Jira, API testing",
        "CERTIFICATIONS",
        "ISTQB Certified Tester Foundation Level",
    ], {"role": "qa lead", "location": "dallas", "years": 10,
        "skills": {"selenium", "cypress", "python", "jmeter", "jira"},
        "certs": {"istqb certified tester foundation level"}}),

    ("linkedin export", [
        "Jordan Alvarez",
        "Senior Accountant at Plains Health System",
        "Des Moines, Iowa, United States",
        "Top Skills",
        "Financial Reporting",
        "Account Reconciliation",
        "NetSuite",
        "Certifications",
        "Certified Public Accountant (CPA)",
        "Experience",
        "Plains Health System",
        "Senior Accountant",
        "August 2020 - Present (6 years 2 months)",
        "Heartland Credit Union",
        "Staff Accountant",
        "July 2017 - July 2020 (3 years 1 month)",
        "Page 1 of 1",
    ], {"role": "senior accountant", "location": "des moines", "years": 9,
        "skills": {"financial reporting", "account reconciliation", "netsuite"},
        "certs": {"certified public accountant"}}),
]


def _long_resume() -> list[str]:
    """A long, dense résumé like the real 7-page one that broke import: twelve
    jobs with full bullets, skills, and certifications at the very END -- the
    part a too-small context or text cap silently cut (P10)."""
    employers = ["Northwind Logistics", "Contoso Freight", "Fabrikam Supply", "Tailspin Distribution",
                 "Litware Transport", "Adventure Works Cargo", "Proseware Shipping", "Wingtip Carriers",
                 "Humongous Haulage", "Coho Fleet Services", "Lucerne Freightways", "Margie Logistics"]
    titles = ["Director of Operations", "Senior Operations Manager", "Operations Manager",
              "Regional Logistics Manager", "Logistics Manager", "Distribution Supervisor",
              "Warehouse Supervisor", "Shift Supervisor", "Inventory Coordinator",
              "Logistics Coordinator", "Shipping Clerk", "Warehouse Associate"]
    lines = ["Morgan Reyes", "Kansas City, MO | morgan.r@example.com | (555) 010-2233",
             "SUMMARY", "Operations leader across freight, warehousing and distribution.", "EXPERIENCE"]
    end_year = None
    for i, (title, employer) in enumerate(zip(titles, employers)):
        start = 2024 - 2 * i
        end = "Present" if i == 0 else f"Dec {start + 1}"
        lines.append(f"{title}, {employer}, Jan {start} - {end}")
        for n in range(6):
            lines.append(f"- Led cross-site initiative {n + 1} at {employer}: cut dock-to-stock time, "
                         f"rebuilt slotting, trained crews of {10 + n} on safety and scanning workflows, "
                         f"and reported weekly throughput, cost per unit and on-time delivery to leadership.")
        end_year = start
    lines += ["EDUCATION", f"B.S. Supply Chain Management, State University, {end_year - 4} - {end_year}",
              "SKILLS: Warehouse management systems; Lean; Six Sigma; Forklift operation; Budgeting",
              "CERTIFICATIONS: APICS CSCP; OSHA 30; Certified Six Sigma Green Belt"]
    return lines


RESUMES.append(("long, 12 jobs", _long_resume(),
                {"role": "director of operations", "location": "kansas city", "years": 24,
                 "skills": {"lean", "six sigma", "budgeting"},
                 "certs": {"apics cscp", "osha 30", "six sigma green belt"}}))

TODAY = date(2026, 9, 26)


def _has(found: list[str], wanted: str) -> bool:
    return any(wanted in f.lower() for f in found)


async def run(model: str | None) -> None:
    # The model is passed to the provider directly: setting OLLAMA_MODEL here
    # only worked for the first model -- the provider reads it once, at import,
    # so a second model in the same run silently re-tested the first.
    from app.services import resume
    from app.services.providers.ollama_provider import OllamaProvider
    from tests.pdf_fixtures import make_pdf

    total = right = invented = 0
    print(f"\n=== model: {model or os.getenv('OLLAMA_MODEL', 'default')}")
    for name, lines, want in RESUMES:
        started = time.monotonic()
        text, _ = await resume.read_pdf(make_pdf(lines))
        provider = OllamaProvider(model=model) if model else await resume.get_provider("ollama")
        raw = await provider.generate_json(resume.build_prompt(text), resume.SCHEMA)
        got = resume.check(raw, text, TODAY)
        secs = time.monotonic() - started
        f = got["fields"]
        checks = {
            "role": (f["current_role"] or "").lower() == want["role"],
            "location": want["location"] in (f["location"] or "").lower(),
            "years": f["years_experience"] == want["years"],
            "skills": all(_has(f["skills"], s) for s in want["skills"]),
            "certs": all(_has(f["certifications"], c) for c in want["certs"]),
        }
        caught = sum(got["dropped"].values())
        total += len(checks)
        right += sum(checks.values())
        invented += caught
        misses = [k for k, ok in checks.items() if not ok]
        print(f"  {name:16} {sum(checks.values())}/{len(checks)} fields  "
              f"invented+caught {caught:<2} {secs:5.1f}s"
              + (f"   missed: {', '.join(misses)} -> "
                 f"role={f['current_role']!r} years={f['years_experience']} "
                 f"skills={f['skills']} certs={f['certifications']}" if misses else ""))
    print(f"  TOTAL {right}/{total} fields right; {invented} invented items caught and dropped")


async def main() -> None:
    for model in MODELS or [None]:
        await run(model)


if __name__ == "__main__":
    asyncio.run(main())
