# SAM.gov API Reference

Three SAM.gov APIs for federal procurement work: Opportunities (solicitations/notices), Entity Management (contractor registrations), and Federal Hierarchy (agency/org resolution).

## Authentication

All SAM.gov APIs require a free API key from https://sam.gov/content/entity-information.

Pass the key via `api_key` query parameter or `X-Api-Key` header. Store in `SAM_API_KEY` environment variable:

```python
import os, requests

SAM_API_KEY = os.environ["SAM_API_KEY"]
```

**Rate limits:**
| Tier | Requests/day |
|------|-------------|
| Unregistered (personal key) | 10 |
| Registered (system account) | 1,000 |
| Federal (.gov/.mil email) | 1,000 |

Rate-limited responses return HTTP 429 with `Retry-After` header.

## Opportunities API

Search contract solicitations, notices, and awards.

**Endpoint:** `GET https://api.sam.gov/opportunities/v2/search`

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_key` | string | API key (required) |
| `postedFrom` | string | Start date `MM/dd/yyyy` (required with postedTo) |
| `postedTo` | string | End date `MM/dd/yyyy` (required with postedFrom) |
| `keyword` | string | Full-text search across title and description |
| `naics` | string | NAICS code filter |
| `ptype` | string | Procurement type: `o` (solicitation), `k` (combined), `p` (presolicitation), `r` (sources sought), `s` (special notice), `g` (sale of surplus), `i` (intent to bundle), `a` (award notice) |
| `solnum` | string | Solicitation number |
| `noticeid` | string | Specific notice ID |
| `deptname` | string | Department name |
| `subtier` | string | Sub-tier agency name |
| `state` | string | Place of performance state (2-letter code) |
| `zip` | string | Place of performance ZIP |
| `typeOfSetAside` | string | Set-aside type: `SBA`, `SBP`, `8A`, `8AN`, `HZC`, `HZS`, `SDVOSBC`, `SDVOSBS`, `WOSB`, `WOSBSS`, `EDWOSB`, `EDWOSBSS`, `VSA`, `VSB` |
| `limit` | int | Results per page (default 10, max 1000) |
| `offset` | int | Pagination offset (0-based) |

**Date constraints:** Max 1-year range per request. Dates use `MM/dd/yyyy` format (not ISO).

### Response Structure

```json
{
  "totalRecords": 150,
  "opportunitiesData": [
    {
      "noticeId": "abc123",
      "title": "IT Support Services",
      "solicitationNumber": "W911NF-24-R-0001",
      "department": "Department of Defense",
      "subTier": "Department of the Army",
      "office": "ACC-APG",
      "postedDate": "2024-06-15",
      "type": "Solicitation",
      "baseType": "Solicitation",
      "archiveType": "autocustom",
      "archiveDate": "2024-09-15",
      "typeOfSetAsideDescription": "Total Small Business Set-Aside",
      "responseDeadLine": "2024-07-15T14:00:00-04:00",
      "naicsCode": "541511",
      "classificationCode": "D301",
      "active": "Yes",
      "description": "https://api.sam.gov/opportunities/v2/search?...",
      "organizationType": "OFFICE",
      "uiLink": "https://sam.gov/opp/abc123/view",
      "links": [
        {"rel": "self", "href": "https://api.sam.gov/opportunities/v2/search?noticeid=abc123"}
      ],
      "pointOfContact": [
        {"fullName": "Jane Smith", "email": "jane.smith@army.mil", "phone": "555-0100", "type": "primary"}
      ],
      "award": {
        "date": "2024-08-01",
        "number": "W911NF-24-C-0001",
        "amount": "1500000.00",
        "awardee": {
          "name": "Contractor Inc.",
          "ueiSAM": "ABC123DEF456",
          "location": {"city": {"code": "12345", "name": "Boston"}, "state": {"code": "MA"}, "zip": "02101", "country": {"code": "USA"}}
        }
      }
    }
  ]
}
```

### Code Example

```python
import os, requests

SAM_API_KEY = os.environ["SAM_API_KEY"]

params = {
    "api_key": SAM_API_KEY,
    "postedFrom": "01/01/2024",
    "postedTo": "06/30/2024",
    "keyword": "cybersecurity",
    "ptype": "o",
    "limit": 100,
    "offset": 0,
}
resp = requests.get("https://api.sam.gov/opportunities/v2/search", params=params)
data = resp.json()
opps = data.get("opportunitiesData", [])
save_api_response("sam_opportunities", params, opps, subdir="sam")

