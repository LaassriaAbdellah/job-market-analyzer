"""Free-Work job collection from the structured Nuxt payload."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from common import BASE_DIR, DATA_DIR, create_http_session, canonicalize_url, deduplicate_jobs, stable_job_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

FREEWORK_ROOT = "https://www.free-work.com"
NUXT_REACTIVE_TAGS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "Computed", "ComputedRef"}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/",
}
HTTP = create_http_session()


class NuxtPayloadDecoder:
    """Resolve Nuxt's flattened object table using references found in the payload."""

    def __init__(self, payload: Any):
        if not isinstance(payload, list):
            raise ValueError("Le contenu __NUXT_DATA__ doit être une liste sérialisée.")
        self.payload = payload
        self.cache: Dict[int, Any] = {}
        self.active: set[int] = set()

    def decode(self) -> Any:
        if not self.payload:
            raise ValueError("Le contenu __NUXT_DATA__ est vide.")
        return self._reference(0)

    def _reference(self, index: int) -> Any:
        if index < 0 or index >= len(self.payload):
            raise ValueError(f"Référence Nuxt hors limites : {index}.")
        if index in self.cache:
            return self.cache[index]
        if index in self.active:
            raise ValueError(f"Référence Nuxt cyclique : {index}.")
        self.active.add(index)
        try:
            decoded = self._decode_node(self.payload[index])
            self.cache[index] = decoded
            return decoded
        finally:
            self.active.remove(index)

    def _decode_child(self, value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool):
            return self._reference(value)
        return self._decode_node(value)

    def _decode_node(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._decode_child(child) for key, child in value.items()}
        if isinstance(value, list):
            if len(value) == 2 and isinstance(value[0], str) and value[0] in NUXT_REACTIVE_TAGS:
                return self._decode_child(value[1])
            return [self._decode_child(child) for child in value]
        return value


