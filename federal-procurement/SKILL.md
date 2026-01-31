---
name: federal-procurement
description: "Query, analyze, and build tools for federal contract and spending data from FPDS (Federal Procurement Data System), USAspending.gov, and SAM.gov APIs (Opportunities, Entity Management, Federal Hierarchy). Use when working with federal procurement data, government contracts, agency spending, FPDS ATOM feeds, USAspending API, SAM.gov APIs, or analyzing contract awards. Covers: (1) Querying FPDS ATOM feed via the fpds Python library, (2) Querying USAspending REST API, (3) Analyzing contract data with pandas, (4) Looking up agency codes, NAICS codes, PSC codes, and contract action types, (5) Building or extending federal procurement analysis tools, (6) Querying SAM.gov APIs for opportunities, entity registrations, and org hierarchy."
---

# Federal Procurement Data Toolkit

## Data Provenance

**MANDATORY: Every API call must save its raw response to `data/raw/` in the project directory before any analysis.** Use the `save_api_response()` helper below. Never analyze data that hasn't been persisted first.

```python
import json, os, time
from pathlib import Path

def save_api_response(source: str, params: dict, data, subdir: str = ""):
    """Save raw API response with provenance metadata. Always call this before analysis."""
    base = Path(os.environ.get("FPDS_DATA_DIR", "data/raw"))
    raw_dir = base / subdir if subdir else base
    raw_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    filename = f"{source}_{ts}.json"
    payload = {
        "source": source,
        "query_params": params,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "record_count": len(data) if isinstance(data, list) else 1,
        "data": data
    }
    path = raw_dir / filename
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Saved {path} ({len(data) if isinstance(data, list) else 1} records)")
    return path
```

Override save directory with `FPDS_DATA_DIR` env var. Default: `./data/raw/`.

## Data Sources

Three primary sources for federal contract data:

| Source | Best For | Access |
|--------|----------|--------|
| **FPDS ATOM Feed** | Transaction-level detail, modifications, specific PIIDs, recent data | `fpds` Python library |
| **USAspending API** | Aggregations, fiscal year summaries, complex multi-criteria filters, keyword search | REST API (no auth) |
| **SAM.gov APIs** | Contract opportunities/solicitations, entity registrations, org hierarchy | REST API (requires free API key) |

## Quick Start

### FPDS (via fpds library)

```python
from fpds import fpdsRequest
import asyncio, pandas as pd

request = fpdsRequest(
    AGENCY_NAME="Department of Defense",
    LAST_MOD_DATE="[2024/01/01, 2024/12/31]"  # YYYY/MM/DD with slashes
)
records = asyncio.run(request.data())
save_api_response("fpds", {"agency": "DoD", "dates": "2024"}, records)
df = pd.DataFrame(records)
```

FPDS dates use `YYYY/MM/DD` (forward slashes). Brackets `[]` = inclusive, parens `()` = exclusive.

### USAspending API

```python
import requests, pandas as pd

response = requests.post(
    "https://api.usaspending.gov/api/v2/search/spending_by_award/",
    json={
        "filters": {
            "time_period": [{"start_date": "2024-01-01", "end_date": "2024-12-31"}],
            "agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of Defense"}],
            "award_type_codes": ["A", "B", "C", "D"]  # Contracts only
        },
        "fields": ["Award ID", "Recipient Name", "Award Amount", "Description"],
        "limit": 100,
        "sort": "Award Amount",
        "order": "desc"
    }
)
results = response.json().get("results", [])
save_api_response("usaspending", {"agency": "DoD", "dates": "2024"}, results)
df = pd.DataFrame(results)
```

Federal fiscal year: Oct 1 to Sep 30. FY2024 = `2023-10-01` to `2024-09-30`.

### SAM.gov Opportunities

```python
import os, requests

SAM_API_KEY = os.environ["SAM_API_KEY"]

params = {
    "api_key": SAM_API_KEY,
    "postedFrom": "01/01/2024",   # MM/dd/yyyy format
    "postedTo": "06/30/2024",
    "keyword": "cybersecurity",
    "ptype": "o",                  # Solicitations
    "limit": 100,
}
resp = requests.get("https://api.sam.gov/opportunities/v2/search", params=params)
opps = resp.json().get("opportunitiesData", [])
save_api_response("sam_opportunities", params, opps, subdir="sam")
```

### SAM.gov Entity Lookup

```python
params = {
    "api_key": SAM_API_KEY,
    "ueiSAM": "ABC123DEF456",
    "includeSections": "entityRegistration,coreData,assertions",
}
resp = requests.get("https://api.sam.gov/entity-information/v3/entities", params=params)
entities = resp.json().get("entityData", [])
save_api_response("sam_entity", params, entities, subdir="sam")
```

### Data Cleanup (FPDS)

FPDS returns OBLIGATED_AMOUNT as strings like "$1,234.56":

```python
df["OBLIGATED_AMOUNT"] = df["OBLIGATED_AMOUNT"].replace(r'[$,]', '', regex=True).astype(float)
```

## Common FPDS Parameters