# Paginate
while len(opps) < data.get("totalRecords", 0):
    params["offset"] += params["limit"]
    resp = requests.get("https://api.sam.gov/opportunities/v2/search", params=params)
    page = resp.json().get("opportunitiesData", [])
    if not page:
        break
    opps.extend(page)
save_api_response("sam_opportunities_full", params, opps, subdir="sam")
```

### Date Chunking for Large Ranges

The 1-year max means multi-year searches need chunking:

```python
from datetime import datetime, timedelta

def date_chunks(start: str, end: str, days: int = 365):
    """Yield (from, to) tuples in MM/dd/yyyy format, each <=days apart."""
    fmt_in, fmt_out = "%Y-%m-%d", "%m/%d/%Y"
    s = datetime.strptime(start, fmt_in)
    e = datetime.strptime(end, fmt_in)
    while s < e:
        chunk_end = min(s + timedelta(days=days - 1), e)
        yield s.strftime(fmt_out), chunk_end.strftime(fmt_out)
        s = chunk_end + timedelta(days=1)

# Usage: search 2022-2024
all_opps = []
for fr, to in date_chunks("2022-01-01", "2024-12-31"):
    params["postedFrom"], params["postedTo"] = fr, to
    resp = requests.get("https://api.sam.gov/opportunities/v2/search", params=params)
    all_opps.extend(resp.json().get("opportunitiesData", []))
save_api_response("sam_opportunities_multiyear", {"range": "2022-2024"}, all_opps, subdir="sam")
```

## Entity Management API

Look up SAM.gov entity registrations (contractors, grantees). Authoritative source for UEI, CAGE code, and registration status.

> **Doing bulk work or cross-referencing a list of UEIs?** Don't loop this per-UEI endpoint — it's
> capped at 10–1,000 requests/day. Use the **[Entity Extract API (bulk)](#entity-extract-api-bulk--the-default-for-bulk--cross-reference-work)**
> below (one async job ≈ the whole public dataset). The per-UEI calls in this section are the
> single-entity / cache-miss fallback.

**Endpoint:** `GET https://api.sam.gov/entity-information/v3/entities`

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_key` | string | API key (required) |
| `ueiSAM` | string | Unique Entity ID |
| `cageCode` | string | CAGE/NCAGE code |
| `legalBusinessName` | string | Legal name (exact or partial match) |
| `dbaName` | string | Doing-business-as name |
| `registrationStatus` | string | `A` (active), `E` (expired), `W` (work-in-progress) |
| `purposeOfRegistrationCode` | string | `Z1` (federal assistance), `Z2` (contracts), `Z5` (both) |
| `naicsCode` | string | NAICS code |
| `primaryNaics` | string | Primary NAICS code (Y/N flag when combined with naicsCode) |
| `stateCode` | string | 2-letter state code (per-UEI search; the **bulk extract** uses `physicalAddressProvinceOrStateCode` instead) |
| `zipCode` | string | ZIP code |
| `countryCode` | string | 3-letter country code |
| `samExtractCode` | string | `A` (all), `E` (entity), `1`-`4` (specific extracts) |
| `includeSections` | string | Comma-separated: `entityRegistration`, `coreData`, `assertions`, `repsAndCerts`, `pointsOfContact` |
| `page` | int | Page number (0-based) |
| `size` | int | Results per page (default 10, max 1000) |

### Response Structure

```json
{
  "totalRecords": 1,
  "entityData": [
    {
      "entityRegistration": {
        "samRegistered": "Yes",
        "ueiSAM": "ABC123DEF456",
        "cageCode": "1A2B3",
        "legalBusinessName": "Contractor Inc.",
        "dbaName": "Contractor",
        "registrationStatus": "Active",
        "registrationDate": "2020-01-15",
        "expirationDate": "2025-01-15",
        "purposeOfRegistrationCode": "Z2",
        "purposeOfRegistrationDesc": "All Awards"
      },
      "coreData": {
        "entityInformation": {
          "entityURL": "https://contractorinc.com",
          "entityStartDate": "2010-05-01"
        },
        "physicalAddress": {
          "addressLine1": "123 Main St",
          "city": "Boston",
          "stateOrProvinceCode": "MA",
          "zipCode": "02101",
          "countryCode": "USA"
        },
        "mailingAddress": { ... },
        "businessTypes": {
          "businessTypeList": [
            {"businessTypeCode": "2X", "businessTypeDescription": "For Profit Organization"}
          ],
          "sbaBusinessTypeList": []
        },
        "financialInformation": {
          "creditCardUsage": "Y",
          "debtSubjectToOffset": "N"
        }
      },
      "assertions": {
        "goodsAndServices": {
          "primaryNaics": "541511",
          "naicsList": [
            {"naicsCode": "541511", "naicsDescription": "Custom Computer Programming Services", "sbaSmallBusiness": "Y"}
          ],
          "pscList": [
            {"pscCode": "D301", "pscDescription": "IT and Telecom - Facility Operation and Maintenance"}
          ]
        }
      }
    }
  ]
}
```

### Code Example

```python
import os, requests

