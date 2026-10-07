"""Convert source-specific job records to the shared internal schema."""

import json
import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from common import BASE_DIR, DATA_DIR, canonicalize_url, deduplicate_jobs, stable_job_id

NORMALIZED_FIELDS = (
    "id",
    "title",
    "company",
    "location",
    "description",
    "url",
    "source",
    "published_at",
    "employment_type",
    "remote",
    "skills",
)
SOURCE_ALIASES = {
    "remotive": "remotive",
    "jobicy": "jobicy",
    "freework": "free-work",
    "free-work": "free-work",
}
PLACEHOLDER_TITLES = {"titre non spécifié", "titre non specifie", "n/a", "unknown"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item).strip() for item in value if item is not None and str(item).strip())
    return re.sub(r"\s+", " ", str(value)).strip()


def _first(job: Dict[str, Any], *names: str) -> Any:
    for name in names:
        value = job.get(name)
        if value is not None and value != "":
            return value
    return None


def _description(value: Any) -> str:
    raw = _text(value)
    if not raw:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(raw, "html.parser").get_text(" ")).strip()


def _published_at(value: Any) -> Optional[str]:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
    return parsed.isoformat()


def _employment_type(value: Any) -> Optional[str]:
    raw = _text(value)
    if not raw:
        return None
    key = re.sub(r"[_\s]+", "-", raw.lower())
    aliases = {
        "fulltime": "full-time",
        "full-time": "full-time",
        "parttime": "part-time",
        "part-time": "part-time",
        "contractor": "contract",
        "contract": "contract",
        "freelance": "freelance",
        "internship": "internship",
        "temporary": "temporary",
    }
    return aliases.get(key, raw)


def _remote(job: Dict[str, Any], location: str) -> Optional[bool]:
    value = _first(job, "remote", "is_remote", "remote_allowed")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        key = value.strip().lower()
        if key in {"true", "yes", "1", "remote", "fully remote"}:
            return True
        if key in {"false", "no", "0", "on-site", "onsite", "office"}:
            return False
    location_key = location.lower()
    if re.search(r"\b(remote|télétravail|teletravail|work from home)\b", location_key):
        return True
    if re.search(r"\b(on[- ]?site|onsite|office[- ]based)\b", location_key):
        return False
    return None


def _source(job: Dict[str, Any], source: Optional[str]) -> Optional[str]:
    candidate = source or job.get("source")
    if not candidate:
        job_id = _text(job.get("id")).lower()
        candidate = next((prefix for prefix in SOURCE_ALIASES if job_id.startswith(prefix + "_")), None)
    return SOURCE_ALIASES.get(_text(candidate).lower()) if candidate else None


def _base_normalize(job: Dict[str, Any], source: str, title: Any, company: Any,
                    location: Any, description: Any, url: Any, published_at: Any,
                    employment_type: Any = None) -> Dict[str, Any]:
    normalized_url = canonicalize_url(_text(url))
    job_id = _text(job.get("id")) or stable_job_id(source, normalized_url, title, company)
    normalized_location = _text(location)
    skills = job.get("skills")
    if not isinstance(skills, list):
        skills = []
    clean_skills = list(dict.fromkeys(_text(skill) for skill in skills if _text(skill)))
    return {
        "id": job_id,
        "title": _text(title),
        "company": _text(company) or "Inconnue",
        "location": normalized_location,
        "description": _description(description),
        "url": normalized_url,
        "source": source,
        "published_at": _published_at(published_at),
        "employment_type": _employment_type(employment_type),
        "remote": _remote(job, normalized_location),
        "skills": clean_skills,
    }


def normalize_remotive_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return _base_normalize(
        job, "remotive", _first(job, "title"), _first(job, "company", "company_name"),
        _first(job, "location", "candidate_required_location"),
        _first(job, "description"), _first(job, "url"),
        _first(job, "published_at", "publication_date"),
        _first(job, "employment_type", "job_type"),
    )


