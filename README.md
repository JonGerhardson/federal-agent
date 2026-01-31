# federal-agent
A Claude Code skill for querying, analyzing, and building tools for federal contract and spending data from FPDS (Federal Procurement Data System), USAspending.gov, and SAM.gov APIs.

## Overview

This skill provides comprehensive knowledge and code patterns for working with three primary federal procurement data sources:

- **FPDS ATOM Feed** - Transaction-level contract detail via the `fpds` Python library
- **USAspending API** - Award aggregations and fiscal year summaries (no auth required)
- **SAM.gov APIs** - Contract opportunities, entity registrations, and organizational hierarchy (requires free API key)

## Features

- Query federal contracts by agency, date, vendor, NAICS code, PSC code
- Analyze spending patterns, vendor concentration, contract modifications
- Look up contractor registrations and SAM.gov entity details
- Search active solicitations and opportunities
- Cross-reference data across multiple sources
- **Mandatory data provenance** - All API calls automatically save raw responses for reproducibility

## Installation

Copy this directory to `~/.claude/skills/federal-procurement/`

## Dependencies

```bash
pip install fpds pandas requests
```

## Required API Keys

- **SAM.gov**: Get a free API key at https://sam.gov/content/entity-information
  - Set as `SAM_API_KEY` environment variable
  - Required for: Opportunities API, Entity Management API, Federal Hierarchy API

## Quick Start Examples

See `SKILL.md` for full documentation and code examples.

### Query FPDS for DoD contracts

```python
from fpds import fpdsRequest
import asyncio

request = fpdsRequest(
    AGENCY_NAME="Department of Defense",
    LAST_MOD_DATE="[2024/01/01, 2024/12/31]"
)
records = asyncio.run(request.data())
```

### Search SAM.gov for active opportunities

```python
import os, requests

params = {
    "api_key": os.environ["SAM_API_KEY"],
    "postedFrom": "01/01/2024",
    "postedTo": "06/30/2024",
    "keyword": "cybersecurity",
    "limit": 100,
}
resp = requests.get("https://api.sam.gov/opportunities/v2/search", params=params)
opps = resp.json().get("opportunitiesData", [])
```

### Look up contractor by UEI

```python
params = {
    "api_key": os.environ["SAM_API_KEY"],
    "ueiSAM": "ABC123DEF456",
    "includeSections": "entityRegistration,coreData",
}
resp = requests.get("https://api.sam.gov/entity-information/v3/entities", params=params)
entities = resp.json().get("entityData", [])
```

## Documentation Structure

- **SKILL.md** - Main skill file with data sources, quick start, analysis patterns
- **references/sam_api.md** - Complete SAM.gov API reference (Opportunities, Entity Management, Federal Hierarchy)
- **references/usaspending_api.md** - USAspending.gov API endpoint reference
- **references/field_mappings.md** - Field mappings across FPDS, USAspending, and SAM.gov
- **references/query_patterns.md** - Code examples for common queries and investigations
- **references/data/** - Lookup tables for agency codes, NAICS codes, PSC codes, contract action types

## Data Sources

All data sources are public and authoritative:

- **FPDS** - Federal Procurement Data System (managed by GSA)
- **USAspending.gov** - Official source for U.S. government spending data
- **SAM.gov** - System for Award Management (entity registrations and contract opportunities)


## License

This skill documentation is provided as-is for public use. Data accessed through these APIs is subject to each source's terms of service.
The files in ./references/data are excerpted from [CSISdefense/Lookup-Tables](https://github.com/CSISdefense/Lookup-Tables) (CC0 license).
The fpds.gov parser is from [dherincx92/fpds](https://github.com/dherincx92/fpds) (MIT license). 

## Contributing

Contributions and improvements welcome.

## Support

For issues or questions about:
- The skill itself - file an issue 
- FPDS API - see https://www.fpds.gov/wiki/index.php/ATOM_Feed_FAQ
- USAspending API - see https://api.usaspending.gov/
- SAM.gov APIs - see https://open.gsa.gov/api/sam-api/