SAM_API_KEY = os.environ["SAM_API_KEY"]

# Look up entity by UEI
params = {
    "api_key": SAM_API_KEY,
    "ueiSAM": "ABC123DEF456",
    "includeSections": "entityRegistration,coreData,assertions",
}
resp = requests.get("https://api.sam.gov/entity-information/v3/entities", params=params)
entities = resp.json().get("entityData", [])
save_api_response("sam_entity", params, entities, subdir="sam")

# Look up by name
params = {
    "api_key": SAM_API_KEY,
    "legalBusinessName": "Raytheon",
    "registrationStatus": "A",
    "includeSections": "entityRegistration,coreData",
}
resp = requests.get("https://api.sam.gov/entity-information/v3/entities", params=params)
entities = resp.json().get("entityData", [])
save_api_response("sam_entity_search", params, entities, subdir="sam")
```

### Name Matching Tips

The Entity API does partial matching on `legalBusinessName`, but results include many variants. Filter by similarity:

```python
from difflib import SequenceMatcher

def best_entity_match(name: str, entities: list, threshold: float = 0.6) -> dict | None:
    """Find the best-matching entity by legal business name."""
    best, best_score = None, 0
    target = name.upper().strip()
    for e in entities:
        reg = e.get("entityRegistration", {})
        candidate = reg.get("legalBusinessName", "").upper().strip()
        score = SequenceMatcher(None, target, candidate).ratio()
        if score > best_score:
            best, best_score = e, score
    return best if best_score >= threshold else None
```

## Entity Extract API (bulk) — the default for bulk / cross-reference work

The per-UEI lookups above are rate-limited to **10 requests/day** (bare key) or **1,000/day**
(entity-associated key) — far too few to iterate over a corpus of award recipients. The *same*
Entity Management endpoint doubles as an asynchronous **Extract API**: add a `format` parameter and
it returns a downloadable file of up to the **first 1,000,000 records**. The active-registrant
universe is well under 1M, so one extract ≈ the entire public dataset. **Use the extract for any
bulk or cross-reference operation; per-UEI lookups are now a single-entity / cache-miss fallback.**

Don't hand-roll the async dance — call the module. **Pull the whole active-registrant universe in
one job** (it's under the 1M cap), then enrich from that cache:

```python
from scripts.sam_extract import submit_extract, download_extract, pull_entity_extract, enrich_ueis

# QUOTA-SAFE two-step (recommended for the national pull on a 10/day key) — 2 calls total:
submit_extract({"registrationStatus": "A"})          # 1 call: submit ALL active registrants, token saved
# … wait a few minutes for SAM to build the file (or until the optional email notification) …
df = download_extract({"registrationStatus": "A"})   # 1 call: grab the finished file, cache + manifest

# One-shot convenience (submits AND polls in a loop — only when you have quota to spare):
df = pull_entity_extract({"registrationStatus": "A", "physicalAddressProvinceOrStateCode": "VT"})

