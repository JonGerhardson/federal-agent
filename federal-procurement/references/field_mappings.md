# FPDS ↔ USAspending ↔ SAM.gov Field Mappings

Complete mapping of FPDS ATOM feed field names to USAspending API parameters and SAM.gov Entity API fields.

## Contract/Award Fields

| FPDS Field | USAspending API | Notes |
|------------|-----------------|-------|
| PIID | award_ids | Contract ID |
| CONTRACT_TYPE | award_type_codes | |
| AWARD_TYPE | award_type_codes | |
| AWARD_STATUS | keyword_search | Not directly filterable |
| AWARD_COMPLETION_DATE | time_period | |
| SIGNED_DATE | time_period | Maps to Period of Performance Start Date |
| CONTRACT_FISCAL_YEAR | time_period | |

## Agency Fields

| FPDS Field | USAspending API | Notes |
|------------|-----------------|-------|
| AGENCY_CODE | agencies.award_agency_code | 4-digit **sub-agency** code (e.g., ICE=7012, CBP=7014). NOT for department-level queries — use DEPARTMENT_ID instead |
| AGENCY_NAME | agencies.toptier_name | |
| DEPARTMENT_ID | agencies.id | Top-level **department** code (e.g., DHS=7000, DoD=9700). Use this for department-wide queries |
| DEPARTMENT_NAME | agencies.toptier_name | |
| CONTRACTING_AGENCY_ID | agencies.id | |
| CONTRACTING_AGENCY_NAME | agencies.name | |
| CONTRACTING_OFFICE_ID | agencies.office_id | |
| CONTRACTING_OFFICE_NAME | agencies.office_name | |
| FUNDING_AGENCY_ID | agencies.id | Use type: "funding" |
| FUNDING_AGENCY_NAME | agencies.name | Use type: "funding" |
| FUNDING_OFFICE_ID | agencies.office_id | Use type: "funding" |
| FUNDING_OFFICE_NAME | agencies.office_name | Use type: "funding" |

## Amount/Value Fields

| FPDS Field | USAspending API | Notes |
|------------|-----------------|-------|
| OBLIGATED_AMOUNT | award_amounts | Comes as string with "$" and commas |
| BASE_EXERCISED_OPTIONS_VALUE | award_amounts | |
| CURRENT_CONTRACT_VALUE | award_amounts | |
| ULTIMATE_CONTRACT_VALUE | award_amounts | |
| TOTAL_BASE_AND_ALL_OPTIONS_VALUE | award_amounts | |
| TOTAL_BASE_AND_EXERCISED_OPTIONS_VALUE | award_amounts | |
| TOTAL_DOLLARS_OBLIGATED | award_amounts | |

## Vendor/Entity Fields

| FPDS Field | USAspending API | Notes |
|------------|-----------------|-------|
| UEI_NAME | legal_entities | Vendor/recipient name |
| VENDOR_UEI | legal_entities.uei | Unique Entity ID |
| ULTIMATE_UEI | legal_entities.ultimate_parent_uei | Parent company UEI |
| ULTIMATE_UEI_NAME | legal_entities.ultimate_parent_legal_entity_name | |
| VENDOR_DOING_BUSINESS_AS_NAME | recipient_locations.recipient_name | DBA name |
| VENDOR_ADDRESS_CITY | recipient_locations.city_name | |
| VENDOR_ADDRESS_STATE_CODE | recipient_locations.state_code | 2-letter code |
| VENDOR_ADDRESS_STATE_NAME | recipient_locations.state_name | |
| VENDOR_ADDRESS_ZIP_CODE | recipient_locations.zip5 | |
| VENDOR_ADDRESS_COUNTRY_CODE | recipient_locations.country_code | |
| VENDOR_ADDRESS_COUNTRY_NAME | recipient_locations.country_name | |
| VENDOR_CONGRESS_DISTRICT_CODE | recipient_locations.congressional_code | |

## Category/Coding Fields

| FPDS Field | USAspending API | Notes |
|------------|-----------------|-------|
| PRINCIPAL_NAICS_CODE | naics_codes | 6-digit NAICS |
| NAICS_DESCRIPTION | naics_codes | |
| PRODUCT_OR_SERVICE_CODE | psc_codes | PSC code |
| PRODUCT_OR_SERVICE_DESCRIPTION | psc_codes | |

## Location/Performance Fields

