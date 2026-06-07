"""Bulk SAM.gov Entity "Extract" pulls — the default path for any bulk / cross-reference work.

Per-UEI lookups against the Entity Management API are rate-limited to 10 requests/day (bare key)
or 1,000/day (entity-associated key) — useless for iterating over a large corpus of award
recipients. The *same* endpoint doubles as an asynchronous Extract API: add a ``format`` parameter
and it returns a downloadable file of up to the first 1,000,000 records. The active-registrant
universe is well under 1M, so one (or a few) extract calls ≈ the entire public dataset and the
daily rate limit stops mattering.

Async flow (verified against https://open.gsa.gov/api/entity-api/, 2026-06):
  1. GET  /entity-information/v3/entities?api_key=…&format=JSON&<filters>   → returns a token
  2. GET  /entity-information/v3/download-entities?token=<token>&api_key=…  → poll until ready
     - still processing: HTTP 400 / JSON body "…not generated yet. Please try again later."
     - ready:           HTTP 200 with the file. Verified 2026-06-07: a format=JSON public extract is
                        a BARE GZIP stream (magic 1f 8b) that decompresses straight to a JSON array —
                        NOT the .zip-of-.json.gz the GSA docs describe. CSV/federal keys may differ.
     - too big:         HTTP 400 "…exceeded the maximum allowable limit: 1000000…"
Download is a GET (POST → 415). The code sniffs the actual bytes (PK=zip, 1f 8b=gzip, else plain) and
parses the token defensively, so it's robust whether the payload is a zip, a bare gzip, or plain.

Public API:
  pull_entity_extract(filters, fmt="JSON", refresh_after_days=7, include_sections=…) -> DataFrame
      One-shot submit→poll→download→load. Convenient, but polls — see the caveat below.
  submit_extract(filters, …) -> {token,…}     # 1 call: submit only, token saved to disk
  download_extract(filters | token=…, …) -> DataFrame  # 1 call: grab the finished file later
  enrich_ueis(uei_list, refresh_after_days=7) -> DataFrame
  normalize_entities(records, fmt="JSON") -> DataFrame

Quota note: a bare key allows only 10 requests/day and EVERY download poll spends one. For a large
(e.g. national) extract that takes minutes to build, prefer the two-step path — submit_extract()
now (1 call), wait, then download_extract() once it's ready (1 call) — instead of pull_entity_extract,
which polls in a loop and can exhaust a 10/day key before the file is even ready.

Auth: reads SAM_API_KEY from the environment (free key at https://sam.gov/content/entity-information).
"""

import gzip
import io
import os
import re
import time
import zipfile
import json as _json
from pathlib import Path

import pandas as pd
import requests

try:
    from .provenance import save_api_response, write_extract_manifest
except ImportError:  # allow running as a plain script, not just as a package module
    from provenance import save_api_response, write_extract_manifest

# --- Endpoint constants (bump API_VERSION here if v3 is ever retired) ----------------------------
API_BASE = "https://api.sam.gov/entity-information"
API_VERSION = "v3"
ENTITIES_URL = f"{API_BASE}/{API_VERSION}/entities"
DOWNLOAD_URL = f"{API_BASE}/{API_VERSION}/download-entities"
MAX_EXTRACT_RECORDS = 1_000_000

# Default sections. entityRegistration + coreData carry everything needed for entity resolution /
# shell detection (name, UEI, CAGE, addresses, registration/activation/expiration dates) and are
# available to a public "Read Public" key. Add "assertions" if you need NAICS/PSC.
DEFAULT_SECTIONS = "entityRegistration,coreData"


class SamExtractError(RuntimeError):
    """Base class for extract failures."""


class SamAuthError(SamExtractError):
    """Invalid/forbidden API key."""


class SamRateLimitError(SamExtractError):
    """Daily request cap hit (HTTP 429)."""


class SamExtractTooLarge(SamExtractError):
    """Filter set would exceed the 1,000,000-record cap; caller should partition."""


class SamExtractTimeout(SamExtractError):
    """The async job did not finish within the poll budget."""