# Enrich a list of UEIs (e.g. from USAspending) — cache-first, live per-UEI only for misses
enriched = enrich_ueis(["ABC123DEF456", "GHI789JKL012"])
```

One national extract (~600–700k active entities, well under 1M) replaces the entire per-UEI grind,
and `enrich_ueis` then serves your award UEIs straight from that cached file with zero further calls.

### The async flow (verified live against api.sam.gov, 2026-06)

The GSA docs describe this imperfectly; the steps below are what the API **actually does**:

1. **Submit** — `GET /entity-information/v3/entities` with `format=JSON` (or `CSV`) plus your
   filters. Returns HTTP 200 with a **plain-text** body (not a JSON object) carrying a token:

   ```
   Extract File will be available for download with url:
   https://api.sam.gov/entity-information/v3/download-entities?api_key=…&token=zJktKnaazg in some time.
   ```

2. **Poll/download** — **`GET`** the download URL (`download-entities?api_key=…&token=<token>`).
   ⚠️ The endpoint is **GET**, not POST — a POST returns `415 UNSUPPORTED_MEDIA_TYPE`.
   - **Still generating:** HTTP `400` — `{"message":"The requested JSON or CSV file is not generated yet. Please try again later."}`
   - **Ready:** HTTP `200` with the binary file. **Verified live (2026-06-07):** a `format=JSON` public extract downloads as a **bare gzip stream** (`.gz`, magic `1f 8b`) that decompresses directly to a JSON array — *not* a `.zip`. (GSA's docs describe a `.zip` of `.json.gz`/`.csv.gz` members; CSV exports or federal keys may differ.) The module sniffs the magic bytes (`PK`=zip, `1f 8b`=gzip, else plain) and decompresses whichever it gets, so it's robust to both.
   - **Expired token:** HTTP `400` — `"…token is expired."`
   - **Over the cap:** HTTP `400` — `"Total Number of Records: <n> exceeded the maximum allowable limit: 1000000…"`

3. **Cache + provenance** — the raw download is saved to
   `references/data/sam_extract/sam_entities_<filter-hash>_<YYYYMMDD>.<ext>` and reused unless older
   than `refresh_after_days` (default 7). A manifest sidecar (`…manifest.json`) records the resolved
   URL, params, timestamp, record count, and sha256.

**Verified end-to-end (2026-06-07):** a national `{"registrationStatus": "A"}` extract returned a
137 MB gzip → **750,756 records** (744,227 rows after dropping null/duplicate UEIs), in **4 API
calls total** (1 submit + 3 download attempts, since the file took ~25 min to build). The file took
a while to generate — hence submit/wait/download, not a tight poll loop.

### ⚠️ Every poll counts against the daily cap — use submit/download, not a poll loop

Each download poll is a billable request. A bare **10/day** key is genuinely tight: a national file
takes minutes to build, so a naive `pull_entity_extract` poll loop can spend the whole day's quota
*before the file is even ready*, after which you get `429 code 900804 "Message throttled out"` with
`Retry-After` / `nextAccessTime` pointing at the **next 00:00 UTC** (the daily reset).

The fix is to **decouple submit from download** so the whole national pull costs **2 calls**:

1. `submit_extract(filters)` — one call; SAM returns a token (the module saves it to disk).
2. Wait for the file to finish building (minutes; SAM can also email a notification).
3. `download_extract(filters)` — one call; resolves the saved token and grabs the finished file.

`pull_entity_extract` (which polls in a loop) is fine on a 1,000/day entity-associated key or for a
small slice that builds quickly, but on a 10/day key prefer the two-step path. The whole point of
the extract is that *one* job replaces thousands of per-UEI calls — if you're tripping the cap, look
for a per-UEI loop that should be `enrich_ueis()`.

### Extract filter parameters (verified, case-sensitive)

| Parameter | Notes |
|-----------|-------|
| `format` | `JSON` or `CSV` — presence switches the endpoint into async extract mode |
| `registrationStatus` | `A` (active), `E` (expired) |
| `registrationDate` | Single `MM/DD/YYYY` or inclusive range `[MM/DD/YYYY,MM/DD/YYYY]` |
| `activationDate` | Same format — **the tell for freshly-activated entities** |
| `registrationExpirationDate` | Same format (was `expirationDate` in v1) |
| `physicalAddressProvinceOrStateCode` | 2-char state/territory code — **this is the geo filter for the extract** (not `stateCode`) |
| `primaryNaics` / `naicsCode` | 6-digit NAICS |
| `q` | Free-text search |
| `ueiSAM` / `cageCode` | Up to 100 values each |
| `includeSections` | `entityRegistration`, `coreData`, `assertions`, `pointsOfContact`, `repsAndCerts`, `All`, `integrityInformation` |

**includeSections for a non-federal "Read Public" key:** you get name / UEI / CAGE / registration
dates / physical & mailing addresses / business types / NAICS / PSC and POC *name + address*.
Entity **parent/child hierarchy**, security levels, and POC **email/phone/fax** are FOUO-restricted
and require a federal "Read FOUO" key — those fields are absent for a public key, so a parent-
hierarchy column will usually be empty. The module defaults to `entityRegistration,coreData`
(everything needed for entity resolution / shell detection); add `assertions` for NAICS/PSC.

### Handling the 1,000,000-record cap

Active registrants total well under 1M, so a single `registrationStatus=A` extract fits. If a
broader filter set ever exceeds the cap (the 400 above), `pull_entity_extract` auto-partitions by
`physicalAddressProvinceOrStateCode` (every entity has a physical state, yielding ~56 sub-1M
buckets), pulls each, and concatenates + de-dupes on UEI. For an extreme single state, narrow
further with a `registrationDate` window.

### Other bulk datasets: SAM File Extracts

SAM also publishes **Contract Opportunities, Exclusions (debarment), and Assistance Listings** as
daily flat files on a public S3 bucket — the bulk path that sidesteps the 10/day API cap for those
datasets (just as the Entity Extract above does for entities). The entity *monthly* ZIP exists there
too, but the JSON Entity Extract API above is preferred (cleaner, normalized). Full details — URL
patterns, public-vs-presigned access, schemas, and the `scripts/file_extracts.py` loader (incl. a
debarment cross-check) — are in **[file_extracts.md](file_extracts.md)**.

## Federal Hierarchy API

Resolve agency/department names to SAM.gov organization IDs.

**Endpoint:** `GET https://api.sam.gov/prod/federalorganizations/v1/orgs`

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `api_key` | string | API key (required) |
| `fhorgname` | string | Organization name (partial match) |
| `fhorgtype` | string | Type: `DEPARTMENT`, `AGENCY`, `OFFICE` |
| `status` | string | `ACTIVE` or `INACTIVE` |
| `limit` | int | Results per page |
| `offset` | int | Pagination offset |

