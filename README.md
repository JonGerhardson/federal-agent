# federal-agent

A Claude Code skill for querying, analyzing, and building tools for federal contract and spending
data from FPDS (Federal Procurement Data System), USAspending.gov, and SAM.gov APIs — including
**bulk extraction paths that sidestep SAM's per-day API caps**.

## Overview

This skill provides comprehensive knowledge and reusable code for working with three primary federal
procurement data sources:

- **FPDS ATOM Feed** — transaction-level contract detail via the `fpds` Python library
- **USAspending API** — award aggregations and fiscal-year summaries (no auth, no rate limit)
- **SAM.gov** — entity registrations, contract opportunities, exclusions (debarment), and org hierarchy (free API key)

SAM's *search* APIs are capped at **10 requests/day** on a bare key, so for any bulk or
cross-reference work the skill defaults to **bulk** routes: the asynchronous Entity Extract API and
GSA's public flat-file extracts. Everything joins on **UEI** (the Unique Entity ID).

## Features

- Query federal contracts by agency, date, vendor, NAICS code, PSC code
- Analyze spending patterns, vendor concentration, contract modifications
- **Bulk SAM entity extract** — pull the entire active-registrant universe (~745k) in one job, bypassing the 10/day cap
- **SAM File Extracts** — Contract Opportunities, Exclusions (debarment), and Assistance Listings as daily flat files (no key for the public ones)
- **Debarment cross-check** — flag award winners on the SAM Exclusions list by UEI
- **Entity resolution / shell-company detection** — e.g. flag a freshly-activated entity winning a large award
- Look up contractor registrations and SAM.gov entity details
- Search active solicitations and opportunities
- Cross-reference data across FPDS / USAspending / SAM on UEI
- **Mandatory data provenance** — every pull saves its raw response + a sha256 manifest for reproducibility
- **Importable modules** — `scripts/` ships reusable, cached, provenance-aware Python, not just docs

## Installation

Copy this directory to `~/.claude/skills/federal-procurement/`. The `scripts/` modules are importable
(e.g. `from scripts.file_extracts import load_file_extract`).

## Dependencies

```
pip install fpds pandas requests
```

## Required API Keys

- **SAM.gov** — free "Public API Key" from your sam.gov account (Account Details → Public API Key). Set as `SAM_API_KEY`.
  - Powers: the bulk **Entity Extract**, the **Exclusions** Extracts Download API, and the per-record Opportunities / Entity / Federal Hierarchy APIs.
  - **Bare personal key = 10 requests/day** (1,000/day with a SAM role); resets at 00:00 UTC.
  - **Not needed** for the public file extracts (Contract Opportunities, Assistance Listings) or for USAspending.

## Quick Start Examples

See `SKILL.md` for full documentation and code examples. A few highlights:

### Bulk: the whole active-registrant universe (sidesteps the 10/day cap)

```python
from scripts.sam_extract import submit_extract, download_extract, enrich_ueis

submit_extract({"registrationStatus": "A"})          # 1 call — submit the national extract
# ...wait a few minutes for SAM to build the file...
df = download_extract({"registrationStatus": "A"})   # 1 call — download + cache + manifest
```

### Bulk file extracts (Opportunities = no key; Exclusions = your key)

```python
from scripts.file_extracts import load_file_extract, check_exclusions

opps = load_file_extract("contract_opportunities")   # anonymous public S3 — no key, no rate limit
debarred = check_exclusions(award_uei_list)           # flag winners on the SAM debarment list (UEI join)
```

### Query FPDS for DoD contracts

```python
from fpds import fpdsRequest
import asyncio

records = asyncio.run(fpdsRequest(
    AGENCY_NAME="Department of Defense",
    LAST_MOD_DATE="[2024/01/01, 2024/12/31]",
).data())
```

### Look up a single contractor by UEI (per-record fallback)

```python
import os, requests

resp = requests.get("https://api.sam.gov/entity-information/v3/entities", params={
    "api_key": os.environ["SAM_API_KEY"],
    "ueiSAM": "ABC123DEF456",
    "includeSections": "entityRegistration,coreData",
})
entities = resp.json().get("entityData", [])
```

## Documentation Structure

- **SKILL.md** — main skill file: data sources, bulk-vs-API routing, quick start, analysis patterns
- **scripts/sam_extract.py** — bulk Entity Extract (submit/poll/download, caching, partition, normalize) + `enrich_ueis`
- **scripts/file_extracts.py** — SAM File Extracts loader (Opportunities / Exclusions / Assistance) + `check_exclusions` + a last-resort USAspending archive helper
- **scripts/provenance.py** — shared `save_api_response` + `write_extract_manifest` (sha256 manifests)
- **references/sam_api.md** — SAM.gov API reference (Opportunities, Entity Management + bulk Extract, Federal Hierarchy)
- **references/file_extracts.md** — bulk flat-file extracts: access classes, URL patterns, schemas, the federal-procurement data-estate map
- **references/usaspending_api.md** — USAspending.gov API reference + bulk download (last resort) + the ~10k pagination ceiling
- **references/field_mappings.md** — field mappings across FPDS, USAspending, and SAM.gov
- **references/query_patterns.md** — code examples for common queries and investigations (incl. the recently-activated-winner + debarment cross-check)
- **references/data/** — lookup tables for agency codes, NAICS codes, PSC codes, contract action types

## Data Sources

All data sources are public and authoritative:

- **FPDS** — Federal Procurement Data System (managed by GSA) — transaction-level awards
- **USAspending.gov** — official source for U.S. government spending data (no key, no rate limit)
- **SAM.gov** — System for Award Management — entity registrations, opportunities, and exclusions, via both the APIs and GSA/IAE's public flat-file extracts (the `falextracts` S3 bucket)

**Routing:** SAM *search* APIs are capped (10/day on a bare key) → use the **bulk extracts** for
corpus work; **USAspending** has no cap → API-first for awards; **FPDS** for transaction-level
detail. Join across all of them on **UEI**.

## License

This skill documentation is provided as-is for public use. Data accessed through these APIs is
subject to each source's terms of service. The files in `./references/data` are excerpted from
CSISdefense/Lookup-Tables (CC0 license). The FPDS parser is from dherincx92/fpds (MIT license).

## Contributing

Contributions and improvements welcome.

## Support

For issues or questions about:

- The skill itself — file an issue
- FPDS API — see https://www.fpds.gov/wiki/index.php/ATOM_Feed_FAQ
- USAspending API — see https://api.usaspending.gov/
- SAM.gov APIs — see https://open.gsa.gov/api/sam-api/ , https://open.gsa.gov/api/entity-api/
- SAM.gov bulk extracts — see https://open.gsa.gov/api/sam-entity-extracts-api/
