
import os
import json
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

from scripts.common import BASE_DIR, CONFIG_DIR, DATA_DIR

from scripts.skill_normalizer import canonicalize_skills
# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv(BASE_DIR / ".env")

PROFILE_PATH = CONFIG_DIR / "my_profile.json"
OUTPUT_PATH = DATA_DIR / "matched_jobs.json"

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Profil local utilisé pendant le développement.
PROFILE_NAME = "Mon profil"


# ============================================================
# CONNEXION POSTGRESQL
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


# ============================================================
# CHARGEMENT DES OFFRES DEPUIS POSTGRESQL
# ============================================================

def load_jobs_from_db() -> list[dict]:
    """
    Charge les offres et leurs analyses NLP
    depuis les tables jobs et job_analysis.
    """

    query = """
        SELECT
            j.id,
            j.title,
            j.company,
            j.location,
            j.url,
            j.source,
            j.published_at,
            a.cleaned_description AS description,
            a.extracted_skills,
            a.total_skills_count

        FROM jobs j

        INNER JOIN job_analysis a
            ON j.id = a.job_id

        ORDER BY j.published_at DESC NULLS LAST;
    """

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query)

            columns = [
                column[0]
                for column in cursor.description
            ]

            rows = cursor.fetchall()

    jobs = []

    for row in rows:
        job = dict(zip(columns, row))

        published_at = job.get("published_at")

        if hasattr(published_at, "isoformat"):
            job["published_at"] = published_at.isoformat()

        jobs.append(job)

    return jobs


# ============================================================
# CHARGEMENT DU PROFIL JSON
# ============================================================

def load_json(path: Path) -> dict:
    """Charge un fichier JSON."""

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# ENREGISTREMENT DU PROFIL
# ============================================================