### Response Structure

```json
{
  "totalrecords": 5,
  "orglist": [
    {
      "fhorgid": 100000000,
      "fhorgname": "Department of Defense",
      "fhorgtype": "DEPARTMENT",
      "status": "ACTIVE",
      "fhparentorgname": null,
      "fhparentorgid": null,
      "agencycode": "9700",
      "oldfpdsofficecode": null,
      "cgac": "097",
      "fhorgnamehistory": null
    }
  ]
}
```

### Code Example

```python
import os, requests

SAM_API_KEY = os.environ["SAM_API_KEY"]

params = {
    "api_key": SAM_API_KEY,
    "fhorgname": "Department of Defense",
    "fhorgtype": "DEPARTMENT",
    "status": "ACTIVE",
}
resp = requests.get("https://api.sam.gov/prod/federalorganizations/v1/orgs", params=params)
orgs = resp.json().get("orglist", [])
save_api_response("sam_fed_hierarchy", params, orgs, subdir="sam")
```

## Date Format Reference

| API | Format | Example |
|-----|--------|---------|
| SAM Opportunities | `MM/dd/yyyy` | `01/15/2024` |
| SAM Entity | ISO dates in responses | `2024-01-15` |
| SAM Fed Hierarchy | N/A | N/A |
| FPDS | `YYYY/MM/DD` | `2024/01/15` |
| USAspending | `YYYY-MM-DD` | `2024-01-15` |

## Rate Limit Handling

```python
import time

def sam_request(url: str, params: dict, source: str = "sam", max_retries: int = 3) -> dict:
    """Make a SAM.gov API request with retry on 429. Saves response before returning."""
    for attempt in range(max_retries):
        resp = requests.get(url, params=params)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            print(f"Rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        # Extract the list payload for saving (varies by endpoint)
        records = data.get("opportunitiesData", data.get("entityData", data.get("orglist", data)))
        save_api_response(source, params, records, subdir="sam")
        return data
    raise RuntimeError(f"Still rate-limited after {max_retries} retries")
```
