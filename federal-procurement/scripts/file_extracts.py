"""Bulk flat-file extracts for federal procurement data — SAM Data Services + USAspending archive.

These are the BULK path for datasets where the live API is rate-limited or absent:

  • SAM "File Extracts" (GSA/IAE) published to the public S3 bucket `falextracts.s3.amazonaws.com`.
    The Entity / Opportunities / Exclusions search APIs are capped at 10 requests/day on a bare key,
    so for bulk or cross-reference work these daily flat files are the move — no key, no rate limit.
  • USAspending award archive — a LAST RESORT (see ``usaspending_award_archive``). USAspending's API
    has no rate limit, so prefer it (or FPDS for transaction-level); the GB-scale archive is only for
    full-mirror needs.

Access classes (verified live 2026-06):
  • PUBLIC   (.../datagov/ or .../grantsgov/) — anonymous static URL, plain GET.
  • PRESIGNED (.../Public V2/, the "person icon" datasets: Exclusions, Entity) — require a short-lived
    (~45 min) presigned URL minted by sam.gov while you're logged in (grab it from the browser Network
    tab on the Download button). These cannot be built blind; pass the URL via ``presigned_url=``.

Bucket listing is disabled, so date-partitioned files are found by HEAD-walking back from today.
Everything caches under references/data/sam_extract/ with a sha256 + Last-Modified manifest (reusing
provenance.write_extract_manifest) and is reused while younger than ``refresh_after_days``.

Datasets:
  contract_opportunities          public, stable URL, daily   — active opportunities (~78k), NO UEI
  assistance_listings_datagov     public, weekly, date-part.  — federal assistance PROGRAM catalog
  assistance_listings_grantsgov   public, daily,  date-part.  — same, grants.gov schema variant
  exclusions                      presigned, daily            — debarment list, 31 cols, UEI on firms
  entity_registration             presigned, monthly          — prefer the JSON Entity Extract API instead

Public API:
  download_file_extract(dataset, date=None, presigned_url=None, refresh_after_days=1) -> Path
  load_file_extract(dataset, ...) -> DataFrame
  check_exclusions(ueis_or_df, uei_col="uei", presigned_url=None) -> DataFrame
  usaspending_award_archive(fiscal_year, award_type="contracts", agency="all", download=False) -> dict|Path
"""

import datetime
import io
import os
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pandas as pd
import requests

try:
    from .provenance import write_extract_manifest
except ImportError:  # allow running as a plain script
    from provenance import write_extract_manifest

FALEXTRACTS = "https://falextracts.s3.amazonaws.com"
# IAE Extracts Download API — the api_key route for the gated "Public V2" extracts. Synchronous:
# one GET with fileType=ENTITY|EXCLUSION|SCR|BIO & date=MM/DD/YYYY returns the ZIP (server-side
# presigning). Counts against the 10/day cap. Verified live for EXCLUSION (2026-06).
EXTRACTS_API = "https://api.sam.gov/data-services/v1/extracts"
# Generic, non-identifying UA (some GSA/Akamai edges 403 the default python-requests UA).
UA = {"User-Agent": "Mozilla/5.0 (compatible; research-client/1.0)"}