def _find_jobs_search(value: Any) -> List[Dict[str, Any]]:
    """Find a decoded jobs-search-* state without relying on table positions."""
    if isinstance(value, dict):
        for key, child in value.items():
            if (
                isinstance(key, str)
                and key.startswith("jobs-search-")
                and isinstance(child, dict)
                and isinstance(child.get("jobs"), list)
            ):
                return child["jobs"]
        for child in value.values():
            found = _find_jobs_search(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_jobs_search(child)
            if found:
                return found
    return []


def extract_freework_search(html: str) -> Dict[str, Any] | None:
    """Decode the matching Nuxt search object, including its pagination metadata."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NUXT_DATA__", attrs={"type": "application/json"})
    if script is None:
        logging.warning("Réponse Free-Work sans script __NUXT_DATA__.")
        return None
    try:
        payload = json.loads(script.string or script.get_text())
        decoded = NuxtPayloadDecoder(payload).decode()
    except (json.JSONDecodeError, ValueError, RecursionError) as error:
        logging.error("Impossible de décoder __NUXT_DATA__ Free-Work : %s", error)
        return None
    result: Dict[str, Any] | None = None

    def find_search(value: Any) -> None:
        nonlocal result
        if result is not None:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if key.startswith("jobs-search-") and isinstance(child, dict) and isinstance(child.get("jobs"), list):
                    result = child
                    return
            for child in value.values():
                find_search(child)
        elif isinstance(value, list):
            for child in value:
                find_search(child)

    find_search(decoded)
    if result is None:
        logging.warning("Aucune section jobs-search-* trouvée dans __NUXT_DATA__.")
    return result


def extract_freework_jobs(html: str) -> List[Dict[str, Any]]:
    """Parse and decode the jobs array from Nuxt's application state."""
    search = extract_freework_search(html)
    return [job for job in search.get("jobs", []) if isinstance(job, dict)] if search else []


def _clean_html(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(BeautifulSoup(str(value), "html.parser").get_text(" ").split())


def _freework_job_url(job: Dict[str, Any]) -> str:
    for key in ("cardProps", "cardAltProps"):
        props = job.get(key)
        route = props.get("to") if isinstance(props, dict) else None
        if isinstance(route, dict):
            route = route.get("path") or route.get("fullPath") or route.get("href")
        if isinstance(route, str) and route.strip():
            return canonicalize_url(urljoin(FREEWORK_ROOT, route.strip()))

    slug = job.get("slug")
    parent = job.get("job")
    parent_slug = parent.get("slug") if isinstance(parent, dict) else None
    if slug and parent_slug:
        path = f"/fr/tech-it/job-mission/{parent_slug}/{slug}"
        return canonicalize_url(urljoin(FREEWORK_ROOT, path))
    return ""


def normalize_freework_record(job: Dict[str, Any], keyword: str) -> Dict[str, Any]:
    """Map one decoded Free-Work posting to the raw-job envelope used by this project."""
    company = job.get("company")
    location = job.get("location")
    skills = job.get("skills")
    contracts = job.get("contracts")
    employment_type = job.get("jobPostingType") or (
        contracts[0] if isinstance(contracts, list) and contracts else None
    )
    remote_mode = str(job.get("remoteMode") or "").strip().lower()
    remote = True if remote_mode in {"full", "partial", "remote", "fully_remote"} else (
        False if remote_mode in {"none", "no", "on_site", "onsite"} else None
    )
    url = _freework_job_url(job)
    source_id = job.get("id")
    company_name = company.get("name") if isinstance(company, dict) else ""
    job_id = f"freework_{source_id}" if source_id not in (None, "") else stable_job_id(
        "freework", url, job.get("title"), company_name
    )
    return {
        "id": job_id,
        "title": " ".join(str(job.get("title") or "").split()),
        "company": " ".join(str(company_name or "").split()),
        "category": keyword,
        "location": " ".join(str(location.get("label") or "").split()) if isinstance(location, dict) else "",
        "url": url,
        "published_at": job.get("publishedAt"),
        "employment_type": employment_type,
        "remote": remote,
        "skills": [skill["name"] for skill in skills if isinstance(skill, dict) and skill.get("name")]
        if isinstance(skills, list) else [],
        "description": _clean_html(job.get("description")),
    }


def scrape_freework_broad_tech(
    keywords: List[str], max_pages_per_keyword: int | None = None, request_delay: float = 1.5,
    errors: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Collect Free-Work listings from Nuxt state and deduplicate across searches."""
    logging.info("--- DÉMARRAGE DE LA COLLECTE STRUCTURÉE FREE-WORK ---")
    scraped_jobs: List[Dict[str, Any]] = []
    successful_pages = 0
    page_limit = max_pages_per_keyword or max(1, int(os.getenv("FREEWORK_MAX_PAGES_PER_KEYWORD", "10")))
    for keyword in keywords:
        pages_succeeded = 0
        total_items = None
        for page in range(1, page_limit + 1):
            url = f"{FREEWORK_ROOT}/fr/tech-it/jobs"
            try:
                response = HTTP.get(
                    url,
                    params={"query": keyword, "page": page},
                    headers=HEADERS,
                    timeout=10,
                )
                response.raise_for_status()
                search = extract_freework_search(response.text)
                if search is None:
                    raise ValueError("Payload Nuxt absent ou invalide.")
                successful_pages += 1
                found_jobs = [job for job in search.get("jobs", []) if isinstance(job, dict)]
                pages_succeeded += 1
                if isinstance(search.get("totalItems"), int):
                    total_items = search["totalItems"]
                valid_jobs = []
                for source_job in found_jobs:
                    job = normalize_freework_record(source_job, keyword)
                    if not job["title"] or not job["url"] or not job["id"]:
                        logging.warning(
                            "Offre Free-Work invalide ignorée (id=%r, titre=%r).",
                            job["id"], job["title"],
                        )
                        continue
                    valid_jobs.append(job)

                previous_count = len(scraped_jobs)
                scraped_jobs = deduplicate_jobs([*scraped_jobs, *valid_jobs])
                duplicate_count = len(valid_jobs) - (len(scraped_jobs) - previous_count)
                logging.info(
                    "Free-Work '%s' page %s : %s trouvées, %s valides, %s doublons.",
                    keyword, page, len(found_jobs), len(valid_jobs), duplicate_count,
                )
                if total_items is not None and (not found_jobs or page * len(found_jobs) >= total_items):
                    break
                if not found_jobs:
                    break
                if request_delay > 0:
                    time.sleep(request_delay)
            except requests.RequestException as error:
                logging.error("Erreur HTTP Free-Work pour '%s' page %s : %s", keyword, page, error)
                if errors is not None:
                    errors.append(f"recherche '{keyword}', page {page}: {error}")
            except (ValueError, TypeError, KeyError) as error:
                logging.error("Erreur de lecture Free-Work pour '%s' page %s : %s", keyword, page, error)
                if errors is not None:
                    errors.append(f"recherche '{keyword}', page {page}: {error}")
        if pages_succeeded == 0:
            logging.error("Aucune page Free-Work valide pour la recherche '%s'.", keyword)
    if keywords and successful_pages == 0:
        raise RuntimeError("Toutes les requêtes Free-Work ont échoué.")
    logging.info("Collecte Free-Work terminée : %s offres uniques.", len(scraped_jobs))
    return scraped_jobs


def append_to_raw_jobs(
    new_jobs: List[Dict[str, Any]], filepath: Path = DATA_DIR / "raw_jobs.json"
) -> Dict[str, int]:
    """Append collected postings to the UTF-8 raw file and deduplicate the result."""
    output_path = Path(filepath)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    existing_jobs: List[Dict[str, Any]] = []
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as source_file:
            try:
                existing_jobs = json.load(source_file)
            except json.JSONDecodeError as error:
                logging.error("Le fichier '%s' contient un JSON invalide : %s", output_path, error)
                raise
    if not new_jobs:
        logging.warning("Aucune nouvelle offre reçue ; le fichier brut existant reste inchangé.")
        return {
            "existing": len(existing_jobs),
            "new": 0,
            "total": len(existing_jobs),
            "duplicates_removed": 0,
        }
    combined = [*existing_jobs, *new_jobs]
    unique_jobs = deduplicate_jobs(combined)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(unique_jobs, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    stats = {
        "existing": len(existing_jobs),
        "new": len(new_jobs),
        "total": len(unique_jobs),
        "duplicates_removed": len(combined) - len(unique_jobs),
    }
    logging.info(
        "Fichier '%s' mis à jour : %s offres uniques (%s doublons supprimés).",
        output_path, stats["total"], stats["duplicates_removed"],
    )
    return stats


if __name__ == "__main__":
    tech_keywords = ["developpeur", "devops", "cloud", "intelligence artificielle", "cybersecurite"]
    html_jobs = scrape_freework_broad_tech(tech_keywords, max_pages_per_keyword=1)
    save_stats = append_to_raw_jobs(html_jobs)
    print("\n5 exemples Free-Work")
    for job in html_jobs[:5]:
        print(json.dumps({key: job.get(key) for key in (
            "id", "title", "company", "location", "published_at", "skills", "url"
        )}, ensure_ascii=False, indent=2))
    print("\nBilan sauvegarde :", json.dumps(save_stats, ensure_ascii=False))