def save_profile(profile: dict) -> int:
    """
    Crée ou met à jour le profil candidat.

    Pendant le développement, le nom "Mon profil"
    permet de retrouver le même profil.

    Retourne son identifiant PostgreSQL.
    """

    skills_json = json.dumps(
        profile.get("skills", []),
        ensure_ascii=False
    )

    roles_json = json.dumps(
        profile.get("target_roles", []),
        ensure_ascii=False
    )

    with get_connection() as conn:
        with conn.cursor() as cursor:

            # Rechercher un profil existant
            cursor.execute(
                """
                SELECT id
                FROM profiles
                WHERE name = %s
                ORDER BY id
                LIMIT 1;
                """,
                (PROFILE_NAME,)
            )

            result = cursor.fetchone()

            if result:

                profile_id = result[0]

                cursor.execute(
                    """
                    UPDATE profiles
                    SET
                        skills = %s::jsonb,
                        target_roles = %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (
                        skills_json,
                        roles_json,
                        profile_id
                    )
                )

                print(
                    f"Profil mis à jour : ID = {profile_id}"
                )

            else:

                cursor.execute(
                    """
                    INSERT INTO profiles (
                        name,
                        skills,
                        target_roles
                    )
                    VALUES (
                        %s,
                        %s::jsonb,
                        %s::jsonb
                    )
                    RETURNING id;
                    """,
                    (
                        PROFILE_NAME,
                        skills_json,
                        roles_json
                    )
                )

                profile_id = cursor.fetchone()[0]

                print(
                    f"Nouveau profil créé : ID = {profile_id}"
                )

    return profile_id


# ============================================================
# ENREGISTREMENT DES RÉSULTATS DU MATCHING
# ============================================================

def save_matches(
    profile_id: int,
    jobs: list[dict]
) -> None:
    """
    Enregistre les scores dans job_matches.

    Si un matching existe déjà pour ce profil
    et cette offre, ses scores sont mis à jour.
    """

    if not jobs:
        print("Aucun matching à enregistrer.")
        return

    query = """
        INSERT INTO job_matches (
            profile_id,
            job_id,
            semantic_score,
            role_score,
            skill_score,
            final_score
        )
        VALUES (%s, %s, %s, %s, %s, %s)

        ON CONFLICT (profile_id, job_id)
        DO UPDATE SET
            semantic_score = EXCLUDED.semantic_score,
            role_score = EXCLUDED.role_score,
            skill_score = EXCLUDED.skill_score,
            final_score = EXCLUDED.final_score,
            matched_at = NOW();
    """

    values = [
        (
            profile_id,
            job["id"],
            job["semantic_score"],
            job["role_score"],
            job["skill_score"],
            job["final_score"]
        )
        for job in jobs
    ]

    with get_connection() as conn:
        with conn.cursor() as cursor:

            execute_batch(
                cursor,
                query,
                values,
                page_size=100
            )

    print(
        f"{len(values)} résultats de matching "
        "enregistrés dans PostgreSQL."
    )


# ============================================================
# CONSTRUCTION DU TEXTE DU PROFIL
# ============================================================

def build_profile_text(profile: dict) -> str:
    """Construit le texte représentant le candidat."""

    roles = ", ".join(
        profile.get("target_roles", [])
    )

    skills = ", ".join(
        profile.get("skills", [])
    )

    return (
        f"Target roles: {roles}. "
        f"Skills: {skills}."
    )


# ============================================================
# CONSTRUCTION DU TEXTE D'UNE OFFRE
# ============================================================

def build_job_text(job: dict) -> str:
    """Construit le texte représentant une offre."""

    title = job.get("title") or ""
    description = job.get("description") or ""

    return (
        f"Job title: {title}. "
        f"Description: {description}"
    )


# ============================================================
# SCORE DE COMPÉTENCES
# ============================================================



def calculate_skill_score(
    job: dict,
    profile: dict
) -> float:
    """
    Calcule la compatibilité des compétences.

    Les synonymes sont normalisés avant comparaison.

    Pondération :
    - 70 % : couverture des compétences de l'offre
    - 30 % : couverture des compétences du profil
    """

    # 1. Compétences du candidat
    user_skills = canonicalize_skills(
        profile.get("skills", [])
    )

    # 2. Compétences extraites de l'offre
    extracted = job.get("extracted_skills") or {}

    raw_job_skills = []

    for category, skills in extracted.items():

        if category == "nlp_tech_concepts":
            continue

        if isinstance(skills, list):
            raw_job_skills.extend(skills)

    job_skills = canonicalize_skills(
        raw_job_skills
    )

    # 3. Vérifier les listes
    if not user_skills or not job_skills:
        return 0.0

    # 4. Compétences communes
    matched_skills = user_skills.intersection(
        job_skills
    )

    # 5. Couverture des compétences
    job_coverage = (
        len(matched_skills) / len(job_skills)
    )

    profile_coverage = (
        len(matched_skills) / len(user_skills)
    )

    # 6. Score final des compétences
    score = (
        job_coverage * 0.70
        + profile_coverage * 0.30
    ) * 100

    return round(score, 2)




# ============================================================
# SCORE DU MÉTIER
# ============================================================

def calculate_role_score(
    job: dict,
    role_embeddings,
    model
) -> float:
    """
    Compare le titre de l'offre avec les métiers
    recherchés par le candidat.
    """

    title = (job.get("title") or "").strip()

    if not title or role_embeddings is None:
        return 0.0

    title_embedding = model.encode(
        title,
        convert_to_tensor=True
    )

    similarities = cos_sim(
        title_embedding,
        role_embeddings
    )[0]

    best_similarity = float(
        similarities.max()
    )

    return round(
        max(0.0, best_similarity * 100),
        2
    )


# ============================================================
# MATCHING PRINCIPAL
# ============================================================

def run_matcher():

    print("\n===== DÉMARRAGE DU MATCHING =====\n")

    # --------------------------------------------------------
    # 1. Charger les offres et le profil
    # --------------------------------------------------------

    print("Chargement des offres depuis PostgreSQL...")

    jobs = load_jobs_from_db()

    profile = load_json(PROFILE_PATH)

    print(f"Offres chargées : {len(jobs)}")

    if not jobs:
        print(
            "Aucune offre analysée trouvée. "
            "Exécute d'abord python scripts\\parser.py."
        )
        return

    # --------------------------------------------------------
    # 2. Enregistrer ou mettre à jour le profil
    # --------------------------------------------------------

    profile_id = save_profile(profile)

    # --------------------------------------------------------
    # 3. Charger Sentence Transformer
    # --------------------------------------------------------

    print("Chargement du modèle Sentence Transformer...")

    model = SentenceTransformer(MODEL_NAME)

    # --------------------------------------------------------
    # 4. Construire les textes
    # --------------------------------------------------------

    profile_text = build_profile_text(profile)

    job_texts = [
        build_job_text(job)
        for job in jobs
    ]

    # --------------------------------------------------------
    # 5. Embedding du profil
    # --------------------------------------------------------

    print("Création de l'embedding du profil...")

    profile_embedding = model.encode(
        profile_text,
        convert_to_tensor=True
    )

    # --------------------------------------------------------
    # 6. Embeddings des offres
    # --------------------------------------------------------

    print(
        f"Création des embeddings pour "
        f"{len(jobs)} offres..."
    )

    job_embeddings = model.encode(
        job_texts,
        convert_to_tensor=True,
        show_progress_bar=True
    )

    # --------------------------------------------------------
    # 7. Similarité sémantique
    # --------------------------------------------------------

    semantic_similarities = cos_sim(
        profile_embedding,
        job_embeddings
    )[0]

    # --------------------------------------------------------
    # 8. Embeddings des métiers cibles
    # --------------------------------------------------------

    target_roles = profile.get(
        "target_roles", []
    )

    if target_roles:

        print(
            f"Création des embeddings pour "
            f"{len(target_roles)} métiers cibles..."
        )

        role_embeddings = model.encode(
            target_roles,
            convert_to_tensor=True
        )

    else:
        role_embeddings = None

    # --------------------------------------------------------
    # 9. Calcul des scores hybrides
    # --------------------------------------------------------

    print("Calcul des scores hybrides...")

    for job, similarity in zip(
        jobs,
        semantic_similarities
    ):

        # SCORE 1 : Sémantique

        semantic_score = max(
            0.0,
            float(similarity) * 100
        )

        # SCORE 2 : Compétences

        skill_score = calculate_skill_score(
            job,
            profile
        )

        # SCORE 3 : Métier

        if role_embeddings is not None:

            role_score = calculate_role_score(
                job,
                role_embeddings,
                model
            )

        else:
            role_score = 0.0

        # SCORE FINAL
        # 50 % sémantique
        # 30 % métier
        # 20 % compétences

        final_score = (
            semantic_score * 0.50
            + role_score * 0.30
            + skill_score * 0.20
        )

        job["semantic_score"] = round(
            semantic_score, 2
        )

        job["role_score"] = round(
            role_score, 2
        )

        job["skill_score"] = round(
            skill_score, 2
        )

        job["final_score"] = round(
            final_score, 2
        )

    # --------------------------------------------------------
    # 10. Trier les offres par score final
    # --------------------------------------------------------

    jobs.sort(
        key=lambda job: job["final_score"],
        reverse=True
    )

    # --------------------------------------------------------
    # 11. Enregistrer les scores dans PostgreSQL
    # --------------------------------------------------------

    print("Enregistrement des scores dans PostgreSQL...")

    save_matches(
        profile_id,
        jobs
    )

    # --------------------------------------------------------
    # 12. Export JSON temporaire
    # --------------------------------------------------------

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with OUTPUT_PATH.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            jobs,
            f,
            ensure_ascii=False,
            indent=4
        )

    # --------------------------------------------------------
    # 13. Affichage du TOP 10
    # --------------------------------------------------------

    print(
        f"\nMatching terminé : {len(jobs)} offres."
    )

    print(f"Profil ID : {profile_id}")

    print(f"Export JSON : {OUTPUT_PATH}")

    print(
        "\n===== TOP 10 MATCHING HYBRIDE =====\n"
    )

    for i, job in enumerate(
        jobs[:10],
        start=1
    ):

        print(
            f"{i}. {job.get('title', '')}"
        )

        print(
            f"   Entreprise : "
            f"{job.get('company', '')}"
        )

        print(
            f"   Sémantique : "
            f"{job['semantic_score']} %"
        )

        print(
            f"   Métier     : "
            f"{job['role_score']} %"
        )

        print(
            f"   Skills     : "
            f"{job['skill_score']} %"
        )

        print(
            f"   FINAL      : "
            f"{job['final_score']} %"
        )

        print("-" * 70)


# ============================================================
# EXÉCUTION
# ============================================================

if __name__ == "__main__":
    run_matcher()
