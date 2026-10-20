import json
import logging
import os
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from common import BASE_DIR, DATA_DIR, create_http_session, deduplicate_jobs, stable_job_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}
HTTP = create_http_session()


def _require_job_payload(payload: Any, source: str) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError(f"Réponse {source} invalide : propriété 'jobs' absente ou incorrecte.")
    return [job for job in payload["jobs"] if isinstance(job, dict)]

def fetch_remotive_tech_jobs(categories: List[str], errors: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Récupère les offres pour plusieurs catégories Tech sur Remotive."""
    all_jobs = []
    failed_categories = []
    for cat in categories:
        url = "https://remotive.com/api/remote-jobs"
        try:
            logging.info(f"Scraping Remotive - Catégorie : '{cat}'...")
            response = HTTP.get(url, params={"category": cat}, headers=HEADERS, timeout=20)
            response.raise_for_status()
            payload = response.json()
            raw_jobs = _require_job_payload(payload, "Remotive")
            if payload.get("job-count") is not None and int(payload["job-count"]) != len(raw_jobs):
                raise ValueError(
                    f"Remotive annonce {payload['job-count']} résultats, {len(raw_jobs)} reçus pour '{cat}'."
                )
            
            for job in raw_jobs:
                job_url = job.get("url")
                all_jobs.append({
                    "id": f"remotive_{job['id']}" if job.get("id") is not None else stable_job_id("remotive", job_url, job.get("title"), job.get("company_name")),
                    "title": job.get("title"),
                    "company": job.get("company_name", "Inconnue"),
                    "category": job.get("category", cat),
                    "location": job.get("candidate_required_location", "Non spécifiée"),
                    "url": job.get("url"),
                    "published_at": job.get("publication_date"),
                    "description": job.get("description", "")
                })
        except (requests.RequestException, ValueError, TypeError) as e:
            failed_categories.append(cat)
            if errors is not None:
                errors.append(f"catégorie {cat}: {e}")
            logging.error(f"Erreur Remotive pour la catégorie '{cat}' : {e}")

    if categories and len(failed_categories) == len(categories):
        raise RuntimeError("Toutes les requêtes Remotive ont échoué.")
    if failed_categories:
        logging.warning("Remotive incomplet, catégories en échec : %s", ", ".join(failed_categories))
            
    return all_jobs

def fetch_jobicy_tech_jobs(industries: List[str], errors: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Récupère les offres pour plusieurs industries Tech sur Jobicy."""
    all_jobs = []
    failed_industries = []
    page_limit = max(1, int(os.getenv("JOBICY_MAX_PAGES_PER_FILTER", "10")))
    page_size = min(200, max(1, int(os.getenv("JOBICY_PAGE_SIZE", "100"))))
    for ind in industries:
        cursor = None
        seen_cursors = set()
        pages_read = 0
        try:
            while pages_read < page_limit:
                params = {"industry": ind, "count": page_size}
                if cursor:
                    params["cursor"] = cursor
                logging.info("Scraping Jobicy - Industrie '%s', page %s...", ind, pages_read + 1)
                response = HTTP.get(
                    "https://jobicy.com/api/v2/remote-jobs", params=params, headers=HEADERS, timeout=20
                )
                response.raise_for_status()
                payload = response.json()
                raw_jobs = _require_job_payload(payload, "Jobicy")
                if payload.get("success") is False:
                    raise ValueError(f"Jobicy indique un échec : {payload.get('error', 'erreur inconnue')}")

                for job in raw_jobs:
                    job_url = job.get("url")
                    all_jobs.append({
                        "id": f"jobicy_{job['id']}" if job.get("id") is not None else stable_job_id(
                            "jobicy", job_url, job.get("jobTitle"), job.get("companyName")
                        ),
                        "title": job.get("jobTitle"),
                        "company": job.get("companyName"),
                        "category": ind,
                        "location": job.get("jobGeo"),
                        "url": job_url,
                        "published_at": job.get("pubDate"),
                        "employment_type": job.get("jobType"),
                        "description": job.get("jobDescription", ""),
                    })

                pages_read += 1
                next_cursor = payload.get("nextCursor")
                if not next_cursor:
                    break
                if next_cursor in seen_cursors:
                    raise ValueError(f"Jobicy a renvoyé un curseur répété pour '{ind}'.")
                seen_cursors.add(next_cursor)
                cursor = next_cursor
            if pages_read == page_limit and cursor:
                logging.warning("Jobicy : limite de %s pages atteinte pour '%s'.", page_limit, ind)
        except (requests.RequestException, ValueError, TypeError) as e:
            failed_industries.append(ind)
            if errors is not None:
                errors.append(f"industrie {ind}: {e}")
            logging.error("Erreur Jobicy pour l'industrie '%s' : %s", ind, e)

    if industries and len(failed_industries) == len(industries):
        raise RuntimeError("Toutes les requêtes Jobicy ont échoué.")
    if failed_industries:
        logging.warning("Jobicy incomplet, industries en échec : %s", ", ".join(failed_industries))
            
    return all_jobs

def run_broad_tech_collector(limit: int | None = None) -> List[Dict[str, Any]]:
    """Collecte globale des offres Informatique (Dev, AI, Data, DevOps)."""
    logging.info("--- DÉMARRAGE DE LA COLLECTE INFORMATIQUE GLOBALE ---")
    
    # Catégories ciblées
    remotive_cats = ["software-dev", "data", "devops"]
    jobicy_inds = ["dev", "data-science", "supporting"]
    
    all_jobs = []
    all_jobs.extend(fetch_remotive_tech_jobs(remotive_cats))
    all_jobs.extend(fetch_jobicy_tech_jobs(jobicy_inds))
    
    # Déduplication par ID unique
    unique_jobs = deduplicate_jobs(all_jobs)
    if limit is not None:
        unique_jobs = unique_jobs[:limit]
    
    logging.info(f"Collecte terminée : {len(unique_jobs)} offres IT brutes récupérées.")
    return unique_jobs

def save_raw_jobs(jobs: List[Dict[str, Any]], filepath: Path = DATA_DIR / "raw_jobs.json") -> None:
    output_path = Path(filepath)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    existing_jobs = []
    if output_path.exists():
        try:
            with output_path.open("r", encoding="utf-8") as f:
                existing_jobs = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logging.error("Impossible de lire les offres existantes dans '%s': %s", output_path, e)
            raise
    unique_jobs = deduplicate_jobs([*existing_jobs, *jobs])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(unique_jobs, f, ensure_ascii=False, indent=4)
    logging.info("Fichier '%s' enregistré : %s offres uniques.", output_path, len(unique_jobs))

if __name__ == "__main__":
    jobs = run_broad_tech_collector()
    save_raw_jobs(jobs)
