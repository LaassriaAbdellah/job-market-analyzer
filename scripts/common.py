"""Shared paths and helpers for the job collection scripts."""

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_JOBS_PATH = RAW_DIR / "latest_jobs.json"
PROCESSED_DIR = DATA_DIR / "processed"
NORMALIZED_JOBS_PATH = PROCESSED_DIR / "normalized_jobs.json"
CONFIG_DIR = BASE_DIR / "config"


def create_http_session() -> requests.Session:
    """Create a GET-only client that retries transient server/rate-limit errors."""
    retries = Retry(
        total=int(os.getenv("HTTP_RETRIES", "3")),
        connect=int(os.getenv("HTTP_RETRIES", "3")),
        read=int(os.getenv("HTTP_RETRIES", "3")),
        status=int(os.getenv("HTTP_RETRIES", "3")),
        backoff_factor=float(os.getenv("HTTP_RETRY_BACKOFF", "1")),
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def external_id_for(source: str, job_id: Any) -> str:
    """Return the source's ID, or the stable hash suffix used when it has none."""
    value = str(job_id or "").strip()
    aliases = {source, "freework" if source == "free-work" else source}
    for alias in aliases:
        prefix = f"{alias}_"
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


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
    seen_external_ids: Set[tuple[str, str]] = set()
    for job in jobs:
        job_id = str(job.get("id") or "").strip()
        source = str(job.get("source") or "").strip()
        external_id = str(job.get("external_id") or "").strip()
        source_identity = (source, external_id) if source and external_id else None
        canonical_url = canonicalize_url(job.get("url"))
        duplicate = (
            (source_identity is not None and source_identity in seen_external_ids)
            or (job_id and job_id in seen_ids)
            or (canonical_url and canonical_url in seen_urls)
        )
        if source_identity:
            seen_external_ids.add(source_identity)
        if job_id:
            seen_ids.add(job_id)
        if canonical_url:
            seen_urls.add(canonical_url)
        if duplicate:
            continue
        unique.append(job)
    return unique