# Registry. `url` templates fill {ymd}=YYYYMMDD, {year}=YYYY, {month}=MM-Mon (e.g. 06-Jun),
# {julian}=YYjjj per `date_kind`. `cache_glob` lets us reuse an already-downloaded file.
DATASETS = {
    "contract_opportunities": {
        "access": "public",
        "date_kind": None,
        "url": f"{FALEXTRACTS}/Contract Opportunities/datagov/ContractOpportunitiesFullCSV.csv",
        "container": "csv",
        "cache_glob": "ContractOpportunitiesFullCSV.csv",
        "notes": "Active opportunities only (~78k). 47 cols. NO UEI. ~12k award notices carry Awardee+$.",
    },
    "assistance_listings_datagov": {
        "access": "public",
        "date_kind": "ymd",
        "url": f"{FALEXTRACTS}/Assistance Listings/datagov/{{year}}/{{month}}/AssistanceListings_DataGov_PUBLIC_WEEKLY_{{ymd}}.csv",
        "container": "csv",
        "cache_glob": "AssistanceListings_DataGov_PUBLIC_WEEKLY_*.csv",
        "notes": "Weekly. Federal assistance/grant PROGRAM catalog (not awards).",
    },
    "assistance_listings_grantsgov": {
        "access": "public",
        "date_kind": "ymd",
        "url": f"{FALEXTRACTS}/Assistance Listings/grantsgov/{{year}}/{{month}}/AssistanceListings_GrantsGov_PUBLIC_DAILY_{{ymd}}.csv",
        "container": "csv",
        "cache_glob": "AssistanceListings_GrantsGov_PUBLIC_DAILY_*.csv",
        "notes": "Daily, grants.gov schema variant of the assistance program catalog.",
    },
    "exclusions": {
        "access": "presigned",
        "date_kind": "julian",
        "url": f"{FALEXTRACTS}/Exclusions/Public V2/SAM_Exclusions_Public_Extract_V2_{{julian}}.ZIP",
        "container": "zip_csv",
        "cache_glob": "SAM_Exclusions_Public_Extract_V2_*",
        "extracts_filetype": "EXCLUSION",   # api_key route via the IAE Extracts Download API
        "notes": "Debarment list. Daily. 31 cols incl. Unique Entity ID (firms only, ~28%). Auto-fetched with SAM_API_KEY, or pass a presigned_url.",
    },
    "entity_registration": {
        "access": "presigned",
        "date_kind": "ymd",
        "url": f"{FALEXTRACTS}/Entity Registration/Public V2/SAM_PUBLIC_UTF-8_MONTHLY_V2_{{ymd}}.ZIP",
        "container": "zip_csv",
        "cache_glob": "SAM_PUBLIC_*MONTHLY_V2_*.ZIP",
        "notes": "Monthly, pipe-delimited. PREFER sam_extract.pull_entity_extract/submit_extract (clean JSON).",
    },
}


class FileExtractError(RuntimeError):
    pass


# ----------------------------------------------------------------------------------------------- #
# Public functions
# ----------------------------------------------------------------------------------------------- #
def download_file_extract(dataset: str, date=None, presigned_url: str = None,
                          refresh_after_days: int = 1) -> Path:
    """Download (or reuse from cache) a bulk flat-file extract; return the local Path.

    Public datasets resolve their own URL (stable, or latest available date via HEAD-walk).
    Presigned datasets (Exclusions/Entity) require ``presigned_url=`` — grab it from the browser
    Network tab (it expires in ~45 min). A fresh cached copy (< refresh_after_days old) is reused
    with no network call, so already-downloaded files are picked up automatically.
    """
    ds = _ds(dataset)

    cached = _find_cache(dataset, refresh_after_days)
    if cached is not None:
        print(f"Cache hit: {cached.name} (< {refresh_after_days}d old) — no download")
        return cached

    if ds["access"] == "presigned":
        if presigned_url:
            url = presigned_url
            source_url = url.split("?")[0]          # never persist the signature
        elif ds.get("extracts_filetype") and os.environ.get("SAM_API_KEY"):
            # api_key route (IAE Extracts Download API) — automatable; caches + manifests itself.
            return _download_via_extracts_api(dataset, date=date)
        else:
            raise FileExtractError(_presigned_help(dataset))
    else:
        url = _build_url(ds, _coerce_date(date)) if date is not None else _resolve_latest(dataset)[0]
        source_url = url

    dest = _cache_dir() / _basename_from_url(url)
    last_modified = _stream_download(url, dest)
    write_extract_manifest(
        dest, source_url, {"dataset": dataset}, None,
        source="sam_file_extract",
        extra={"last_modified": last_modified, "source_url": source_url, "access": ds["access"]},
    )
    print(f"Downloaded {dataset} → {dest} ({dest.stat().st_size:,} bytes)")
    return dest


def load_file_extract(dataset: str, date=None, presigned_url: str = None,
                      refresh_after_days: int = 1, **read_kw) -> pd.DataFrame:
    """Download/reuse a flat-file extract and parse it into a DataFrame (columns kept as-is)."""
    path = download_file_extract(dataset, date=date, presigned_url=presigned_url,
                                 refresh_after_days=refresh_after_days)
    return _read_to_df(path, _ds(dataset)["container"], **read_kw)


