# USAspending API Reference

Base URL: `https://api.usaspending.gov/api/v2/`

No authentication required. All endpoints accept POST with JSON body.

## Key Endpoints

### Award Search (primary)
`POST /search/spending_by_award/`

```python
payload = {
    "filters": { ... },       # Required
    "fields": ["field1", ...], # Optional, limits returned fields
    "limit": 100,              # Max records per page (default 10, max 100)
    "page": 1,                 # Pagination
    "sort": "Award Amount",    # Sort field
    "order": "desc"            # "asc" or "desc"
}
```

### Spending by Category
`POST /search/spending_by_category/`
- Groups spending by: awarding_agency, recipient, naics, psc, etc.
- Returns aggregated totals

### Spending Over Time
`POST /search/spending_over_time/`
- Groups spending by fiscal_year or month
- Returns time series data

### Award Detail
`GET /awards/{award_id}/`
- Full details for a single award

### Autocomplete Endpoints
- `POST /autocomplete/awarding_agency/` — Agency name autocomplete
- `POST /autocomplete/recipient/` — Recipient name autocomplete
- `POST /autocomplete/naics/` — NAICS code autocomplete
- `POST /autocomplete/psc/` — PSC code autocomplete

## Filter Structure

All search endpoints use the same filter format:

```python
filters = {
    # Time period (fiscal year Oct 1 - Sep 30)
    "time_period": [
        {"start_date": "2024-10-01", "end_date": "2025-09-30"}
    ],

    # Agencies
    "agencies": [
        {"type": "awarding", "tier": "toptier", "name": "Department of Defense"},
        {"type": "funding", "tier": "subtier", "name": "Army"}
    ],

    # Award type codes
    "award_type_codes": [
        "A", "B", "C", "D",   # Contracts
        "02", "03", "04", "05" # Grants, loans, etc.
    ],

    # Award amounts
    "award_amounts": [
        {"lower_bound": 1000000, "upper_bound": 5000000}
    ],

    # Location filters
    "recipient_locations": [
        {"country": "USA", "state": "CA"}
    ],
    "place_of_performance_locations": [
        {"country": "USA", "state": "MA", "city": "Boston"}
    ],

    # Code filters
    "naics_codes": ["541511", "541512"],
    "psc_codes": ["R617", "D301"],

    # Keyword search (searches description fields)
    "keywords": ["cybersecurity", "IT modernization"],

    # Recipient/vendor
    "legal_entities": [
        {"name": "Raytheon", "uei": "..."}
    ],

    # Set-aside types
    "set_aside": ["SBA", "8A"],

    # Treasury accounts
    "treasury_accounts": [
        {"federal_account": "097-0100"}
    ],

    # Defense spending codes
    "def_codes": ["L", "M", "N"]
}
```

## Award Type Codes

For the `award_type_codes` filter:

| Code | Type |
|------|------|
| A | BPA Call |
| B | Purchase Order |
| C | Delivery Order |
| D | Definitive Contract |
| 02 | Block Grant |
| 03 | Formula Grant |
| 04 | Project Grant |
| 05 | Cooperative Agreement |
| 06 | Direct Payment |
| 07 | Direct Loan |
| 08 | Guaranteed/Insured Loan |
| 09 | Insurance |
| 10 | Direct Payment with Unrestricted Use |
| 11 | Other Financial Assistance |
| IDV_A | GWAC Government Wide Acquisition Contract |
| IDV_B | IDC Multi-Agency Contract |
| IDV_B_A | IDC Indefinite Delivery Contract |
| IDV_B_B | IDC Federal Supply Schedule |
| IDV_B_C | IDC Basic Ordering Agreement |
| IDV_C | FSS Federal Supply Schedule |
| IDV_D | BOA Blanket Purchase Agreement |
| IDV_E | BPA Blanket Purchase Agreement |

## Response Fields (spending_by_award)

Available fields for the `fields` parameter:

```
"Award ID", "Recipient Name", "Recipient DUNS Number",
"Awarding Agency", "Awarding Sub Agency", "Award Amount",
"Total Outlays", "Description", "Contract Award Type",
"Award Type", "Funding Agency", "Funding Sub Agency",
"Period of Performance Start Date", "Period of Performance Current End Date",
"Place of Performance City Code", "Place of Performance State Code",
"Place of Performance Country Code", "NAICS Code", "PSC Code",
"recipient_id", "prime_award_recipient_id"
```

## Pagination

Results are paginated. To get all results:

```python
page = 1
all_results = []
while True:
    payload["page"] = page
    response = requests.post(url, json=payload)
    data = response.json()
    results = data.get("results", [])
    if not results:
        break
    all_results.extend(results)
    if len(results) < payload.get("limit", 10):
        break
    page += 1
save_api_response("usaspending", payload.get("filters", {}), all_results)
```

## Rate Limits

No official rate limit documented, but:
- Keep requests reasonable (1-2 per second)
- Use pagination instead of massive single requests
- Cache results when doing repeated analysis
