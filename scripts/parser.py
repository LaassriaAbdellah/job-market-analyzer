
import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Set

import psycopg2
import spacy
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from psycopg2.extras import execute_batch

from common import BASE_DIR, CONFIG_DIR, DATA_DIR


# ============================================================
# CONFIGURATION
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

load_dotenv(BASE_DIR / ".env")


# ============================================================
# POSTGRESQL : CONNEXION ET LECTURE
# ============================================================

def get_connection():
    """Crée une connexion à PostgreSQL."""
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432")
    )


def load_jobs_from_db() -> List[Dict[str, Any]]:
    """Récupère les offres normalisées depuis PostgreSQL."""

    query = """
        SELECT
            id,
            title,
            company,
            location,
            description,
            url,
            source,
            published_at,
            employment_type,
            remote,
            skills
        FROM jobs
        ORDER BY published_at DESC NULLS LAST;
    """

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query)

            columns = [
                column[0]
                for column in cursor.description
            ]

            rows = cursor.fetchall()

    jobs = [
        dict(zip(columns, row))
        for row in rows
    ]

    logging.info(
        "%s offres chargées depuis PostgreSQL.",
        len(jobs)
    )

    return jobs


# ============================================================
# POSTGRESQL : ENREGISTREMENT DES ANALYSES
# ============================================================

def save_job_analyses(
    parsed_jobs: List[Dict[str, Any]]
) -> None:
    """
    Enregistre les analyses NLP dans job_analysis.

    INSERT pour une nouvelle analyse.
    UPDATE pour une analyse existante.
    """

    if not parsed_jobs:
        logging.info("Aucune analyse à enregistrer.")
        return

    query = """
        INSERT INTO job_analysis (
            job_id,
            cleaned_description,
            extracted_skills,
            total_skills_count
        )
        VALUES (%s, %s, %s::jsonb, %s)

        ON CONFLICT (job_id)
        DO UPDATE SET
            cleaned_description = EXCLUDED.cleaned_description,
            extracted_skills = EXCLUDED.extracted_skills,
            total_skills_count = EXCLUDED.total_skills_count,
            analyzed_at = NOW();
    """

    values = []

    for job in parsed_jobs:
        values.append((
            job["id"],
            job.get("description", ""),
            json.dumps(
                job.get("extracted_skills", {}),
                ensure_ascii=False
            ),
            job.get("total_skills_count", 0)
        ))

    with get_connection() as conn:
        with conn.cursor() as cursor:
            execute_batch(
                cursor,
                query,
                values,
                page_size=100
            )

    logging.info(
        "%s analyses enregistrées/mises à jour "
        "dans PostgreSQL.",
        len(values)
    )


# ============================================================
# CHARGEMENT DES MODÈLES SPACY
# ============================================================

def load_spacy_model(model_name: str):
    """Charge un modèle spaCy sans bloquer l'autre."""

    try:
        return spacy.load(model_name)
    except OSError:
        logging.warning(
            "Modèle spaCy absent : %s",
            model_name
        )
        return None


nlp_en = load_spacy_model("en_core_web_sm")
nlp_fr = load_spacy_model("fr_core_news_sm")


# ============================================================
# MOTS-CLÉS TECHNIQUES
# ============================================================

TECH_TRIGGER_WORDS = {
    "data", "engineer", "engineering", "developer",
    "development", "cloud", "architecture", "pipeline",
    "system", "infrastructure", "api", "automation",
    "testing", "code", "security", "design", "agile",
    "analytics", "learning", "model", "database",
    "service", "software", "network", "devops", "ci/cd",
    "projet", "gestion", "développement",
    "intégration", "sécurité", "réseau"
}


# ============================================================
# UTILITAIRES
# ============================================================

def clean_html(raw_html: str) -> str:
    """Supprime les balises HTML et nettoie les espaces."""

    if not raw_html:
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=" ")

    return re.sub(r"\s+", " ", text).strip()


def load_json(filepath: Path) -> Any:
    """Charge un fichier JSON."""

    with Path(filepath).open("r", encoding="utf-8") as f:
        return json.load(f)


def project_path(path: Path) -> Path:
    """Résout un chemin depuis la racine du projet."""

    candidate = Path(path)

    if candidate.is_absolute():
        return candidate

    return BASE_DIR / candidate


# ============================================================
# NIVEAU 1 : EXTRACTION PAR DICTIONNAIRE
# ============================================================

def extract_known_skills(
    text: str,
    keywords_dict: Dict[str, List[str]]
) -> Dict[str, List[str]]:
    """
    Recherche les compétences connues dans le texte
    à partir du dictionnaire keywords.json.
    """

    found_skills = {}
    text_lower = text.lower()

    for category, skills_list in keywords_dict.items():

        found_in_cat = []

        for skill in skills_list:

            pattern = (
                r"\b"
                + re.escape(skill.lower())
                + r"\b"
            )

            if re.search(pattern, text_lower):
                found_in_cat.append(skill)

        if found_in_cat:
            found_skills[category] = found_in_cat

    return found_skills


