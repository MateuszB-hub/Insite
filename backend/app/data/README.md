# Vendored data

`occupations.json` — the O*NET-SOC occupation taxonomy (code, title,
description), derived from O*NET's public database text files:
https://www.onetcenter.org/database.html

Vendored rather than fetched at runtime so occupation resolution works
offline, has no startup latency, and does not depend on O*NET API approval.
O*NET-SOC codes are collapsed to their SOC base (29-1141.00 -> 29-1141),
which is the form BLS OEWS uses.

Attribution is required when this data is displayed — see
`frontend/src/components/SourceAttribution.tsx`.

To refresh, re-run the fetch in the git history for this directory.