def check_exclusions(ueis_or_df, uei_col: str = "uei", presigned_url: str = None,
                     refresh_after_days: int = 1) -> pd.DataFrame:
    """Flag which of the given UEIs appear on the SAM debarment (Exclusions) list.

    Joins on the Exclusions ``Unique Entity ID`` column, which is populated only for FIRM/entity
    exclusions (~28% of records). Individual exclusions (the ~79% majority) have no UEI and must be
    matched by name instead — out of scope here. Returns the matching exclusion rows with the
    agency, type, and active/termination dates so you can check whether a party was excluded *at the
    time it won an award*.
    """
    if isinstance(ueis_or_df, pd.DataFrame):
        want = {str(u).strip().upper() for u in ueis_or_df[uei_col].dropna()}
    else:
        want = {str(u).strip().upper() for u in ueis_or_df if u and str(u).strip()}
    if not want:
        return pd.DataFrame()

    ex = load_file_extract("exclusions", presigned_url=presigned_url, refresh_after_days=refresh_after_days)
    col = "Unique Entity ID"
    if col not in ex.columns:
        raise FileExtractError(f"Exclusions file missing '{col}' column (got {list(ex.columns)[:5]}…)")
    hits = ex[ex[col].fillna("").str.strip().str.upper().isin(want)]
    keep = [col, "Classification", "Name", "Excluding Agency", "Exclusion Type",
            "Active Date", "Termination Date", "Record Status", "Cross-Reference"]
    return hits[[c for c in keep if c in hits.columns]].reset_index(drop=True)


def usaspending_award_archive(fiscal_year, award_type: str = "contracts", agency: str = "all",
                              download: bool = False, refresh_after_days: int = 30):
    """LAST RESORT — full-year USAspending award archive (GB-scale zips).

    USAspending's API has **no key and no rate limit**, so this is almost never the right tool:
      • For a targeted slice → use the `spending_by_award` API (paginate; ~10k-result ceiling per
        query, subdivide by agency/quarter if you exceed it). See references/usaspending_api.md.
      • For transaction-level detail → use FPDS (the `fpds` library) — usually better for that.
    Reach for the archive only to mirror a *whole* fiscal year/agency offline. By default this just
    resolves the URL + size (no download); pass ``download=True`` to actually pull the (~1-2 GB) file.

    Returns a dict {file_name, url, size_bytes, fiscal_year, type} — plus "path" when downloaded.
    """
    base = "https://api.usaspending.gov/api/v2/bulk_download/list_monthly_files/"
    params = {"agency": agency, "fiscal_year": int(fiscal_year), "type": award_type}
    r = requests.get(base, params=params, headers=UA, timeout=60)
    if r.status_code != 200:
        r = requests.post(base, json=params, headers=UA, timeout=60)
    r.raise_for_status()
    files = (r.json() or {}).get("monthly_files", [])
    if not files:
        raise FileExtractError(f"No archive for FY{fiscal_year} {award_type} ({agency}). Response: {r.text[:200]}")
    f = files[0]
    url = f["url"]
    head = requests.head(url, headers=UA, timeout=60)
    size = int(head.headers.get("Content-Length", 0)) or None
    info = {"file_name": f.get("file_name"), "url": url, "size_bytes": size,
            "fiscal_year": fiscal_year, "type": award_type}
    if not download:
        gb = f"{size/1e9:.2f} GB" if size else "unknown size"
        print(f"[last-resort] FY{fiscal_year} {award_type}: {info['file_name']} ({gb}). "
              f"Pass download=True to fetch; otherwise prefer the API/FPDS.")
        return info
    dest = _cache_dir() / Path(f["file_name"]).name
    lm = _stream_download(url, dest)
    write_extract_manifest(dest, url, params, None, source="usaspending_award_archive",
                           extra={"last_modified": lm, "source_url": url})
    info["path"] = str(dest)
    return info


# ----------------------------------------------------------------------------------------------- #
# URL resolution / download
# ----------------------------------------------------------------------------------------------- #
def _resolve_latest(dataset: str, max_back_days: int = 10):
    """Return (url, date) for the newest available file. Stable datasets ignore the date walk."""
    ds = _ds(dataset)
    if ds["date_kind"] is None:
        url = _enc(ds["url"])
        if not _head_ok(url):
            raise FileExtractError(f"{dataset} not reachable at {url}")
        return url, None
    today = datetime.date.today()
    for back in range(max_back_days + 1):
        d = today - datetime.timedelta(days=back)
        url = _build_url(ds, d)
        if _head_ok(url):
            return url, d
    raise FileExtractError(
        f"No {dataset} file found in the last {max_back_days} days (bucket listing is disabled, "
        "so we probe by date). Pass an explicit date=YYYYMMDD if you know it.")


