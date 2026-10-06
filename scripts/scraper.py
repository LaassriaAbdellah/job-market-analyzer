import os
import json
import logging
import requests
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

def fetch_remotive_tech_jobs(categories: List[str]) -> List[Dict[str, Any]]:
    """Récupère les offres pour plusieurs catégories Tech sur Remotive."""
    all_jobs = []
    for cat in categories:
        url = f"https://remotive.com/api/remote-jobs?category={cat}"
        try:
            logging.info(f"Scraping Remotive - Catégorie : '{cat}'...")
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            raw_jobs = response.json().get("jobs", [])
            
            for job in raw_jobs:
                all_jobs.append({
                    "id": f"remotive_{job.get('id')}",
                    "title": job.get("title"),
                    "company": job.get("company_name", "Inconnue"),
                    "category": job.get("category", cat),
                    "location": job.get("candidate_required_location", "Non spécifiée"),
                    "url": job.get("url"),
                    "published_at": job.get("publication_date"),
                    "description": job.get("description", "")
                })
        except Exception as e:
            logging.error(f"Erreur Remotive pour la catégorie '{cat}' : {e}")
            
    return all_jobs

def fetch_jobicy_tech_jobs(industries: List[str]) -> List[Dict[str, Any]]:
    """Récupère les offres pour plusieurs industries Tech sur Jobicy."""
    all_jobs = []
    for ind in industries:
        url = f"https://jobicy.com/api/v2/remote-jobs?industry={ind}&count=20"
        try:
            logging.info(f"Scraping Jobicy - Industrie : '{ind}'...")
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            raw_jobs = response.json().get("jobs", [])
            
            for job in raw_jobs:
                all_jobs.append({
                    "id": f"jobicy_{job.get('id')}",
                    "title": job.get("jobTitle"),
                    "company": job.get("companyName", "Inconnue"),
                    "category": ind,
                    "location": job.get("jobGeo", "Non spécifiée"),
                    "url": job.get("url"),
                    "published_at": job.get("pubDate"),
                    "description": job.get("jobDescription", "")
                })
        except Exception as e:
            logging.error(f"Erreur Jobicy pour l'industrie '{ind}' : {e}")
            
    return all_jobs

def run_broad_tech_collector(limit: int = 100) -> List[Dict[str, Any]]:
    """Collecte globale des offres Informatique (Dev, AI, Data, DevOps)."""
    logging.info("--- DÉMARRAGE DE LA COLLECTE INFORMATIQUE GLOBALE ---")
    
    # Catégories ciblées
    remotive_cats = ["software-dev", "data", "devops"]
    jobicy_inds = ["dev", "data-science", "supporting"]
    
    all_jobs = []
    all_jobs.extend(fetch_remotive_tech_jobs(remotive_cats))
    all_jobs.extend(fetch_jobicy_tech_jobs(jobicy_inds))
    
    # Déduplication par ID unique
    unique_jobs = list({job["id"]: job for job in all_jobs}.values())[:limit]
    
    logging.info(f"Collecte terminée : {len(unique_jobs)} offres IT brutes récupérées.")
    return unique_jobs

def save_raw_jobs(jobs: List[Dict[str, Any]], filepath: str = "data/raw_jobs.json") -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=4)
    logging.info(f"Fichier '{filepath}' enregistré avec succès.")

if __name__ == "__main__":
    jobs = run_broad_tech_collector(limit=100)
    save_raw_jobs(jobs)