def normalize_jobicy_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return _base_normalize(
        job, "jobicy", _first(job, "title", "jobTitle"), _first(job, "company", "companyName"),
        _first(job, "location", "jobGeo"), _first(job, "description", "jobDescription"),
        _first(job, "url"), _first(job, "published_at", "pubDate"),
        _first(job, "employment_type", "jobType"),
    )


def normalize_freework_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return _base_normalize(
        job, "free-work", _first(job, "title"), _first(job, "company"),
        _first(job, "location"), _first(job, "description"), _first(job, "url"),
        _first(job, "published_at"), _first(job, "employment_type"),
    )


NORMALIZERS = {
    "remotive": normalize_remotive_job,
    "jobicy": normalize_jobicy_job,
    "free-work": normalize_freework_job,
}


def normalize_job(job: Dict[str, Any], source: Optional[str] = None) -> Optional[Dict[str, Any]]:
    source_name = _source(job, source)
    if not source_name:
        logging.warning("Offre ignorée : source inconnue (id=%r).", job.get("id"))
        return None
    normalized = NORMALIZERS[source_name](job)
    missing = [field for field in ("id", "title", "source", "url") if not normalized.get(field)]
    parsed_url = urlsplit(normalized["url"])
    if not parsed_url.scheme or not parsed_url.netloc or parsed_url.scheme not in {"http", "https"}:
        missing.append("URL absolue HTTP(S)")
    if normalized["title"].casefold() in PLACEHOLDER_TITLES:
        missing.append("titre exploitable")
    if missing:
        logging.warning("Offre ignorée (id=%r) : champ(s) invalide(s) : %s.", job.get("id"), ", ".join(missing))
        return None
    return {field: normalized[field] for field in NORMALIZED_FIELDS}


def normalize_jobs(jobs: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int, int]:
    normalized: List[Dict[str, Any]] = []
    rejected = 0
    for job in jobs:
        if not isinstance(job, dict):
            logging.warning("Offre ignorée : l'entrée n'est pas un objet JSON.")
            rejected += 1
            continue
        result = normalize_job(job)
        if result is None:
            rejected += 1
        else:
            normalized.append(result)
    unique = deduplicate_jobs(normalized)
    duplicates_removed = len(normalized) - len(unique)
    return unique, rejected, duplicates_removed


def run_normalization(
    raw_path: Path = DATA_DIR / "raw_jobs.json",
    output_path: Path = DATA_DIR / "processed" / "normalized_jobs.json",
) -> Dict[str, Any]:
    resolved_raw = Path(raw_path)
    resolved_output = Path(output_path)
    if not resolved_raw.is_absolute():
        resolved_raw = BASE_DIR / resolved_raw
    if not resolved_output.is_absolute():
        resolved_output = BASE_DIR / resolved_output
    with resolved_raw.open("r", encoding="utf-8") as source_file:
        raw_jobs = json.load(source_file)
    normalized, rejected, duplicates_removed = normalize_jobs(raw_jobs)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    with resolved_output.open("w", encoding="utf-8") as output_file:
        json.dump(normalized, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    stats = {
        "raw_count": len(raw_jobs),
        "normalized_count": len(normalized),
        "rejected_count": rejected,
        "duplicates_removed": duplicates_removed,
        "source_counts": {},
        "missing_fields": {
            field: sum(not job.get(field) for job in normalized)
            for field in ("title", "company", "location", "description", "url", "published_at")
        },
        "output_path": str(resolved_output),
    }
    for job in normalized:
        stats["source_counts"][job["source"]] = stats["source_counts"].get(job["source"], 0) + 1
    logging.info(
        "Normalisation terminée : %s brutes, %s normalisées, %s rejetées, %s doublons supprimés. Sortie : %s",
        stats["raw_count"], stats["normalized_count"], rejected, duplicates_removed, resolved_output,
    )
    for source_name in ("remotive", "jobicy", "free-work"):
        logging.info("Offres normalisées depuis %s : %s", source_name, stats["source_counts"].get(source_name, 0))
    for field, count in stats["missing_fields"].items():
        logging.info("Champ %s absent : %s", field, count)
    return stats


if __name__ == "__main__":
    run_normalization()
