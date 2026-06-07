# Bulk File Extracts — SAM Data Services + USAspending Archive

The **bulk path** for federal procurement data, for when the live APIs are rate-limited or absent.
Implemented in [scripts/file_extracts.py](../scripts/file_extracts.py).

## Table of Contents
1. [When to use this vs the APIs](#when-to-use-this-vs-the-apis)
2. [SAM File Extracts (the `falextracts` bucket)](#sam-file-extracts-the-falextracts-bucket)
3. [Access classes: public vs presigned](#access-classes-public-vs-presigned)
4. [Using the module](#using-the-module)
5. [Exclusions schema (debarment cross-check)](#exclusions-schema-debarment-cross-check)
6. [Contract Opportunities schema](#contract-opportunities-schema)
7. [USAspending award archive (last resort)](#usaspending-award-archive-last-resort)
8. [The federal procurement data estate](#the-federal-procurement-data-estate)

## When to use this vs the APIs

SAM's Entity / Opportunities / Exclusions **search APIs are capped at 10 requests/day** on a bare
key (1,000 with an entity-associated key) — useless for iterating a corpus. GSA/IAE also publishes
most of those datasets as **daily flat files** on a public S3 bucket: no key, no rate limit, one
download ≈ the whole dataset. **For bulk or cross-reference work, prefer the flat files.** Reserve
the APIs for single-record lookups (and the async Entity Extract API when you want clean JSON).

USAspending is the exception: its API has **no rate limit**, so for awards you query the API (or use
FPDS for transaction-level) — the bulk award archive is a last resort (see below).

## SAM File Extracts (the `falextracts` bucket)

Base: `https://falextracts.s3.amazonaws.com/`. Bucket *listing* is disabled, so date-partitioned
files are found by HEAD-walking back from today (the module does this automatically).

| Dataset (module key) | Path pattern | Cadence | Format | ~Size | Join key |
|---|---|---|---|---|---|
| `contract_opportunities` | `Contract Opportunities/datagov/ContractOpportunitiesFullCSV.csv` | daily, **stable name** | CSV | 218 MB | NoticeId; awardee **name** (no UEI) |
| `assistance_listings_datagov` | `Assistance Listings/datagov/{YYYY}/{MM-Mon}/AssistanceListings_DataGov_PUBLIC_WEEKLY_{YYYYMMDD}.csv` | weekly | CSV | 9 MB | program # (CFDA) |
| `assistance_listings_grantsgov` | `Assistance Listings/grantsgov/{YYYY}/{MM-Mon}/AssistanceListings_GrantsGov_PUBLIC_DAILY_{YYYYMMDD}.csv` | daily | CSV | 0.4 MB | program # |
| `exclusions` | `Exclusions/Public V2/SAM_Exclusions_Public_Extract_V2_{YYjjj}.ZIP` | daily | ZIP→CSV | 12 MB | **UEI** (firms), name (individuals) |
| `entity_registration` | `Entity Registration/Public V2/SAM_PUBLIC_[UTF-8_]MONTHLY_V2_{YYYYMMDD}.ZIP` | monthly | ZIP→pipe-delim | large | UEI |

**Date conventions:** `{YYYYMMDD}` = `20260607`; `{MM-Mon}` folder = `06-Jun`; `{YYjjj}` = Julian
(`26158` = day 158 of 2026 = 2026-06-07). `date +%y%j` / `strftime('%y%j')` builds the Julian stamp.

> **Entity note:** the monthly entity ZIP is the same universe as the Entity API, but pipe-delimited
> and gated. **Prefer the async Entity Extract API** (`sam_extract.pull_entity_extract` /
> `submit_extract`) — cleaner JSON, already normalized. See [sam_api.md](sam_api.md).

## Access classes: public vs gated

The bucket subfolder tells you how to fetch it:

- **`…/datagov/` or `…/grantsgov/` → PUBLIC.** Anonymous static URL, plain GET. No key, no cap. (Opportunities, Assistance Listings.)
- **`…/Public V2/` → GATED** (the "person icon" datasets: **Exclusions, Entity**). The S3 objects aren't anonymously readable. "Public" = public *record*, not anonymous *access*. Two ways in:
  - **api_key route (automatable — preferred):** the IAE **Extracts Download API** —
    `GET https://api.sam.gov/data-services/v1/extracts?api_key=<KEY>&fileType=EXCLUSION&date=MM/DD/YYYY` —
    returns the ZIP **synchronously in one GET** (server-side presigning). Verified live for
    `EXCLUSION`; works with a non-federal personal **Public API Key**; counts against the **10/day**
    cap. The module uses this automatically for `exclusions` when `SAM_API_KEY` is set.
  - **presigned URL (no quota — manual):** sam.gov mints a ~45-min presigned S3 URL when you click
    Download while logged in. Grab it from the browser **Network tab** (it carries `X-Amz-Signature`)
    and pass it as `presigned_url=`. Use this to avoid spending a daily call.

> **You cannot mint the presigned URL yourself from the api_key.** The signature is AWS SigV4 keyed
> on GSA's AWS *secret*, which you never possess (the URL exposes only the public Access Key ID). The
> api_key only works against api.sam.gov endpoints that presign **server-side**. Signatures are
> **never** written to provenance manifests.

(Entity: the monthly ZIP is reachable the same way via `fileType=ENTITY`, but **prefer the JSON Entity
Extract API** — `sam_extract.submit_extract`/`pull_entity_extract` — cleaner and already normalized.)

## Using the module

```python
from scripts.file_extracts import (download_file_extract, load_file_extract,
                                    check_exclusions, usaspending_award_archive)

# Public: resolves the URL (stable, or latest available date) and caches under references/data/sam_extract/
opps = load_file_extract("contract_opportunities")          # -> DataFrame (77k active notices)
al   = load_file_extract("assistance_listings_datagov")     # -> latest weekly program catalog

# Exclusions — api_key route (automatable): set SAM_API_KEY and call; one GET returns the ZIP (1 call)
excl = load_file_extract("exclusions")
# ...or no-quota route: pass a browser-grabbed presigned URL instead (afterwards the cache is reused)
# excl = load_file_extract("exclusions", presigned_url="https://falextracts.s3.amazonaws.com/Exclusions/...X-Amz-Signature=...")

# Cross-check a list of award-winner UEIs against the debarment list (cache-first, 0 calls once cached)
flagged = check_exclusions(awards_df["recipient_uei"].dropna().tolist())
```

Caching: a fresh copy (< `refresh_after_days`, default 1) is reused with no network call — so files
you've already downloaded are picked up automatically. Each download writes a sha256 + `Last-Modified`
manifest sidecar (reusing `provenance.write_extract_manifest`). Encoding is handled automatically
(these CSVs are usually **Windows-1252**, not UTF-8).

**Refresh behavior (what happens tomorrow).** `_find_cache` reuses a file while
`(now - mtime).days <= refresh_after_days`. With the default `1`, a file is reused **today and
tomorrow**, then re-fetched once it's ≥48 h old. Pass `refresh_after_days=0` to force a daily-fresh
pull. On a forced refresh: public datasets re-download (date-partitioned ones HEAD-walk to the new
date, leaving older dated files in the cache — prune occasionally); **`exclusions` auto-refreshes via
the api_key route** if `SAM_API_KEY` is set (else it asks for a fresh presigned URL). USAspending
archive calls aren't cached — each call re-resolves the current URL live.

## Exclusions schema (debarment cross-check)

The Exclusions V2 extract is the parties barred from federal awards — a prime fraud/integrity signal.
**167,578 rows, 31 columns.** Key fields: `Classification` (Individual / Firm / Special Entity
Designation / Vessel), `Name`, `Unique Entity ID`, `Excluding Agency`, `Exclusion Type`,
`Active Date`, `Termination Date`, `Record Status`, `Cross-Reference`, `CAGE`.

Joinability:
- **UEI is populated on ~28% of rows — firms/entities only.** Individuals (≈79% of records) have no
  UEI → match by name (out of scope for `check_exclusions`, which joins on UEI).
- **A single UEI can carry multiple exclusion records** (e.g. a firm + its DBA / related entity);
  `check_exclusions` returns all of them. The `Cross-Reference` field links related records — useful
  for mapping shell/owner networks.
- Use `Active Date`/`Termination Date` to test whether a party was excluded **at the time it won an
  award** (compare to the award date from USAspending/FPDS).

## Contract Opportunities schema

The bulk opportunities CSV — what the government is putting out to bid. **Active notices only**
(closed/inactive go to a separate "Archived Data" folder); **77,683 rows, 47 columns**.

- Notice lifecycle in `Type`: Combined Synopsis/Solicitation + Solicitation (~45k = **open for bid**),
  Award Notice (~12k), Presolicitation, Sources Sought, Special Notice, etc.
- Useful columns: `NoticeId`, `Title`, `Sol#`, `Department/Ind.Agency`/`Sub-Tier`/`Office`,
  `NaicsCode`, `ClassificationCode` (PSC), `SetASide`, `PostedDate`, `ResponseDeadLine`, place-of-
  performance `Pop*`, `PrimaryContact*` (public contracting-officer name/email/phone), `Link`,
  `Description` (5000 chars).
- **Award notices** carry `Awardee` + `Award$` + `AwardDate` + `AwardNumber` — but `Awardee` is a
  free-text `Name City State Zip` string, **no UEI**. To join opportunities/award-notices to the
  entity extract you must name-match; for clean UEI award joins use USAspending/FPDS instead.
- Date skew: "active" ≠ recent — ~81% of `PostedDate` is 2025–2026, with a thin tail back to 2008
  (long-lived open notices). Treat it as a current-state snapshot, not a time series.

## USAspending award archive (last resort)

⚠️ **USAspending's API has no key and no rate limit**, so this is almost never the right tool.
- Targeted slice → `spending_by_award` API (paginate; ~10k-result ceiling per query — subdivide by
  agency/quarter if you exceed it). See [usaspending_api.md](usaspending_api.md).
- Transaction-level detail → **FPDS** (`fpds` library), usually better for that.
- Whole-FY/agency offline mirror → the archive, via `usaspending_award_archive(fiscal_year, ...)`.

Mechanics: `GET https://api.usaspending.gov/api/v2/bulk_download/list_monthly_files/?agency=all&fiscal_year=YYYY&type=contracts|assistance`
returns the file URL at `https://files.usaspending.gov/award_data_archive/FY{YYYY}_All_{Contracts|Assistance}_Full_{YYYYMMDD}.zip`.
**Verified FY2025:** contracts **1.91 GB**, assistance **1.48 GB** (zipped; ~10–20 GB raw each). The
module returns URL + size by default and only downloads when `download=True` (so you don't pull ~2 GB
by accident).

## The federal procurement data estate

| Layer | Source | Access | Rate limit | Bulk path | Join key |
|---|---|---|---|---|---|
| **Entities** (who they are) | SAM Entity API | free key | 10–1,000/day | async Extract API → ~745k JSON (have it) | **UEI** |
| **Opportunities** (what's bid) | SAM Opportunities API | free key | 10–1,000/day | `falextracts` CSV (218 MB, active) | NoticeId; awardee name |
| **Exclusions** (who's barred) | SAM Exclusions | api_key *or* presigned | 10/day (api_key route) | Extracts API ZIP, or `falextracts` presigned (daily) | **UEI** (firms) / name |
| **Assistance programs** | SAM Assistance Listings | anonymous | — | `falextracts` CSV (weekly/daily) | CFDA/program # |
| **Awards** (who won, $) | FPDS / USAspending | none | **none** | USAspending archive (GB) — last resort | **UEI** |

Everything joins on **UEI** except the opportunities awardee field (name) and individual exclusions
(name). The investigative spine: **Opportunities → Awards (USAspending/FPDS) → Entities (SAM extract)
→ Exclusions** — see the worked example in [query_patterns.md](query_patterns.md).
