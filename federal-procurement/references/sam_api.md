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
| `stateCode` | string | 2-letter state code |
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