# ----------------------------------------------------------------------------------------------- #
# Public functions
# ----------------------------------------------------------------------------------------------- #
def pull_entity_extract(
    filters: dict,
    fmt: str = "JSON",
    refresh_after_days: int = 7,
    include_sections: str = DEFAULT_SECTIONS,
    poll_interval: int = 20,
    max_wait_seconds: int = 1200,
    _allow_partition: bool = True,
) -> pd.DataFrame:
    """Pull a bulk SAM.gov entity extract and return a normalized, UEI-keyed DataFrame.

    ``filters`` uses the real (case-sensitive) Entity API param names, e.g.::

        {"registrationStatus": "A",
         "physicalAddressProvinceOrStateCode": "VT",
         "registrationDate": "[01/01/2025,06/01/2025]",   # MM/DD/YYYY, brackets = inclusive range
         "q": "logistics"}

    The raw download is cached under references/data/sam_extract/ (override with
    SAM_EXTRACT_CACHE_DIR) and reused unless older than ``refresh_after_days`` — so repeated joins
    don't re-pull. A provenance manifest (resolved URL, timestamp, record count, sha256) is written
    next to every cached file.
    """
    fmt = fmt.upper()
    if fmt not in ("JSON", "CSV"):
        raise ValueError("fmt must be 'JSON' or 'CSV'")

    h = _filter_hash(filters, fmt, include_sections)
    cached = _find_fresh_cache(h, refresh_after_days)
    if cached is not None:
        print(f"Cache hit: {cached.name} (< {refresh_after_days}d old) — skipping re-pull")
        records = _extract_to_records(cached.read_bytes(), fmt)
        return normalize_entities(records, fmt)

    api_key = _get_key()
    try:
        token, resolved_url, inline = _submit_extract_job(filters, fmt, include_sections, api_key)
        if inline is not None:  # tiny result came back inline rather than as a job
            df, _ = _save_extract_bytes(
                _records_to_bytes(inline, fmt), "json" if fmt == "JSON" else "csv",
                filters, fmt, include_sections, resolved_url,
            )
            return df
        raw, ext = _poll_download(token, api_key, poll_interval, max_wait_seconds)
    except SamExtractTooLarge:
        if not _allow_partition:
            raise
        print("Result exceeds the 1,000,000-record cap — partitioning by state and concatenating.")
        return _partition_by_state(filters, fmt, refresh_after_days, include_sections)

    df, _ = _save_extract_bytes(raw, ext, filters, fmt, include_sections, resolved_url)
    return df


def submit_extract(filters: dict, fmt: str = "JSON", include_sections: str = DEFAULT_SECTIONS) -> dict:
    """Submit a bulk extract job WITHOUT downloading — exactly **one** API call.

    This is the quota-safe path for a tight key (a bare key is 10 requests/day, and *every* download
    poll counts). Submit now, let SAM build the file (minutes for a national pull), then spend a
    second call on ``download_extract`` once it's ready — instead of burning the day's quota polling.
    The token is persisted under the cache dir so ``download_extract`` can pick it up later, even in
    a fresh process. Returns ``{"token", "filter_hash", "resolved_url"}``.
    """
    fmt = fmt.upper()
    if fmt not in ("JSON", "CSV"):
        raise ValueError("fmt must be 'JSON' or 'CSV'")
    api_key = _get_key()
    h = _filter_hash(filters, fmt, include_sections)
    token, resolved_url, inline = _submit_extract_job(filters, fmt, include_sections, api_key)
    if inline is not None:  # small result returned inline — cache immediately, no 2nd call needed
        _save_extract_bytes(_records_to_bytes(inline, fmt), "json" if fmt == "JSON" else "csv",
                            filters, fmt, include_sections, resolved_url)
        print("Result returned inline and was cached; no separate download needed.")
        return {"token": None, "filter_hash": h, "resolved_url": resolved_url}
    _save_pending(h, {"token": token, "fmt": fmt, "include_sections": include_sections,
                      "filters": filters, "resolved_url": resolved_url, "submitted_at": _now_iso()})
    print(f"Submitted extract job (filter_hash={h}); token saved.\n"
          f"  → Wait a few minutes for SAM to build the file, then download it with ONE call:\n"
          f"      download_extract({filters!r}, fmt={fmt!r})")
    return {"token": token, "filter_hash": h, "resolved_url": resolved_url}


