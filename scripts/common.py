"""Shared paths and helpers for the job collection scripts."""

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urlsplit, urlunsplit

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"


def canonicalize_url(url: Optional[str]) -> str:
    """Remove fragments, query parameters, and trailing slashes from a URL."""
    if not url or not url.strip():
        return ""
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return url.strip()
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def stable_job_id(source: str, url: Optional[str], *fallback_fields: Any) -> str:
    """Build a reproducible ID from a canonical URL or stable fallback fields."""
    canonical_url = canonicalize_url(url)
    identity = f"{source}:{canonical_url}" if canonical_url else f"{source}:" + "|".join(
        str(value or "").strip().lower() for value in fallback_fields
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{source}_{digest}"


def deduplicate_jobs(jobs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the first job for each stable ID or canonical URL."""
    unique: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    seen_urls: Set[str] = set()
    for job in jobs:
        job_id = str(job.get("id") or "").strip()
        canonical_url = canonicalize_url(job.get("url"))
        if (job_id and job_id in seen_ids) or (canonical_url and canonical_url in seen_urls):
            continue
        if job_id:
            seen_ids.add(job_id)
        if canonical_url:
            seen_urls.add(canonical_url)
        unique.append(job)
    return unique
