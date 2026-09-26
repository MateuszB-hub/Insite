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

`oews.json` — national wages (median, mean) and employment per occupation
from the BLS OEWS survey, written by `python -m app.scripts.vendor_bls`
(needs `BLS_API_KEY`; ~53 API requests). OEWS is published once a year, so
the site serves these stored figures instead of asking BLS on every page
view — which ran the key's 500-requests-a-day limit out and left live pages
without pay. Re-run each spring when BLS publishes a new year.

`titles.json` and `abbreviations.json` — O*NET alternate and reported job
titles, and the abbreviations learned from them; written by `vendor_onet`.