def download_extract(filters: dict = None, *, token: str = None, fmt: str = "JSON",
                     include_sections: str = DEFAULT_SECTIONS, refresh_after_days: int = 7,
                     poll_interval: int = 30, max_wait_seconds: int = 1800) -> pd.DataFrame:
    """Download a previously-submitted extract by its saved token — typically **one** API call.

    Pass the same ``filters`` you gave ``submit_extract`` (the saved token is looked up by their
    hash), or an explicit ``token=``. Call this once SAM has finished building the file; if you call
    too early it will poll (extra calls). Cache-first: a fresh cached extract returns with no call.
    """
    fmt = fmt.upper()
    h = _filter_hash(filters or {}, fmt, include_sections) if filters is not None else None
    if h is not None:
        cached = _find_fresh_cache(h, refresh_after_days)
        if cached is not None:
            print(f"Cache hit: {cached.name} — skipping download")
            return normalize_entities(_extract_to_records(cached.read_bytes(), fmt), fmt)

    api_key = _get_key()
    resolved_url, pend_filters = "", filters
    if token is None:
        if h is None:
            raise SamExtractError("Pass filters= (to resolve the saved token) or an explicit token=.")
        pend = _load_pending(h)
        if not pend:
            raise SamExtractError(
                f"No pending extract found for these filters (hash {h}). Run submit_extract() first, "
                "or pass token= directly.")
        token = pend["token"]
        resolved_url = pend.get("resolved_url", "")
        pend_filters = pend.get("filters", filters) or {}

    raw, ext = _poll_download(token, api_key, poll_interval, max_wait_seconds)
    df, _ = _save_extract_bytes(raw, ext, pend_filters or {}, fmt, include_sections, resolved_url)
    if h is not None:
        _clear_pending(h)
    return df