# ============================================================
# NIVEAU 2 : EXTRACTION NLP SPACY
# ============================================================

def extract_nlp_concepts(
    clean_text: str,
    known_skills_flat: Set[str],
    lang: str = "en"
) -> List[str]:
    """
    Extrait des concepts techniques pertinents
    à l'aide de spaCy.
    """

    nlp_model = nlp_fr if lang == "fr" else nlp_en

    if nlp_model is None:
        return []

    doc = nlp_model(clean_text[:4000])

    valid_concepts = set()

    if lang == "en" and doc.has_annotation("DEP"):

        for chunk in doc.noun_chunks:

            text_chunk = chunk.text.lower().strip()
            words = text_chunk.split()

            if 1 < len(words) <= 3 and not chunk.root.is_stop:

                if any(
                    word in TECH_TRIGGER_WORDS
                    for word in words
                ):

                    if (
                        text_chunk not in known_skills_flat
                        and re.match(
                            r"^[a-z\s-]+$",
                            text_chunk
                        )
                    ):
                        valid_concepts.add(text_chunk)

    return sorted(valid_concepts)[:6]


# ============================================================
# SCORE HISTORIQUE (COMPATIBILITÉ)
# ============================================================

def calculate_score(
    extracted_skills: Dict[str, List[str]],
    user_skills: List[str]
) -> float:
    """
    Ancien score basé sur les compétences.

    Conservé pour la compatibilité avec matcher.py.
    Le score hybride final est calculé par matcher.py.
    """

    all_job_skills = [
        skill
        for sublist in extracted_skills.values()
        for skill in sublist
    ]

    if not all_job_skills:
        return 0.0

    user_skills_set = {
        skill.lower()
        for skill in user_skills
    }

    matched_skills = [
        skill
        for skill in all_job_skills
        if skill.lower() in user_skills_set
    ]

    return round(
        (
            len(matched_skills)
            / len(all_job_skills)
        ) * 100,
        2
    )


# ============================================================
# PIPELINE DE PARSING
# ============================================================

def run_filtered_parser(
    keywords_path: Path = CONFIG_DIR / "keywords.json",
    profile_path: Path = CONFIG_DIR / "my_profile.json",
    output_path: Path = DATA_DIR / "parsed_jobs.json"
):
    """
    1. Lit les offres depuis PostgreSQL.
    2. Nettoie les descriptions.
    3. Extrait les compétences et concepts NLP.
    4. Enregistre les analyses dans job_analysis.
    5. Génère temporairement parsed_jobs.json.
    """

    logging.info(
        "--- DÉMARRAGE DU PARSER "
        "(POSTGRESQL + NLP) ---"
    )

    # 1. Chargement des données

    raw_jobs = load_jobs_from_db()

    keywords = load_json(
        project_path(keywords_path)
    )

    profile = load_json(
        project_path(profile_path)
    )

    user_skills = profile.get("skills", [])

    parsed_jobs = []

    # 2. Parsing des offres

    for job in raw_jobs:

        clean_desc = clean_html(
            job.get("description", "")
        )

        full_clean_text = (
            f"{job.get('title', '')} "
            f"{clean_desc}"
        )

        is_french = (
            job.get("source") == "free-work"
            or "freework" in str(job.get("id", "")).lower()
        )

        lang = "fr" if is_french else "en"

        # Niveau 1 : dictionnaire

        extracted_skills = extract_known_skills(
            full_clean_text,
            keywords
        )

        known_flat = {
            skill.lower()
            for sublist in extracted_skills.values()
            for skill in sublist
        }

        # Niveau 2 : NLP

        nlp_concepts = extract_nlp_concepts(
            full_clean_text,
            known_flat,
            lang=lang
        )

        if nlp_concepts:
            extracted_skills[
                "nlp_tech_concepts"
            ] = nlp_concepts

        # Score historique

        score = calculate_score(
            extracted_skills,
            user_skills
        )

        # Résultat de l'analyse

        published_at = job.get("published_at")

        if hasattr(published_at, "isoformat"):
            published_at = published_at.isoformat()

        parsed_job = {
            "id": job.get("id"),
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "description": clean_desc,
            "url": job.get("url"),
            "published_at": published_at,
            "source": job.get("source"),
            "extracted_skills": extracted_skills,
            "total_skills_count": sum(
                len(values)
                for values in extracted_skills.values()
            ),
            "matching_score": score
        }

        parsed_jobs.append(parsed_job)

    # 3. Enregistrement dans PostgreSQL

    save_job_analyses(parsed_jobs)

    # 4. Export JSON temporaire pour matcher.py

    resolved_output = project_path(output_path)

    resolved_output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with resolved_output.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            parsed_jobs,
            f,
            ensure_ascii=False,
            indent=4
        )

    logging.info(
        "Parsing terminé : %s offres analysées.",
        len(parsed_jobs)
    )

    logging.info(
        "Résultats PostgreSQL : table job_analysis"
    )

    logging.info(
        "Export JSON temporaire : %s",
        resolved_output
    )


if __name__ == "__main__":
    run_filtered_parser()
