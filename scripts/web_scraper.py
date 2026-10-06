import time
import json
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from typing import List, Dict, Any
from pathlib import Path
from common import BASE_DIR, DATA_DIR, canonicalize_url, deduplicate_jobs, stable_job_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/"
}

def scrape_freework_broad_tech(keywords: List[str], max_pages_per_keyword: int = 2) -> List[Dict[str, Any]]:
    """
    Scrape les offres d'emploi IT sur Free-Work pour une liste élargie de domaines Tech.
    """
    logging.info("--- DÉMARRAGE DU SCRAPING WEB HTML GLOBAL (TOUTE LA TECH) ---")
    scraped_jobs = []

    for kw in keywords:
        logging.info(f"Recherche sur le domaine / mot-clé : '{kw}'")
        
        for page in range(1, max_pages_per_keyword + 1):
            url = f"https://www.free-work.com/fr/tech-it/jobs?query={quote_plus(kw)}&page={page}"
            
            try:
                response = requests.get(url, headers=HEADERS, timeout=10)
                if response.status_code != 200:
                    logging.warning(f"Page {page} inaccessible pour '{kw}' (Code {response.status_code})")
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                
                # Sélection des cartes d'offres HTML
                job_cards = soup.find_all("div", class_=lambda c: c and "job-card" in c)
                if not job_cards:
                    job_cards = soup.select("a[href*='/tech-it/jobs/']")

                for index, card in enumerate(job_cards):
                    title_elem = card.find(["h2", "h3", "a"])
                    title = title_elem.get_text(strip=True) if title_elem else "Titre non spécifié"

                    link = card.get("href") if card.name == "a" else None
                    if not link and card.find("a"):
                        link = card.find("a").get("href")

                    # La recherche Free-Work mélange aussi articles et pages de villes.
                    if not link or title == "Titre non spécifié" or "/blog/" in link:
                        continue
                    
                    full_url = f"https://www.free-work.com{link}" if link and link.startswith("/") else link or ""
                    text_content = card.get_text(" ", strip=True)

                    # L'URL canonique produit un identifiant stable entre les exécutions.
                    full_url = canonicalize_url(full_url)
                    if not full_url:
                        continue
                    job_id = stable_job_id("freework", full_url, title, text_content)

                    scraped_jobs.append({
                        "id": job_id,
                        "title": title,
                        "company": "Free-Work Partner",
                        "category": kw,
                        "location": "France / Remote",
                        "url": full_url,
                        "published_at": "Récemment",
                        "description": text_content
                    })

                time.sleep(1.5)  # Pause éthique entre chaque page

            except Exception as e:
                logging.error(f"Erreur lors du scraping pour '{kw}' (page {page}) : {e}")

    logging.info(f"Scraping HTML terminé : {len(scraped_jobs)} offres Tech extraites du Web.")
    return scraped_jobs

def append_to_raw_jobs(new_jobs: List[Dict[str, Any]], filepath: Path = DATA_DIR / "raw_jobs.json") -> None:
    """Combine les nouvelles offres avec le fichier JSON brut existant en dédupliquant."""
    existing_jobs = []
    output_path = Path(filepath)
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            try:
                existing_jobs = json.load(f)
            except json.JSONDecodeError as e:
                logging.error("Le fichier '%s' contient un JSON invalide: %s", output_path, e)
                raise

    # Fusion et déduplication par ID unique
    unique_jobs = deduplicate_jobs([*existing_jobs, *new_jobs])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(unique_jobs, f, ensure_ascii=False, indent=4)

    logging.info("Fichier '%s' mis à jour : %s offres IT brutes uniques.", output_path, len(unique_jobs))

if __name__ == "__main__":
    # Liste de domaines couvrant tout le secteur Tech / IT
    tech_keywords = ["developpeur", "devops", "cloud", "intelligence artificielle", "cybersecurite"]
    
    html_jobs = scrape_freework_broad_tech(keywords=tech_keywords, max_pages_per_keyword=1)
    if html_jobs:
        append_to_raw_jobs(html_jobs)