def enrich_ueis(uei_list, refresh_after_days: int = 7, include_sections: str = DEFAULT_SECTIONS) -> pd.DataFrame:
    """Resolve entity attributes for a list of UEIs, cached-extract-first.

    This is the entry point bulk/cross-reference code should call instead of hitting the live
    per-UEI endpoint directly. UEIs found in the most recent cached extract are served from cache
    (zero API calls); only UEIs *missing* from the extract fall back to the live v3 entities
    endpoint (batched up to 100 UEIs per call, which is cheap on the rate limit).

    Typical use: call ``pull_entity_extract`` once to seed the cache for your corpus, then call
    ``enrich_ueis`` repeatedly. With no cache present, every UEI goes through the live fallback.
    """
    wanted = [u.strip().upper() for u in uei_list if u and str(u).strip()]
    wanted = list(dict.fromkeys(wanted))  # de-dupe, preserve order
    if not wanted:
        return pd.DataFrame()

    cache_df = _load_newest_cache_df(refresh_after_days, include_sections)
    if cache_df is not None and not cache_df.empty and "uei" in cache_df.columns:
        hits = cache_df[cache_df["uei"].isin(wanted)].copy()
        hits["source"] = "extract_cache"
        found = set(hits["uei"])
    else:
        hits = pd.DataFrame()
        found = set()
        print("No fresh cached extract found — resolving all UEIs via the live per-UEI fallback. "
              "Seed the cache with pull_entity_extract() first for large corpora.")

    missing = [u for u in wanted if u not in found]
    if missing:
        print(f"{len(found)} UEIs from cache, {len(missing)} via live per-UEI fallback.")
        live = _enrich_live(missing, include_sections)
        if not live.empty:
            live["source"] = "live_v3"
        frames = [df for df in (hits, live) if not df.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    print(f"All {len(found)} UEIs resolved from cached extract (0 API calls).")
    return hits.reset_index(drop=True)


def normalize_entities(records, fmt: str = "JSON") -> pd.DataFrame:
    """Normalize raw extract records into a tidy, UEI-keyed table for entity resolution.

    Columns: uei, cage_code, legal_business_name, dba_name, registration_status, registration_date,
    activation_date, expiration_date, purpose_of_registration_code, physical_address_line1,
    physical_city, physical_state, physical_zip, physical_country, entity_structure_code,
    entity_start_date, primary_naics.

    NOTE: entity parent/child *hierarchy*, security levels, and point-of-contact email/phone/fax are
    FOUO-restricted and require a federal "Read FOUO" key — for a non-federal Read-Public key those
    fields are absent, so any parent-hierarchy column will usually be empty here.
    """
    if fmt.upper() == "CSV":
        # CSV extracts are already flat; SAM's column headers differ from the JSON paths and are not
        # remapped here. We best-effort surface a 'uei' column so downstream joins work, and pass the
        # rest through. Inspect df.columns to see what the CSV carries.
        df = records if isinstance(records, pd.DataFrame) else pd.DataFrame(records)
        for cand in ("uei", "ueiSAM", "UEI", "Unique Entity ID", "UNIQUE_ENTITY_ID"):
            if cand in df.columns:
                df = df.rename(columns={cand: "uei"})
                break
        return df

    rows = []
    for rec in records or []:
        rows.append(
            {
                "uei": _dig(rec, "entityRegistration", "ueiSAM") or _dig(rec, "ueiSAM"),
                "cage_code": _dig(rec, "entityRegistration", "cageCode"),
                "legal_business_name": _dig(rec, "entityRegistration", "legalBusinessName"),
                "dba_name": _dig(rec, "entityRegistration", "dbaName"),
                "registration_status": _dig(rec, "entityRegistration", "registrationStatus"),
                "registration_date": _dig(rec, "entityRegistration", "registrationDate"),
                "activation_date": _dig(rec, "entityRegistration", "activationDate"),
                # expirationDate (v1) was renamed registrationExpirationDate (v2+); accept either.
                "expiration_date": (
                    _dig(rec, "entityRegistration", "registrationExpirationDate")
                    or _dig(rec, "entityRegistration", "expirationDate")
                ),
                "purpose_of_registration_code": _dig(rec, "entityRegistration", "purposeOfRegistrationCode"),
                "physical_address_line1": _dig(rec, "coreData", "physicalAddress", "addressLine1"),
                "physical_city": _dig(rec, "coreData", "physicalAddress", "city"),
                "physical_state": _dig(rec, "coreData", "physicalAddress", "stateOrProvinceCode"),
                "physical_zip": _dig(rec, "coreData", "physicalAddress", "zipCode"),
                "physical_country": _dig(rec, "coreData", "physicalAddress", "countryCode"),
                # entity structure / org type — present in coreData when exposed to the key.
                "entity_structure_code": (
                    _dig(rec, "coreData", "generalInformation", "entityStructureCode")
                    or _dig(rec, "coreData", "entityInformation", "entityStructureCode")
                ),
                "entity_start_date": _dig(rec, "coreData", "entityInformation", "entityStartDate"),
                "primary_naics": _dig(rec, "assertions", "goodsAndServices", "primaryNaics"),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.dropna(subset=["uei"]).drop_duplicates(subset=["uei"]).reset_index(drop=True)
    return df


# ----------------------------------------------------------------------------------------------- #
# Async submit / poll / download
# ----------------------------------------------------------------------------------------------- #
def _submit_extract_job(filters, fmt, include_sections, api_key):
    """Submit the extract job — one GET. Returns (token, resolved_url, inline_records).

    ``token`` is the download token; ``inline_records`` is non-None only in the rare case a tiny
    result comes back inline instead of as an async job (then ``token`` is None). The submit body is
    plain text carrying the token, which we persist for provenance.
    """
    params = {"api_key": api_key, "format": fmt, "includeSections": include_sections, **filters}
    resolved_url = f"{ENTITIES_URL}?{_qs(params)}"  # _qs redacts the api_key

    submit = requests.get(ENTITIES_URL, params=params)
    _raise_for_known_errors(submit)  # raises SamExtractTooLarge here if the filter set is over the cap
    token = _extract_token(submit)
    try:
        # SAM echoes the full download URL — INCLUDING the real api_key — back in this plain-text
        # body, so scrub the key (and token) before persisting it to provenance on disk.
        safe_msg = re.sub(r"(api_key=)[^&\s\"']+", r"\1***REDACTED***", submit.text or "")
        safe_msg = re.sub(r"(token=)[^&\s\"']+", r"\1***", safe_msg)
        save_api_response("sam_extract_request", params, {"message": safe_msg}, subdir="sam")
    except Exception:
        pass
    if not token:
        inline = _maybe_inline_records(submit)
        if inline is not None:
            return None, resolved_url, inline
        raise SamExtractError(
            "Extract submitted but no download token was found in the response. "
            f"Body starts: {submit.text[:300]}"
        )
    return token, resolved_url, None


def _poll_download(token, api_key, poll_interval, max_wait_seconds):
    """GET the token URL until the file is ready; return (raw_bytes, file_ext). One or more calls.

    Download is a GET — POST returns 415 UNSUPPORTED_MEDIA_TYPE. While the job is still generating,
    the GET returns HTTP 400 "…not generated yet. Please try again later."; once ready it returns 200
    with the binary file. ⚠ Each call counts against the daily cap, so on a bare 10/day key let the
    file finish building first (submit_extract → wait → download_extract) to keep this to one call.
    """
    deadline = time.time() + max_wait_seconds
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        dl = requests.get(DOWNLOAD_URL, params={"api_key": api_key, "token": token})
        magic = dl.content[:4]
        if magic[:4] == b"PK\x03\x04":
            return dl.content, "zip"
        if magic[:2] == b"\x1f\x8b":
            return dl.content, "gz"
        _raise_for_known_errors(dl)  # 429/auth/size abort immediately; a 400 "not ready" keeps polling
        body = (dl.text or "").lower()
        if any(s in body for s in ("not generated yet", "try again", "in-progress", "in progress")):
            wait = min(poll_interval * (1 + attempt // 2), 60)
            print(f"  …extract still generating (attempt {attempt}); waiting {wait}s")
            time.sleep(wait)
            continue
        if "expired" in body:
            raise SamExtractError("Extract token expired before download completed — re-submit.")
        raise SamExtractError(f"Unexpected download response (HTTP {dl.status_code}): {dl.text[:300]}")

    raise SamExtractTimeout(
        f"Extract not ready after {max_wait_seconds}s. National extracts take longer — raise "
        "max_wait_seconds, or use submit_extract() now + download_extract() later (one call each)."
    )


def _save_extract_bytes(raw, ext, filters, fmt, include_sections, resolved_url):
    """Cache the raw download, write the provenance manifest, and normalize → (DataFrame, count)."""
    h = _filter_hash(filters, fmt, include_sections)
    cache_path = _cache_dir() / f"sam_entities_{h}_{_today()}.{ext}"
    cache_path.write_bytes(raw)
    records = _extract_to_records(raw, fmt)
    n = len(records)
    write_extract_manifest(
        cache_path, resolved_url, {**filters, "format": fmt, "includeSections": include_sections}, n
    )
    print(f"Pulled {n} entity records → cached {cache_path}")
    return normalize_entities(records, fmt), n


def _extract_token(resp) -> str | None:
    """Pull the download token from the submit response — structured field first, then regex."""
    data = _safe_json(resp)
    if isinstance(data, dict):
        for k in ("token", "Token", "downloadToken", "fileToken"):
            if data.get(k):
                return str(data[k])
        for k in ("downloadUrl", "fileDownloadUrl", "url", "message", "links"):
            v = data.get(k)
            if v:
                m = re.search(r"token=([^&\s\"']+)", str(v))
                if m:
                    return m.group(1)
    m = re.search(r"token=([^&\s\"']+)", resp.text or "")
    return m.group(1) if m else None


def _raise_for_known_errors(resp):
    """Translate auth / rate-limit / size errors into clear, actionable exceptions."""
    if resp.status_code == 429:
        # SAM throttles via WSO2 (code 900804). For a bare key the daily cap is only 10 calls and
        # resets at 00:00 UTC; the reset time comes back in Retry-After / nextAccessTime.
        reset = resp.headers.get("Retry-After")
        try:
            reset = resp.json().get("nextAccessTime", reset)
        except Exception:
            pass
        raise SamRateLimitError(
            f"SAM.gov request cap hit (HTTP 429; access returns at {reset}). Each poll of an extract "
            "job counts against this cap, so a bare 10/day key is tight — poll patiently, or use an "
            "entity-associated key (1,000/day). Note the extract path needs only a handful of calls "
            "for the entire dataset, so if you're tripping this often, look for a per-UEI loop hitting "
            "the live endpoint instead of enrich_ueis()."
        )
    if resp.status_code in (401, 403):
        raise SamAuthError(
            f"SAM.gov rejected the API key (HTTP {resp.status_code}). Verify SAM_API_KEY is a valid "
            "key from https://sam.gov/content/entity-information and has 'Read Public' access."
        )
    body = (resp.text or "").lower()
    if "exceeded the maximum allowable limit" in body:
        raise SamExtractTooLarge(body[:300])
    if resp.status_code >= 500:
        raise SamExtractError(f"SAM.gov server error (HTTP {resp.status_code}). Try again later.")


# ----------------------------------------------------------------------------------------------- #
# Decompression / parsing
# ----------------------------------------------------------------------------------------------- #
def _extract_to_records(raw: bytes, fmt: str):
    """Decompress raw extract bytes and parse → list[dict] (JSON) or DataFrame (CSV)."""
    members = _decompress_members(raw)
    if fmt.upper() == "CSV":
        frames = [pd.read_csv(io.BytesIO(m)) for m in members if m.strip()]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    records = []
    for m in members:
        records.extend(_parse_json_member(m))
    return records


def _decompress_members(raw: bytes) -> list[bytes]:
    """Return decompressed member payloads. Handles zip(of-gz), bare gzip, and plain bytes."""
    if raw[:4] == b"PK\x03\x04":
        out = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                data = zf.read(name)
                if name.endswith(".gz") or data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                out.append(data)
        return out
    if raw[:2] == b"\x1f\x8b":
        return [gzip.decompress(raw)]
    return [raw]


def _parse_json_member(data: bytes) -> list:
    """Parse a JSON member that may be an array, an {entityData:[…]} object, or NDJSON."""
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        obj = _json.loads(text)
        if isinstance(obj, dict):
            return obj.get("entityData") or obj.get("data") or [obj]
        if isinstance(obj, list):
            return obj
    except _json.JSONDecodeError:
        pass
    # NDJSON fallback
    records = []
    for line in text.splitlines():
        line = line.strip().rstrip(",")
        if line and line not in ("[", "]"):
            try:
                records.append(_json.loads(line))
            except _json.JSONDecodeError:
                continue
    return records


# ----------------------------------------------------------------------------------------------- #
# Partitioning (1M cap)
# ----------------------------------------------------------------------------------------------- #
# US states + DC + territories. Every entity has a physical state, so partitioning on it yields
# buckets each far below the 1M cap, which we then concatenate and de-dupe on UEI.
_US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","DC","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA",
    "ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR",
    "PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","PR","VI","GU","AS","MP",
]


def _partition_by_state(filters, fmt, refresh_after_days, include_sections) -> pd.DataFrame:
    frames = []
    for st in _US_STATES:
        sub = {**filters, "physicalAddressProvinceOrStateCode": st}
        try:
            df = pull_entity_extract(
                sub, fmt=fmt, refresh_after_days=refresh_after_days,
                include_sections=include_sections, _allow_partition=False,
            )
        except SamExtractTooLarge:
            print(f"  state {st} still exceeds 1M even alone — skipping (narrow further by date).")
            continue
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if "uei" in out.columns:
        out = out.drop_duplicates(subset=["uei"]).reset_index(drop=True)
    return out


# ----------------------------------------------------------------------------------------------- #
# Live per-UEI fallback (the demoted path — single-entity / cache-miss enrichment only)
# ----------------------------------------------------------------------------------------------- #
def _enrich_live(ueis, include_sections) -> pd.DataFrame:
    """Resolve UEIs via the live v3 entities endpoint, batched ≤100 per call (ueiSAM cap)."""
    api_key = _get_key()
    records = []
    for batch in _chunks(ueis, 100):
        params = {"api_key": api_key, "ueiSAM": ",".join(batch), "includeSections": include_sections}
        resp = requests.get(ENTITIES_URL, params=params)
        _raise_for_known_errors(resp)
        resp.raise_for_status()
        data = _safe_json(resp)
        ents = data.get("entityData", []) if isinstance(data, dict) else []
        save_api_response("sam_entity_fallback", params, ents, subdir="sam")
        records.extend(ents)
    return normalize_entities(records, "JSON")


# ----------------------------------------------------------------------------------------------- #
# Cache helpers
# ----------------------------------------------------------------------------------------------- #
def _cache_dir() -> Path:
    override = os.environ.get("SAM_EXTRACT_CACHE_DIR")
    d = Path(override) if override else Path(__file__).resolve().parent.parent / "references" / "data" / "sam_extract"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pending_path(filter_hash: str) -> Path:
    return _cache_dir() / f"pending_{filter_hash}.json"


def _save_pending(filter_hash: str, info: dict):
    """Persist a submitted-but-not-downloaded extract token so download_extract() can resume it."""
    _pending_path(filter_hash).write_text(_json.dumps(info, indent=2))


def _load_pending(filter_hash: str):
    p = _pending_path(filter_hash)
    if not p.exists():
        return None
    try:
        return _json.loads(p.read_text())
    except Exception:
        return None


def _clear_pending(filter_hash: str):
    try:
        _pending_path(filter_hash).unlink()
    except FileNotFoundError:
        pass


def _find_fresh_cache(filter_hash: str, refresh_after_days: int):
    """Return the newest cached extract file for this filter set if within the refresh window."""
    matches = sorted(_cache_dir().glob(f"sam_entities_{filter_hash}_*"))
    matches = [m for m in matches if not m.name.endswith(".manifest.json")]
    if not matches:
        return None
    newest = matches[-1]
    m = re.search(r"_(\d{8})\.", newest.name)
    if not m:
        return None
    age_days = (int(_today()) - int(m.group(1)))  # YYYYMMDD diff is a coarse but safe upper bound
    # Convert to a real day delta to avoid month/year-boundary weirdness.
    from datetime import datetime
    file_date = datetime.strptime(m.group(1), "%Y%m%d")
    age_days = (datetime.utcnow() - file_date).days
    return newest if age_days <= refresh_after_days else None


def _load_newest_cache_df(refresh_after_days, include_sections):
    """Load the single most-recent fresh cached extract (any filter) as a normalized DataFrame."""
    matches = [m for m in _cache_dir().glob("sam_entities_*") if not m.name.endswith(".manifest.json")]
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime)
    newest = matches[-1]
    from datetime import datetime
    age_days = (datetime.utcnow() - datetime.utcfromtimestamp(newest.stat().st_mtime)).days
    if age_days > refresh_after_days:
        return None
    fmt = "CSV" if newest.suffix == ".csv" or ".csv" in newest.name else "JSON"
    return normalize_entities(_extract_to_records(newest.read_bytes(), fmt), fmt)


# ----------------------------------------------------------------------------------------------- #
# Small utilities
# ----------------------------------------------------------------------------------------------- #
def _get_key() -> str:
    key = os.environ.get("SAM_API_KEY")
    if not key:
        raise SamAuthError(
            "SAM_API_KEY is not set. Export a free key from https://sam.gov/content/entity-information. "
            "The extract path needs only a handful of calls for the whole dataset."
        )
    return key


def _filter_hash(filters: dict, fmt: str, include_sections: str) -> str:
    import hashlib
    payload = _json.dumps(
        {"filters": {k: v for k, v in sorted(filters.items()) if k != "api_key"},
         "fmt": fmt.upper(), "sections": include_sections},
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:10]


def _today() -> str:
    from datetime import datetime
    return datetime.utcnow().strftime("%Y%m%d")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _qs(params: dict) -> str:
    from urllib.parse import urlencode
    return urlencode({k: v for k, v in params.items() if k != "api_key"} | {"api_key": "***"})


def _safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {}


def _maybe_inline_records(resp):
    """If a (non-format) response actually carried entityData inline, return it; else None."""
    data = _safe_json(resp)
    if isinstance(data, dict) and isinstance(data.get("entityData"), list):
        return data["entityData"]
    return None


def _records_to_bytes(records, fmt) -> bytes:
    if fmt.upper() == "CSV":
        return pd.DataFrame(records).to_csv(index=False).encode()
    return _json.dumps(records).encode()


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _dig(obj, *path):
    """Safely walk a nested dict by keys, returning None if any level is missing/not a dict."""
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _cli_filters(rest):
    """Build filters from CLI args: default = national active registrants; an optional 2-letter
    state arg narrows to that state. e.g. `submit`, `submit VT`, `download`, `download VT`."""
    f = {"registrationStatus": "A"}
    if rest and rest[0].upper() not in ("JSON", "CSV"):
        f["physicalAddressProvinceOrStateCode"] = rest[0].upper()
    return f


def _print_df(df):
    print(f"\n{len(df)} rows\n")
    cols = ["uei", "legal_business_name", "cage_code", "registration_status",
            "registration_date", "activation_date", "expiration_date", "physical_city", "physical_state"]
    print(df[[c for c in cols if c in df.columns]].head(10).to_string())


if __name__ == "__main__":
    # Usage:
    #   python sam_extract.py submit            # submit national active extract (1 call)
    #   python sam_extract.py submit VT         # submit one state
    #   python sam_extract.py download          # download the submitted national extract (1 call)
    #   python sam_extract.py download VT       # download one state
    #   python sam_extract.py [STATE]           # one-shot pull (submits AND polls — needs quota)
    import sys
    args = sys.argv[1:]
    if args and args[0] == "submit":
        print(submit_extract(_cli_filters(args[1:])))
    elif args and args[0] == "download":
        _print_df(download_extract(_cli_filters(args[1:])))
    else:
        _print_df(pull_entity_extract(_cli_filters(args)))