def _build_url(ds: dict, d: datetime.date) -> str:
    repl = {"{ymd}": d.strftime("%Y%m%d"), "{year}": d.strftime("%Y"),
            "{month}": d.strftime("%m-%b"), "{julian}": d.strftime("%y%j")}
    t = ds["url"]
    for k, v in repl.items():
        t = t.replace(k, v)
    return _enc(t)


def _stream_download(url: str, dest: Path) -> str:
    r = requests.get(_enc(url), headers=UA, stream=True, timeout=600)
    if r.status_code != 200:
        raise FileExtractError(f"Download failed (HTTP {r.status_code}) for {dest.name}: {r.text[:200]}")
    with open(dest, "wb") as fh:
        for chunk in r.iter_content(chunk_size=1 << 20):
            if chunk:
                fh.write(chunk)
    return r.headers.get("Last-Modified")


def _head_ok(url: str) -> bool:
    try:
        return requests.head(_enc(url), headers=UA, timeout=30).status_code == 200
    except requests.RequestException:
        return False


def _download_via_extracts_api(dataset: str, date=None) -> Path:
    """Fetch a gated PUBLIC extract via the IAE Extracts Download API using SAM_API_KEY.

    Synchronous — a single GET returns the ZIP (no token/poll), so it costs exactly one call against
    the 10/day cap. This is the *automatable* alternative to the presigned bucket URL (which is
    no-quota but needs a browser). Verified live for fileType=EXCLUSION.
    """
    key = os.environ.get("SAM_API_KEY")
    if not key:
        raise FileExtractError("SAM_API_KEY not set — needed for the api_key extract route (or pass presigned_url=).")
    ftype = _ds(dataset)["extracts_filetype"]
    d = _coerce_date(date) if date is not None else datetime.date.today()
    mdy = d.strftime("%m/%d/%Y")
    r = requests.get(f"{EXTRACTS_API}?api_key={key}&fileType={ftype}&date={mdy}", headers=UA, timeout=600)
    if r.status_code == 429:
        raise FileExtractError(
            "SAM 10/day cap hit (HTTP 429) on the Extracts Download API. Use the presigned bucket "
            "route (pass presigned_url=) for a no-quota pull, or retry after the 00:00 UTC reset.")
    if r.status_code in (401, 403):
        raise FileExtractError(f"SAM rejected the key (HTTP {r.status_code}) on the Extracts Download API.")
    if r.content[:4] != b"PK\x03\x04":
        raise FileExtractError(f"Extracts API did not return a ZIP (HTTP {r.status_code}, "
                               f"{r.headers.get('Content-Type')}): {r.text[:200]}")
    dest = _cache_dir() / _extracts_filename(r, ftype, d)
    dest.write_bytes(r.content)
    write_extract_manifest(
        dest, f"{EXTRACTS_API}?fileType={ftype}&date={mdy}",   # api_key omitted from manifest
        {"dataset": dataset, "fileType": ftype, "date": mdy}, None,
        source="sam_extracts_api",
        extra={"last_modified": r.headers.get("Last-Modified"), "source_url": EXTRACTS_API},
    )
    print(f"Downloaded {dataset} via api_key extracts route → {dest} ({dest.stat().st_size:,} bytes, 1 call)")
    return dest


def _extracts_filename(r, ftype: str, d: datetime.date) -> str:
    """Use the server's Content-Disposition filename; else reconstruct the conventional name."""
    m = re.search(r'filename="?([^";]+)', r.headers.get("Content-Disposition", "") or "")
    if m:
        return m.group(1).strip()
    stem = {"EXCLUSION": "SAM_Exclusions_Public_Extract_V2", "ENTITY": "SAM_PUBLIC_MONTHLY_V2"}.get(ftype, f"SAM_{ftype}")
    return f"{stem}_{d.strftime('%y%j')}.ZIP"


