import re
import json
import logging
import spacy
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Set
from pathlib import Path
from common import BASE_DIR, CONFIG_DIR, DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Chargement des modèles spaCy
try:
    nlp_en = spacy.load("en_core_web_sm")
    nlp_fr = spacy.load("fr_core_news_sm")
except OSError:
    logging.warning("Exécutez : python -m spacy download en_core_web_sm et fr_core_news_sm")
    nlp_en, nlp_fr = None, None

# Mots-clés déclencheurs pour valider qu'un concept NLP est pertinent pour la Tech/Data/Dev
TECH_TRIGGER_WORDS = {
    "data", "engineer", "engineering", "developer", "development", "cloud", 
    "architecture", "pipeline", "system", "infrastructure", "api", "automation", 
    "testing", "code", "security", "design", "agile", "analytics", "learning", 
    "model", "database", "service", "software", "network", "devops", "ci/cd",
    "projet", "gestion", "développement", "intégration", "sécurité", "réseau"
}

def clean_html(raw_html: str) -> str:
    """Supprime les balises HTML et nettoie les espaces."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=" ")
    return re.sub(r'\s+', ' ', text).strip()

def load_json(filepath: str) -> Any:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

# --- NIVEAU 1 : REGEX PAR DICTIONNAIRE (100% Précis) ---
def extract_known_skills(text: str, keywords_dict: Dict[str, List[str]]) -> Dict[str, List[str]]:
    found_skills = {}
    text_lower = text.lower()
    
    for category, skills_list in keywords_dict.items():
        found_in_cat = []
        for skill in skills_list:
            pattern = r'\b' + re.escape(skill.lower()) + r'\b'
            if re.search(pattern, text_lower):
                found_in_cat.append(skill)
        if found_in_cat:
            found_skills[category] = found_in_cat
            
    return found_skills

# --- NIVEAU 2 : NLP SPACY FILTRÉ (Strictement Tech) ---
def extract_nlp_concepts(clean_text: str, known_skills_flat: Set[str], lang: str = "en") -> List[str]:
    nlp_model = nlp_fr if lang == "fr" else nlp_en
    if not nlp_model:
        return []

    doc = nlp_model(clean_text[:4000])
    valid_concepts = set()

    if lang == "en" and doc.has_annotation("DEP"):
        for chunk in doc.noun_chunks:
            text_chunk = chunk.text.lower().strip()
            words = text_chunk.split()
            
            # Filtres stricts :
            # 1. Longueur entre 2 et 3 mots
            # 2. Pas de stopwords
            # 3. Contient AU MOINS UN mot technique déclencheur (TECH_TRIGGER_WORDS)
            # 4. Ne figure pas déjà dans le dictionnaire Niveau 1
            if 1 < len(words) <= 3 and not chunk.root.is_stop:
                if any(w in TECH_TRIGGER_WORDS for w in words):
                    if text_chunk not in known_skills_flat and re.match(r'^[a-z\s-]+$', text_chunk):
                        valid_concepts.add(text_chunk)

    return list(valid_concepts)[:6]  # Max 6 concepts pertinents par offre

def calculate_score(extracted_skills: Dict[str, List[str]], user_skills: List[str]) -> float:
    all_job_skills = [skill for sublist in extracted_skills.values() for skill in sublist]
    if not all_job_skills:
        return 0.0
    user_skills_set = set(s.lower() for s in user_skills)
    matched_skills = [s for s in all_job_skills if s.lower() in user_skills_set]
    return round((len(matched_skills) / len(all_job_skills)) * 100, 2)

def run_filtered_parser(
    raw_path: Path = DATA_DIR / "raw_jobs.json",
    keywords_path: Path = CONFIG_DIR / "keywords.json",
    profile_path: Path = CONFIG_DIR / "my_profile.json",
    output_path: Path = DATA_DIR / "parsed_jobs.json"
):
    logging.info("--- DÉMARRAGE DU PARSER FILTRÉ (Nettoyage + Filtre Sémantique Tech) ---")
    
    def project_path(path: Any) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else BASE_DIR / candidate

    raw_jobs = load_json(str(project_path(raw_path)))
    keywords = load_json(str(project_path(keywords_path)))
    profile = load_json(str(project_path(profile_path)))
    user_skills = profile.get("skills", [])
    
    parsed_jobs = []
    
    for job in raw_jobs:
        clean_desc = clean_html(job.get("description", ""))
        full_clean_text = f"{job.get('title', '')} {clean_desc}"
        
        is_french = "freework" in job.get("id", "").lower()
        lang = "fr" if is_french else "en"
        
        # 1. Niveau 1 : Dictionnaire
        extracted_skills = extract_known_skills(full_clean_text, keywords)
        known_flat = set(s.lower() for sublist in extracted_skills.values() for s in sublist)
        
        # 2. Niveau 2 : NLP spaCy Filtré
        nlp_concepts = extract_nlp_concepts(full_clean_text, known_flat, lang=lang)
        if nlp_concepts:
            extracted_skills["nlp_tech_concepts"] = nlp_concepts
            
        score = calculate_score(extracted_skills, user_skills)
        
        parsed_job = {
            "id": job.get("id"),
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "url": job.get("url"),
            "published_at": job.get("published_at"),
            "extracted_skills": extracted_skills,
            "total_skills_count": sum(len(v) for v in extracted_skills.values()),
            "matching_score": score
        }
        parsed_jobs.append(parsed_job)
        
    resolved_output = project_path(output_path)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    with resolved_output.open("w", encoding="utf-8") as f:
        json.dump(parsed_jobs, f, ensure_ascii=False, indent=4)
        
    logging.info("Parsing filtré réussi : %s offres enregistrées dans '%s'.", len(parsed_jobs), resolved_output)

if __name__ == "__main__":
    run_filtered_parser()
