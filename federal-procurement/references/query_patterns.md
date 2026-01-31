# Common Federal Procurement Query Patterns

## Table of Contents

1. [FPDS Library Usage](#fpds-library-usage)
2. [USAspending API Usage](#usaspending-api-usage)
3. [SAM.gov Opportunities Queries](#samgov-opportunities-queries)
4. [SAM.gov Entity Lookups](#samgov-entity-lookups)
5. [Data Cleanup Patterns](#data-cleanup-patterns)
6. [Analysis Patterns](#analysis-patterns)
7. [Investigative Patterns](#investigative-patterns)
8. [Cross-Source Comparison](#cross-source-comparison)

## FPDS Library Usage

### Basic query with the fpds library

```python
from fpds import fpdsRequest
import asyncio
import pandas as pd

request = fpdsRequest(
    AGENCY_NAME="Department of Defense",
    LAST_MOD_DATE="[2024/01/01, 2024/12/31]"
)
records = asyncio.run(request.data())
save_api_response("fpds", {"agency": "DoD", "dates": "2024/01/01-2024/12/31"}, records)
df = pd.DataFrame(records)
```

### Common FPDS parameters

```python
# By agency code (4-digit)
fpdsRequest(AGENCY_CODE="7504")

# By date range (inclusive brackets, exclusive parens)
fpdsRequest(LAST_MOD_DATE="[2024/01/01, 2024/12/31]")

# By contract ID
fpdsRequest(PIID="W52P1J24C0019")

# By vendor state
fpdsRequest(VENDOR_ADDRESS_STATE_CODE="CA")

# Combined filters
fpdsRequest(
    AGENCY_NAME="Department of the Army",
    VENDOR_ADDRESS_STATE_CODE="MA",
    LAST_MOD_DATE="[2024/01/01, 2024/06/30]"
)
```

### FPDS date format

Dates use `YYYY/MM/DD` format (forward slashes, not hyphens).
- Inclusive range: `[2024/01/01, 2024/12/31]`
- Exclusive range: `(2024/01/01, 2024/12/31)`
- Mixed: `[2024/01/01, 2024/12/31)`

### FPDS field list

The library defines 601 fields. Common ones:
- PIID, AGENCY_NAME, AGENCY_CODE, CONTRACTING_AGENCY_NAME
- OBLIGATED_AMOUNT, UEI_NAME, VENDOR_ADDRESS_STATE_NAME
- PRINCIPAL_NAICS_CODE, PRODUCT_OR_SERVICE_CODE
- SIGNED_DATE, AWARD_COMPLETION_DATE, DESCRIPTION_OF_REQUIREMENT
- MODIFICATION_NUMBER, CONTRACT_TYPE, AWARD_STATUS

## USAspending API Usage

### Basic query

```python
import requests
import pandas as pd

url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
payload = {
    "filters": {
        "time_period": [{"start_date": "2024-01-01", "end_date": "2024-12-31"}],
        "agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of Defense"}]
    },
    "fields": ["Award ID", "Recipient Name", "Award Amount", "Description"],
    "limit": 100,
    "sort": "Award Amount",
    "order": "desc"
}
response = requests.post(url, json=payload)
results = response.json().get("results", [])
save_api_response("usaspending", payload["filters"], results)
df = pd.DataFrame(results)
```

### Fiscal year helper

Federal fiscal year runs Oct 1 to Sep 30. FY2024 = Oct 2023 through Sep 2024.

```python
def fiscal_year_dates(fy):
    return {"start_date": f"{fy-1}-10-01", "end_date": f"{fy}-09-30"}

# Usage
filters = {"time_period": [fiscal_year_dates(2024)]}
```

### Contracts only (exclude grants/loans)

```python
filters["award_type_codes"] = ["A", "B", "C", "D"]
```

## SAM.gov Opportunities Queries

### Search by keyword and date range

```python
import os, requests

SAM_API_KEY = os.environ["SAM_API_KEY"]

params = {
    "api_key": SAM_API_KEY,
    "postedFrom": "01/01/2024",   # MM/dd/yyyy
    "postedTo": "06/30/2024",
    "keyword": "cybersecurity",
    "limit": 100,
    "offset": 0,
}
resp = requests.get("https://api.sam.gov/opportunities/v2/search", params=params)
data = resp.json()
opps = data.get("opportunitiesData", [])
save_api_response("sam_opportunities", params, opps, subdir="sam")
```

### Search by NAICS code

```python
params = {
    "api_key": SAM_API_KEY,
    "postedFrom": "01/01/2024",
    "postedTo": "12/31/2024",
    "naics": "541511",
    "ptype": "o",   # Solicitations only
    "limit": 100,
}
resp = requests.get("https://api.sam.gov/opportunities/v2/search", params=params)
opps = resp.json().get("opportunitiesData", [])
save_api_response("sam_opps_naics_541511", params, opps, subdir="sam")
```

### Search by department/agency

```python
params = {
    "api_key": SAM_API_KEY,
    "postedFrom": "01/01/2024",
    "postedTo": "06/30/2024",
    "deptname": "Department of Defense",
    "subtier": "Department of the Army",
    "limit": 100,
}
resp = requests.get("https://api.sam.gov/opportunities/v2/search", params=params)
opps = resp.json().get("opportunitiesData", [])
save_api_response("sam_opps_army", params, opps, subdir="sam")
```

### Paginate through all results

```python
all_opps = []
offset = 0
limit = 100
while True:
    params["offset"] = offset
    params["limit"] = limit
    resp = requests.get("https://api.sam.gov/opportunities/v2/search", params=params)
    data = resp.json()
    page = data.get("opportunitiesData", [])
    if not page:
        break
    all_opps.extend(page)
    if len(all_opps) >= data.get("totalRecords", 0):
        break
    offset += limit
save_api_response("sam_opps_full", params, all_opps, subdir="sam")
```

### Procurement type codes

| Code | Type |
|------|------|
| `o` | Solicitation |
| `k` | Combined synopsis/solicitation |
| `p` | Presolicitation |
| `r` | Sources sought |
| `s` | Special notice |
| `g` | Sale of surplus property |
| `i` | Intent to bundle |
| `a` | Award notice |

## SAM.gov Entity Lookups

### Look up entity by UEI

```python
params = {
    "api_key": SAM_API_KEY,
    "ueiSAM": "ABC123DEF456",
    "includeSections": "entityRegistration,coreData,assertions",
}
resp = requests.get("https://api.sam.gov/entity-information/v3/entities", params=params)
entities = resp.json().get("entityData", [])
save_api_response("sam_entity_uei", params, entities, subdir="sam")
```

### Look up entity by name

```python
params = {
    "api_key": SAM_API_KEY,
    "legalBusinessName": "Raytheon",
    "registrationStatus": "A",
    "includeSections": "entityRegistration,coreData",
    "size": 25,
}
resp = requests.get("https://api.sam.gov/entity-information/v3/entities", params=params)
entities = resp.json().get("entityData", [])
save_api_response("sam_entity_name", params, entities, subdir="sam")
```

### Look up entity by CAGE code

```python
params = {
    "api_key": SAM_API_KEY,
    "cageCode": "1A2B3",
    "includeSections": "entityRegistration,coreData",
}
resp = requests.get("https://api.sam.gov/entity-information/v3/entities", params=params)
entities = resp.json().get("entityData", [])
save_api_response("sam_entity_cage", params, entities, subdir="sam")
```

### Resolve org hierarchy

```python
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

### Find sub-agencies for a department

```python
# First get the department
params = {
    "api_key": SAM_API_KEY,
    "fhorgname": "Department of Defense",
    "fhorgtype": "DEPARTMENT",
    "status": "ACTIVE",
}
resp = requests.get("https://api.sam.gov/prod/federalorganizations/v1/orgs", params=params)
dept = resp.json().get("orglist", [])[0]

# Then get its sub-agencies
params = {
    "api_key": SAM_API_KEY,
    "fhorgname": "",  # empty to get all
    "fhorgtype": "AGENCY",
    "status": "ACTIVE",
    "limit": 100,
}
resp = requests.get("https://api.sam.gov/prod/federalorganizations/v1/orgs", params=params)
agencies = resp.json().get("orglist", [])
dod_agencies = [a for a in agencies if a.get("fhparentorgname") == "Department of Defense"]
save_api_response("sam_dod_subagencies", params, dod_agencies, subdir="sam")
```

## Data Cleanup Patterns

### Currency string to float (FPDS)

FPDS returns OBLIGATED_AMOUNT as strings like "$1,234,567.89":

```python
df["OBLIGATED_AMOUNT"] = (
    df["OBLIGATED_AMOUNT"]
    .replace(r'[$,]', '', regex=True)
    .astype(float)
)
```

### Select useful columns

```python
useful_fields = [
    "PIID", "AGENCY_NAME", "OBLIGATED_AMOUNT",
    "UEI_NAME", "VENDOR_ADDRESS_STATE_NAME",
    "PRINCIPAL_NAICS_CODE", "PRODUCT_OR_SERVICE_CODE",
    "SIGNED_DATE", "DESCRIPTION_OF_REQUIREMENT"
]
df = df[[f for f in useful_fields if f in df.columns]]
```

## Analysis Patterns

### Aggregate spending by dimension

```python
# By agency
agency_summary = df.groupby("AGENCY_NAME")["OBLIGATED_AMOUNT"].agg(
    count="count", total="sum", avg="mean"
).sort_values("total", ascending=False)

# By state
state_summary = df.groupby("VENDOR_ADDRESS_STATE_NAME")["OBLIGATED_AMOUNT"].agg(
    count="count", total="sum"
).sort_values("total", ascending=False)

# By NAICS code
naics_summary = df.groupby("PRINCIPAL_NAICS_CODE")["OBLIGATED_AMOUNT"].agg(
    count="count", total="sum"
).sort_values("total", ascending=False).head(20)
```

### Large contract filter

```python
large = df[df["OBLIGATED_AMOUNT"] > 1_000_000].sort_values(
    "OBLIGATED_AMOUNT", ascending=False
)
```

### Top N vendors

```python
top_vendors = df.groupby("UEI_NAME")["OBLIGATED_AMOUNT"].agg(
    contracts="count", total="sum"
).sort_values("total", ascending=False).head(20)
```

## Investigative Patterns

### Vendor concentration analysis

Find if a small number of vendors dominate spending:

```python
vendor_totals = df.groupby("UEI_NAME")["OBLIGATED_AMOUNT"].sum().sort_values(ascending=False)
top5_share = vendor_totals.head(5).sum() / vendor_totals.sum()
print(f"Top 5 vendors control {top5_share:.1%} of spending")
```

### Sole-source / no-competition contracts

```python
sole_source = df[df["EXTENT_COMPETED_DESCRIPTION"].str.contains("NOT COMPETED", na=False)]
```

### Contract modifications tracking

```python
mods = df[df["MODIFICATION_NUMBER"] != "0"]
mod_counts = mods.groupby("PIID")["MODIFICATION_NUMBER"].count().sort_values(ascending=False)
```

### Geographic spending patterns

```python
# Spending by state with contract counts
geo = df.groupby("VENDOR_ADDRESS_STATE_NAME").agg({
    "OBLIGATED_AMOUNT": ["sum", "count"],
    "UEI_NAME": "nunique"
}).sort_values(("OBLIGATED_AMOUNT", "sum"), ascending=False)
```

### PSC code analysis for a specific agency

```python
psc_breakdown = df[df["AGENCY_NAME"] == "Department of Defense"].groupby(
    "PRODUCT_OR_SERVICE_CODE"
)["OBLIGATED_AMOUNT"].sum().sort_values(ascending=False).head(20)
```

## Cross-Source Comparison

### Query same scope from both sources

```python
# FPDS
fpds_req = fpdsRequest(
    AGENCY_NAME="Department of Defense",
    LAST_MOD_DATE="[2024/01/01, 2024/01/31]"
)
fpds_records = asyncio.run(fpds_req.data())
save_api_response("fpds", {"agency": "DoD", "dates": "2024/01-only"}, fpds_records)
fpds_df = pd.DataFrame(fpds_records)

# USAspending
usa_payload = {
    "filters": {
        "agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of Defense"}],
        "time_period": [{"start_date": "2024-01-01", "end_date": "2024-01-31"}]
    },
    "limit": 100
}
usa_resp = requests.post(
    "https://api.usaspending.gov/api/v2/search/spending_by_award/",
    json=usa_payload
)
usa_results = usa_resp.json().get("results", [])
save_api_response("usaspending", usa_payload["filters"], usa_results)
usa_df = pd.DataFrame(usa_results)
```

Note: Record counts will differ — FPDS has transaction-level data (including modifications), USAspending aggregates at the award level.

### When to use which source

| Need | Use |
|------|-----|
| Transaction-level detail | FPDS |
| Contract modifications | FPDS |
| Specific contract lookup by PIID | FPDS |
| Recent/real-time data | FPDS |
| Fiscal year aggregations | USAspending |
| Agency-level summaries | USAspending |
| Multi-criteria complex filters | USAspending |
| Larger result sets | USAspending |
| Keyword search across descriptions | USAspending |
| Entity registration data (UEI, CAGE, business type) | SAM.gov Entity API |
| Active solicitations and notices | SAM.gov Opportunities API |
| Verify contractor SAM registration status | SAM.gov Entity API |
| Resolve agency/org names to IDs | SAM.gov Federal Hierarchy API |
| Set-aside and small business certifications | SAM.gov Entity API |
