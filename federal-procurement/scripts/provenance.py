"""Data-provenance helpers for the federal-procurement skill.

Every API call in this skill must persist its raw response before any analysis runs, so that
findings are reproducible and auditable. This module is the single home for that logic so that
both the inline snippets in SKILL.md and the bulk extract module (``sam_extract.py``) call the
*same* helper instead of drifting apart.

Two helpers:

- ``save_api_response`` — for in-memory JSON responses (the original helper, moved here verbatim
  from SKILL.md so it is importable). Wraps the payload with query params + a fetch timestamp and
  writes it under ``data/raw/`` (override with ``FPDS_DATA_DIR``).
- ``write_extract_manifest`` — for the bulk-extract case, where the "raw response" is a large file
  already sitting on disk (a cached .zip). Instead of re-serialising a million records through
  ``save_api_response``, we leave the file in place and drop a small manifest sidecar next to it
  recording the resolved URL, timestamp, record count, and a sha256 of the bytes.
"""

import hashlib
import json
import os
import time
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
        "query_params": _redact(params),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "record_count": len(data) if isinstance(data, list) else 1,
        "data": data,
    }
    path = raw_dir / filename
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Saved {path} ({len(data) if isinstance(data, list) else 1} records)")
    return path


def sha256_file(path) -> str:
    """Return the hex sha256 of a file, read in chunks so large extracts don't blow memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_extract_manifest(cache_path, resolved_url: str, params: dict, record_count: int,
                           source: str = "sam_entity_extract", extra: dict = None):
    """Write a provenance manifest sidecar next to a cached bulk-extract file.

    The extract file itself is the persisted raw response — we don't duplicate its contents. The
    manifest captures everything needed to audit/repro the pull: the resolved URL (api_key stripped),
    the request params, when it was fetched, the record count, and the sha256 of the downloaded bytes
    so tampering or truncation is detectable.

    ``source`` labels the dataset; ``extra`` is merged into the manifest (e.g.
    ``{"last_modified": ..., "source_url": ...}``) for file-extract provenance. Callers must strip
    any presigned-URL signature / api_key before passing it in ``resolved_url``/``extra``.
    """
    cache_path = Path(cache_path)
    manifest_path = cache_path.with_suffix(cache_path.suffix + ".manifest.json")
    manifest = {
        "source": source,
        "resolved_url": _redact_url(resolved_url),
        "request_params": _redact(params),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "record_count": record_count,
        "sha256": sha256_file(cache_path),
        "cache_file": str(cache_path),
    }
    if extra:
        manifest.update(extra)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    rc = record_count if record_count is not None else "?"
    print(f"Wrote manifest {manifest_path} (sha256={manifest['sha256'][:12]}…, {rc} records)")
    return manifest_path


def _redact(params) -> dict:
    """Return a copy of params with the API key blanked, so secrets never land in provenance."""
    if not isinstance(params, dict):
        return params
    out = dict(params)
    for k in ("api_key", "apikey", "x-api-key", "X-Api-Key"):
        if k in out:
            out[k] = "***REDACTED***"
    return out


def _redact_url(url: str) -> str:
    """Strip an api_key query value out of a URL for safe logging."""
    import re

    return re.sub(r"(api_key=)[^&]+", r"\1***REDACTED***", url or "")