| FPDS Field | USAspending API | Notes |
|------------|-----------------|-------|
| POP_STATE_NAME | place_of_performance_locations.state_name | |
| POP_COUNTRY_NAME | place_of_performance_locations.country_name | |
| POP_CONGRESS_DISTRICT_CODE | place_of_performance_locations.congressional_code | |
| EFFECTIVE_DATE | time_period | |
| ESTIMATED_COMPLETION_DATE | time_period | |

## Reference/Description Fields

| FPDS Field | USAspending API | Notes |
|------------|-----------------|-------|
| DESCRIPTION_OF_REQUIREMENT | keyword_search | Scope of work text |
| CAGE_CODE | keyword_search | Contractor ID |
| SOLICITATION_ID | keyword_search | RFP/solicitation number |
| REF_IDV_PIID | keyword_search | Parent contract reference |
| REF_IDV_AGENCY_ID | agencies.id | |

## Treasury Account Fields

| FPDS Field | USAspending API | Notes |
|------------|-----------------|-------|
| TREASURY_ACCOUNT_SYMBOL | treasury_accounts | |
| AGENCY_IDENTIFIER | treasury_accounts.federal_account | |
| MAIN_ACCOUNT_CODE | treasury_accounts.federal_account | |

## SAM.gov Entity Fields

Mapping SAM Entity Management API fields to FPDS and USAspending equivalents.

| SAM Entity API Field | FPDS Field | USAspending API | Notes |
|---------------------|------------|-----------------|-------|
| `entityRegistration.ueiSAM` | VENDOR_UEI | legal_entities.uei | Unique Entity ID (primary key) |
| `entityRegistration.cageCode` | CAGE_CODE | keyword_search | CAGE/NCAGE code |
| `entityRegistration.legalBusinessName` | UEI_NAME | legal_entities.recipient_name | Legal business name |
| `entityRegistration.dbaName` | VENDOR_DOING_BUSINESS_AS_NAME | recipient_locations.recipient_name | DBA name |
| `entityRegistration.registrationStatus` | — | — | Active/Expired/Work-in-progress |
| `entityRegistration.registrationDate` | — | — | SAM registration date |
| `entityRegistration.expirationDate` | — | — | Registration expiration |
| `entityRegistration.purposeOfRegistrationCode` | — | — | Z1=assistance, Z2=contracts, Z5=both |
| `coreData.physicalAddress.addressLine1` | — | recipient_locations.address_line1 | Street address |
| `coreData.physicalAddress.city` | VENDOR_ADDRESS_CITY | recipient_locations.city_name | City |
| `coreData.physicalAddress.stateOrProvinceCode` | VENDOR_ADDRESS_STATE_CODE | recipient_locations.state_code | 2-letter state |
| `coreData.physicalAddress.zipCode` | VENDOR_ADDRESS_ZIP_CODE | recipient_locations.zip5 | ZIP code |
| `coreData.physicalAddress.countryCode` | VENDOR_ADDRESS_COUNTRY_CODE | recipient_locations.country_code | 3-letter country |
| `assertions.goodsAndServices.primaryNaics` | PRINCIPAL_NAICS_CODE | naics_codes | Primary NAICS code |
| `assertions.goodsAndServices.naicsList[].naicsCode` | PRINCIPAL_NAICS_CODE | naics_codes | All NAICS codes |
| `assertions.goodsAndServices.pscList[].pscCode` | PRODUCT_OR_SERVICE_CODE | psc_codes | PSC codes |

### SAM-only fields (no FPDS/USAspending equivalent)

- `entityRegistration.samRegistered` — Whether entity is SAM-registered
- `coreData.businessTypes.businessTypeList` — Business type codes (small business, 8(a), HUBZone, etc.)
- `coreData.businessTypes.sbaBusinessTypeList` — SBA certifications
- `coreData.financialInformation.creditCardUsage` — Accepts government purchase cards
- `coreData.financialInformation.debtSubjectToOffset` — Debt offset flag
- `coreData.entityInformation.entityURL` — Company website
- `coreData.entityInformation.entityStartDate` — Business start date

## Fields Not Searchable via USAspending API

These FPDS fields have no USAspending equivalent:
- MODIFICATION_NUMBER
- CREATED_BY / LAST_MODIFIED_BY
- VERSION
- NUMBER_OF_OFFERS_RECEIVED
- REASON_FOR_MODIFICATION
- FED_BIZ_OPPS_DESC
