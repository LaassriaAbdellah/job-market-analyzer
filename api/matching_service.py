import re
import unicodedata

from psycopg2.extras import execute_batch
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

from api.database import get_connection
from scripts.matcher import (
    MODEL_NAME,
    build_profile_text,
    build_job_text,
    calculate_skill_score,
)

_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.casefold().strip()


def contains_pattern(text, pattern):
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


SENIOR_PATTERN = r"\b(senior|sr\.?|staff|principal|lead|head of|director|manager|expert)\b"
INTERN_PATTERN = r"\b(intern(?:ship)?|stage|stagiaire|pfe|alternan\w*|apprenti\w*)\b"
JUNIOR_PATTERN = r"\b(junior|jr\.?|entry.level|graduate|debutant)\b"
MID_PATTERN = r"\b(mid.level|intermediate|intermediaire|confirmed|confirme)\b"

# Equivalences prudentes pour les localisations les plus fréquentes.
MOROCCO_TERMS = (
    "morocco", "maroc", "rabat", "casablanca", "fes", "fez",
    "marrakech", "tanger", "tangier", "agadir", "kenitra",
    "meknes", "oujda", "tetouan", "sale", "el jadida"
)


def experience_adjustment(title, desired_level):
    if desired_level == "any":
        return 0.0
    title = normalize(title)
    if not title:
        return 0.0
    is_senior = contains_pattern(title, SENIOR_PATTERN)
    is_intern = contains_pattern(title, INTERN_PATTERN)
    is_junior = contains_pattern(title, JUNIOR_PATTERN)
    is_mid = contains_pattern(title, MID_PATTERN)

    if desired_level == "intern":
        if is_senior:
            return -30.0
        if is_intern:
            return 12.0
        if is_junior:
            return 3.0
        if is_mid:
            return -12.0
    elif desired_level == "junior":
        if is_senior:
            return -22.0
        if is_junior:
            return 10.0
        if is_intern:
            return -4.0
        if is_mid:
            return -8.0
    elif desired_level == "mid":
        if is_senior:
            return -8.0
        if is_mid:
            return 10.0
        if is_intern:
            return -15.0
    elif desired_level == "senior":
        if is_senior:
            return 10.0
        if is_intern:
            return -20.0
        if is_junior:
            return -10.0
    return 0.0


def contract_adjustment(title, employment_type, desired_contract):
    if desired_contract == "any":
        return 0.0
    title = normalize(title)
    contract = normalize(employment_type)
    if desired_contract == "internship":
        if contains_pattern(title, INTERN_PATTERN) or contains_pattern(contract, INTERN_PATTERN):
            return 8.0
        if contains_pattern(contract, r"\b(full.time|permanent|cdi|contract|freelance)\b"):
            return -12.0
    elif desired_contract == "full_time":
        if contains_pattern(contract, r"\b(full.time|permanent|cdi)\b"):
            return 8.0
        if contains_pattern(contract, INTERN_PATTERN):
            return -10.0
    elif desired_contract == "part_time":
        if contains_pattern(contract, r"\b(part.time|temps partiel)\b"):
            return 8.0
    elif desired_contract == "contract":
        if contains_pattern(contract, r"\b(contract|freelance|contractor|cdd)\b"):
            return 8.0
    return 0.0


def location_adjustment(job_location, preferred_location):
    preferred = normalize(preferred_location)
    actual = normalize(job_location)
    if not preferred or not actual:
        return 0.0

    if preferred in ("morocco", "maroc"):
        if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", actual) for term in MOROCCO_TERMS):
            return 12.0
        # "Remote" ne signifie pas forcément accessible depuis le Maroc.
        if contains_pattern(actual, r"\b(remote|worldwide|global|anywhere)\b"):
            return 0.0
        return -12.0

    if preferred in actual:
        return 12.0
    if contains_pattern(actual, r"\b(remote|worldwide|global|anywhere)\b"):
        return 0.0
    # Pour une ville, l'absence de correspondance n'est pas une preuve d'incompatibilité.
    return 0.0


def calculate_adjusted_score(job, profile, final_score):
    adjustment = (
        experience_adjustment(job.get("title"), profile.get("experience_level") or "any")
        + contract_adjustment(
            job.get("title"), job.get("employment_type"),
            profile.get("contract_type") or "any"
        )
        + location_adjustment(job.get("location"), profile.get("preferred_location"))
    )
    return round(max(0.0, min(100.0, final_score + adjustment)), 2)


def run_profile_matching(profile_id: int) -> int:
    """Calcule le score hybride et le score ajusté aux préférences."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, skills, target_roles,
                       experience_level, contract_type, preferred_location
                FROM profiles
                WHERE id = %s;
                """,
                (profile_id,)
            )
            profile = cursor.fetchone()
            if profile is None:
                raise ValueError("Profil introuvable")

            cursor.execute(
                """
                SELECT j.id, j.title, j.location, j.employment_type,
                       a.cleaned_description AS description,
                       a.extracted_skills
                FROM jobs j
                JOIN job_analysis a ON j.id = a.job_id;
                """
            )
            jobs = cursor.fetchall()

    if not jobs:
        return 0

    model = get_model()
    profile_text = build_profile_text(profile)
    job_texts = [build_job_text(job) for job in jobs]

    profile_embedding = model.encode(profile_text, convert_to_tensor=True)
    job_embeddings = model.encode(
        job_texts, convert_to_tensor=True, show_progress_bar=False
    )
    semantic_similarities = cos_sim(profile_embedding, job_embeddings)[0]

    target_roles = profile.get("target_roles", [])
    role_embeddings = (
        model.encode(target_roles, convert_to_tensor=True)
        if target_roles else None
    )
    title_embeddings = (
        model.encode(
            [job.get("title") or "" for job in jobs],
            convert_to_tensor=True, show_progress_bar=False
        )
        if role_embeddings is not None else None
    )

    values = []
    for i, job in enumerate(jobs):
        semantic_score = max(0.0, float(semantic_similarities[i]) * 100)
        skill_score = calculate_skill_score(job, profile)
        if role_embeddings is not None and (job.get("title") or "").strip():
            role_score = max(
                0.0,
                float(cos_sim(title_embeddings[i].unsqueeze(0), role_embeddings).max()) * 100
            )
        else:
            role_score = 0.0

        final_score = (
            semantic_score * 0.50
            + role_score * 0.30
            + skill_score * 0.20
        )
        adjusted_score = calculate_adjusted_score(job, profile, final_score)
        values.append((
            profile_id, job["id"], round(semantic_score, 2),
            round(role_score, 2), round(skill_score, 2),
            round(final_score, 2), adjusted_score
        ))

    query = """
        INSERT INTO job_matches (
            profile_id, job_id, semantic_score, role_score,
            skill_score, final_score, adjusted_score
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (profile_id, job_id)
        DO UPDATE SET
            semantic_score = EXCLUDED.semantic_score,
            role_score = EXCLUDED.role_score,
            skill_score = EXCLUDED.skill_score,
            final_score = EXCLUDED.final_score,
            adjusted_score = EXCLUDED.adjusted_score,
            matched_at = NOW();
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            execute_batch(cursor, query, values, page_size=100)
    return len(values)
