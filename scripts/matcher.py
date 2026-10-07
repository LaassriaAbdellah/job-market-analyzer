import json
from pathlib import Path

from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

from common import CONFIG_DIR, DATA_DIR


# ============================================================
# CHEMINS
# ============================================================

PARSED_JOBS_PATH = DATA_DIR / "parsed_jobs.json"
PROFILE_PATH = CONFIG_DIR / "my_profile.json"
OUTPUT_PATH = DATA_DIR / "matched_jobs.json"


# ============================================================
# CHARGEMENT JSON
# ============================================================

def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# CONSTRUCTION DU TEXTE DU PROFIL
# ============================================================

def build_profile_text(profile: dict) -> str:
    roles = ", ".join(profile.get("target_roles", []))
    skills = ", ".join(profile.get("skills", []))

    return (
        f"Target roles: {roles}. "
        f"Skills: {skills}."
    )


# ============================================================
# CONSTRUCTION DU TEXTE D'UNE OFFRE
# ============================================================

def build_job_text(job: dict) -> str:
    title = job.get("title", "")
    description = job.get("description", "")

    return (
        f"Job title: {title}. "
        f"Description: {description}"
    )


# ============================================================
# SCORE DE COMPÉTENCES
# ============================================================

def calculate_skill_score(job: dict, profile: dict) -> float:
    """
    Calcule la compatibilité des compétences entre
    le profil du candidat et l'offre.
    """

    user_skills = {
        skill.lower().strip()
        for skill in profile.get("skills", [])
    }

    extracted = job.get("extracted_skills", {})

    # Compétences réellement détectées dans l'offre
    # On ignore les concepts NLP génériques.
    job_skills = {
        skill.lower().strip()
        for category, skills in extracted.items()
        if category != "nlp_tech_concepts"
        for skill in skills
    }

    if not user_skills or not job_skills:
        return 0.0

    # Compétences communes
    matched_skills = user_skills.intersection(job_skills)

    if not matched_skills:
        return 0.0

    # 1. Quelle proportion des compétences de l'offre
    # le candidat possède ?
    job_coverage = len(matched_skills) / len(job_skills)

    # 2. Quelle proportion du profil est utilisée
    # dans cette offre ?
    profile_coverage = len(matched_skills) / len(user_skills)

    # On donne plus d'importance à la couverture de l'offre
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
    Compare le titre de l'offre aux métiers recherchés
    par le candidat.
    """

    title = job.get("title", "").strip()

    if not title:
        return 0.0

    title_embedding = model.encode(
        title,
        convert_to_tensor=True
    )

    similarities = cos_sim(
        title_embedding,
        role_embeddings
    )[0]

    best_similarity = float(similarities.max())

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

    jobs = load_json(PARSED_JOBS_PATH)
    profile = load_json(PROFILE_PATH)

    print(f"Offres chargées : {len(jobs)}")


    # --------------------------------------------------------
    # 2. Charger Sentence Transformer
    # --------------------------------------------------------

    print("Chargement du modèle Sentence Transformer...")

    model = SentenceTransformer(
        "sentence-transformers/all-MiniLM-L6-v2"
    )


    # --------------------------------------------------------
    # 3. Construire le texte représentant le profil
    # --------------------------------------------------------

    profile_text = build_profile_text(profile)


    # --------------------------------------------------------
    # 4. Construire les textes des offres
    # --------------------------------------------------------

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
    # 7. Similarité profil ↔ offres
    # --------------------------------------------------------

    semantic_similarities = cos_sim(
        profile_embedding,
        job_embeddings
    )[0]


    # --------------------------------------------------------
    # 8. Embeddings des métiers cibles
    #
    # On les calcule UNE SEULE FOIS.
    # --------------------------------------------------------

    target_roles = profile.get(
        "target_roles",
        []
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
    # 9. Calcul des scores
    # --------------------------------------------------------

    print("Calcul des scores hybrides...")

    for job, similarity in zip(
        jobs,
        semantic_similarities
    ):

        # -----------------------------
        # SCORE 1 : Sémantique
        # -----------------------------

        semantic_score = max(
            0.0,
            float(similarity) * 100
        )


        # -----------------------------
        # SCORE 2 : Compétences
        # -----------------------------

        skill_score = calculate_skill_score(
            job,
            profile
        )


        # -----------------------------
        # SCORE 3 : Métier
        # -----------------------------

        if role_embeddings is not None:

            role_score = calculate_role_score(
                job,
                role_embeddings,
                model
            )

        else:
            role_score = 0.0


        # -----------------------------
        # SCORE FINAL
        # -----------------------------
        #
        # 50 % similarité sémantique
        # 30 % métier
        # 20 % compétences
        #

        final_score = (
            semantic_score * 0.50
            + role_score * 0.30
            + skill_score * 0.20
        )


        # Sauvegarde des différents scores

        job["semantic_score"] = round(
            semantic_score,
            2
        )

        job["role_score"] = round(
            role_score,
            2
        )

        job["skill_score"] = round(
            skill_score,
            2
        )

        job["final_score"] = round(
            final_score,
            2
        )


    # --------------------------------------------------------
    # 10. Trier selon le score FINAL
    # --------------------------------------------------------

    jobs.sort(
        key=lambda job: job.get(
            "final_score",
            0
        ),
        reverse=True
    )


    # --------------------------------------------------------
    # 11. Sauvegarder les résultats
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
    # 12. Affichage du TOP 10
    # --------------------------------------------------------

    print(
        f"\nMatching terminé : "
        f"{len(jobs)} offres."
    )

    print(
        f"Résultats : {OUTPUT_PATH}"
    )

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