```python
fpdsRequest(AGENCY_CODE="7504")                    # By 4-digit agency code
fpdsRequest(AGENCY_NAME="Department of the Army")  # By name
fpdsRequest(PIID="W52P1J24C0019")                  # Specific contract
fpdsRequest(VENDOR_ADDRESS_STATE_CODE="CA")         # Vendor state
fpdsRequest(LAST_MOD_DATE="[2024/01/01, 2024/12/31]")  # Date range
fpdsRequest(PRINCIPAL_NAICS_CODE="541511")          # NAICS code
fpdsRequest(PRODUCT_OR_SERVICE_CODE="R617")         # PSC code
```

Key fields: PIID, AGENCY_NAME, AGENCY_CODE, OBLIGATED_AMOUNT, UEI_NAME, VENDOR_ADDRESS_STATE_NAME, PRINCIPAL_NAICS_CODE, PRODUCT_OR_SERVICE_CODE, SIGNED_DATE, DESCRIPTION_OF_REQUIREMENT, MODIFICATION_NUMBER

The library validates 601 fields with regex patterns. For the full list, see the fpds library's `fields.json`.

## USAspending Filter Structure

```python
filters = {
    "time_period": [{"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}],
    "agencies": [{"type": "awarding|funding", "tier": "toptier|subtier", "name": "..."}],
    "award_type_codes": ["A","B","C","D"],  # Contracts
    "award_amounts": [{"lower_bound": 1000000, "upper_bound": 5000000}],
    "naics_codes": ["541511"],
    "psc_codes": ["R617"],
    "keywords": ["cybersecurity"],
    "recipient_locations": [{"country": "USA", "state": "MA"}],
    "place_of_performance_locations": [{"country": "USA", "state": "MA"}],
}
```

## Analysis Patterns

### Aggregate by dimension

```python
summary = df.groupby("AGENCY_NAME")["OBLIGATED_AMOUNT"].agg(
    count="count", total="sum", avg="mean"
).sort_values("total", ascending=False)
```

### Top vendors

```python
top = df.groupby("UEI_NAME")["OBLIGATED_AMOUNT"].agg(
    contracts="count", total="sum"
).sort_values("total", ascending=False).head(20)
```

### Vendor concentration

```python
vendor_totals = df.groupby("UEI_NAME")["OBLIGATED_AMOUNT"].sum().sort_values(ascending=False)
print(f"Top 5 control {vendor_totals.head(5).sum() / vendor_totals.sum():.1%}")
```

## Reference Files

### Field Mappings
For FPDS, USAspending, and SAM.gov field mappings, read [references/field_mappings.md](references/field_mappings.md).

### USAspending API Details
For full API endpoint reference, filter structure, award type codes, pagination, and response fields, read [references/usaspending_api.md](references/usaspending_api.md).

### SAM.gov API Details
For SAM.gov Opportunities, Entity Management, and Federal Hierarchy API reference, read [references/sam_api.md](references/sam_api.md).

### Query Patterns
For detailed code examples covering FPDS queries, USAspending queries, SAM.gov queries, data cleanup, analysis, investigative patterns, and cross-source comparison, read [references/query_patterns.md](references/query_patterns.md).

### Lookup Tables (references/data/)

CSISdefense/Lookup-Tables data (CC0 license, cite CSIS DIIG if used). Use Grep to search these — do not load entire files into context.

- **[references/data/agency_codes.csv](references/data/agency_codes.csv)** — 1,506 agency codes -> names, Customer/SubCustomer grouping, IsDefense flag
  - Columns: AgencyID, AgencyIDtext, Customer, SubCustomer, IsDefense
  - Search: `grep "7504" references/data/agency_codes.csv`

- **[references/data/naics_codes.csv](references/data/naics_codes.csv)** — 1,632 NAICS codes -> descriptions, 2/3-digit sector codes, PDT categories
  - Columns: Unseperated, principalnaicscode, principalnaicscodeText, principalNAICS2DigitCode, principalNAICS3DigitCode, PDTcategory
  - Search: `grep "541511" references/data/naics_codes.csv`

- **[references/data/psc_codes.csv](references/data/psc_codes.csv)** — 3,583 PSC codes -> descriptions, Products/Services classification, area grouping
  - Columns: ProductOrServiceCode, ProductOrServiceCodeText, Simple, IsService, ProductOrServiceArea, ProductServiceOrRnDarea
  - Search: `grep "R617" references/data/psc_codes.csv`

- **[references/data/contract_action_types.csv](references/data/contract_action_types.csv)** — 27 contract action type codes -> categories (BOA, BPA, DO, DCA, FSS, IDC, PO, codes 1-9, A-G)
  - Columns: ContractActionTypeLabel, ContractActionTypeCode, ContractActionTypeCategory

## Dependencies

```
fpds>=1.5.0      # FPDS ATOM feed parser
pandas>=2.0.0    # Data manipulation
requests>=2.31.0 # HTTP for USAspending and SAM.gov APIs
```

Install: `pip install fpds pandas requests`

**Environment variables:**
- `SAM_API_KEY` — Required for SAM.gov APIs. Get a free key at https://sam.gov/content/entity-information
- `FPDS_DATA_DIR` — Override default `data/raw/` save directory (optional)