# ----------------------------------------------------------------------------------------------- #
# Parsing / cache
# ----------------------------------------------------------------------------------------------- #
def _read_to_df(path: Path, container: str, **read_kw) -> pd.DataFrame:
    path = Path(path)
    read_kw.setdefault("dtype", str)  # preserve codes, ZIPs, UEIs; avoid mixed-type warnings
    if path.suffix.lower() == ".zip" or container == "zip_csv":
        with zipfile.ZipFile(path) as z:
            members = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not members:
                raise FileExtractError(f"No CSV inside {path.name}: {z.namelist()}")
            return _read_csv_any(z.read(members[0]), **read_kw)
    return _read_csv_any(path, **read_kw)


def _read_csv_any(src, **read_kw) -> pd.DataFrame:
    """Read a CSV (path or raw bytes) trying encodings in turn. These GSA extracts are usually
    Windows-1252, not UTF-8 (e.g. curly quotes = byte 0x94); latin-1 is the always-decodable floor."""
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            buf = io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src
            return pd.read_csv(buf, encoding=enc, **read_kw)
        except UnicodeDecodeError:
            continue
    raise FileExtractError("Could not decode CSV with utf-8/cp1252/latin-1")


def _cache_dir() -> Path:
    override = os.environ.get("SAM_EXTRACT_CACHE_DIR")
    d = Path(override) if override else Path(__file__).resolve().parent.parent / "references" / "data" / "sam_extract"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_cache(dataset: str, refresh_after_days: int):
    """Newest cached file matching the dataset's glob, if younger than refresh_after_days."""
    matches = [m for m in _cache_dir().glob(_ds(dataset)["cache_glob"]) if not m.name.endswith(".manifest.json")]
    if not matches:
        return None
    newest = max(matches, key=lambda p: p.stat().st_mtime)
    age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(newest.stat().st_mtime)).days
    return newest if age_days <= refresh_after_days else None


# ----------------------------------------------------------------------------------------------- #
# Small utilities
# ----------------------------------------------------------------------------------------------- #
def _ds(dataset: str) -> dict:
    if dataset not in DATASETS:
        raise FileExtractError(f"Unknown dataset '{dataset}'. Known: {', '.join(DATASETS)}")
    return DATASETS[dataset]


def _enc(url: str) -> str:
    return url.replace(" ", "%20")


def _basename_from_url(url: str) -> str:
    return unquote(Path(urlsplit(url).path).name)


def _coerce_date(date):
    if hasattr(date, "strftime"):
        return date
    return datetime.datetime.strptime(str(date).replace("-", ""), "%Y%m%d").date()


def _presigned_help(dataset: str) -> str:
    if dataset == "entity_registration":
        return ("'entity_registration' (monthly pipe-delimited ZIP) is gated — but you don't need it. "
                "Use the JSON Entity Extract API instead: sam_extract.submit_extract({'registrationStatus':'A'}) "
                "then download_extract(...). Cleaner, normalized, and already wired up.")
    return (
        f"'{dataset}' is a gated 'Public V2' extract. Two ways to fetch it:\n"
        "  (a) api_key route (automatable): set SAM_API_KEY and call again — it pulls via the IAE "
        "Extracts Download API in a single GET (counts against the 10/day cap); or\n"
        "  (b) presigned URL (no quota): in the browser, Data Services → the dataset → Download → "
        "copy the request URL from the Network tab (it has X-Amz-Signature, ~45-min validity) and "
        "pass it as presigned_url=. (The data is public record, but the S3 objects aren't anonymously "
        "readable, and a SAM api_key can't presign S3 itself.)")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if args and args[0] == "usaspending":
        yr = args[1] if len(args) > 1 else datetime.date.today().year
        print(usaspending_award_archive(yr, args[2] if len(args) > 2 else "contracts"))
    elif args:
        name = args[0]
        ds = _ds(name)
        if ds["access"] == "public":
            url, d = _resolve_latest(name)
            print(f"{name}: latest = {url}" + (f" (date {d})" if d else " (stable)"))
        else:
            print(f"{name}: presigned — {_presigned_help(name)}")
    else:
        print("datasets:", ", ".join(DATASETS))
        print("usage: python file_extracts.py <dataset> | usaspending <FY> [contracts|assistance]")
