
from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    UploadFile,
    File
)

from psycopg2.extras import Json, RealDictCursor

from api.database import get_connection
from api.schemas import ProfileCreate, ProfileUpdate
from api.matching_service import run_profile_matching
from api.cv_service import extract_cv_text, extract_cv_skills

from api.favorites import router as favorites_router

from api.automatic_email import router as automatic_email_router
from api.email_notifications import router as email_router

from api.analytics import router as analytics_router
# ============================================================
# CONFIGURATION FASTAPI
# ============================================================

app = FastAPI(
    title="Job Market Analyzer API",
    description=(
        "API REST pour la gestion des profils candidats, "
        "la consultation des offres d'emploi et le "
        "matching intelligent basé sur le NLP."
    ),
    version="1.1.0"
)

app.include_router(favorites_router)
app.include_router(automatic_email_router)
app.include_router(email_router)
app.include_router(analytics_router)

# ============================================================
# 1. HEALTH CHECK
# ============================================================

@app.get("/health", tags=["System"])
def health_check():

    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.fetchone()

        return {
            "status": "ok",
            "database": "connected"
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Connexion PostgreSQL indisponible"
        ) from exc


@app.get("/operations/pipeline/runs", tags=["System"])
def get_pipeline_runs(limit: int = Query(default=10, ge=1, le=100)):
    """Expose recent pipeline outcomes and volume counters for operations."""
    query = """
        SELECT id, status, started_at, completed_at, collected_count,
               normalized_count, rejected_count, duplicates_removed,
               inserted_count, updated_count, collected_source_counts, source_counts
        FROM pipeline_runs
        ORDER BY started_at DESC
        LIMIT %s;
    """
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (limit,))
                runs = cursor.fetchall()
        return {"count": len(runs), "runs": runs}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Historique pipeline indisponible") from exc


# ============================================================
# 2. LISTE DES OFFRES
# ============================================================

@app.get("/jobs", tags=["Jobs"])
def get_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0)
):

    query = """
        SELECT
            id,
            title,
            company,
            location,
            url,
            source,
            published_at
        FROM jobs
        ORDER BY published_at DESC NULLS LAST, id
        LIMIT %s OFFSET %s;
    """

    with get_connection() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:
            cursor.execute(query, (limit, offset))
            jobs = cursor.fetchall()

    return {
        "count": len(jobs),
        "limit": limit,
        "offset": offset,
        "jobs": jobs
    }


# ============================================================
# 3. LISTE DES PROFILS
# ============================================================

@app.get("/profiles", tags=["Profiles"])
def get_profiles():

    query = """
        SELECT
            id,
            name,
            skills,
            target_roles,
            experience_level,
            contract_type,
            preferred_location,
            created_at,
            updated_at
        FROM profiles
        ORDER BY id;
    """

    with get_connection() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:
            cursor.execute(query)
            profiles = cursor.fetchall()

    return {
        "count": len(profiles),
        "profiles": profiles
    }


# ============================================================
# 4. CRÉER UN PROFIL
# ============================================================

@app.post(
    "/profiles",
    status_code=201,
    tags=["Profiles"]
)
def create_profile(profile: ProfileCreate):

    query = """
        INSERT INTO profiles (
            name,
            skills,
            target_roles,
            experience_level,
            contract_type,
            preferred_location
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING
            id,
            name,
            skills,
            target_roles,
            experience_level,
            contract_type,
            preferred_location,
            created_at;
    """

    values = (
        profile.name,
        Json(profile.skills),
        Json(profile.target_roles),
        profile.experience_level,
        profile.contract_type,
        profile.preferred_location
    )

    with get_connection() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:
            cursor.execute(query, values)
            created_profile = cursor.fetchone()

    return created_profile


# ============================================================
# 5. MODIFIER UN PROFIL
# ============================================================

@app.put(
    "/profiles/{profile_id}",
    tags=["Profiles"]
)
def update_profile(
    profile_id: int,
    profile: ProfileUpdate
):

    updates = profile.model_dump(
        exclude_unset=True
    )

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Aucune modification fournie"
        )

    allowed_fields = {
        "name",
        "skills",
        "target_roles",
        "experience_level",
        "contract_type",
        "preferred_location"
    }

    fields = []
    values = []

    for key, value in updates.items():

        if key not in allowed_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Champ non autorisé : {key}"
            )

        if value is None:
            raise HTTPException(
                status_code=422,
                detail=f"Le champ {key} ne peut pas être null"
            )

        if key in ("skills", "target_roles"):
            value = Json(value)

        fields.append(f"{key} = %s")
        values.append(value)

    fields.append("updated_at = NOW()")
    values.append(profile_id)

    query = f"""
        UPDATE profiles
        SET {", ".join(fields)}
        WHERE id = %s
        RETURNING
            id,
            name,
            skills,
            target_roles,
            experience_level,
            contract_type,
            preferred_location,
            updated_at;
    """

    with get_connection() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:
            cursor.execute(query, values)
            updated_profile = cursor.fetchone()

    if updated_profile is None:
        raise HTTPException(
            status_code=404,
            detail="Profil introuvable"
        )

    return updated_profile


# ============================================================
# 6. LANCER LE MATCHING
# ============================================================

@app.post(
    "/profiles/{profile_id}/match",
    tags=["Matching"]
)
def trigger_matching(profile_id: int):

    try:
        matched_count = run_profile_matching(
            profile_id
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc)
        ) from exc

    return {
        "status": "completed",
        "profile_id": profile_id,
        "matched_jobs": matched_count,
        "message": "Matching terminé avec succès"
    }


# ============================================================
# 7. RECOMMANDATIONS D'UN PROFIL
# ============================================================

@app.get(
    "/profiles/{profile_id}/matches",
    tags=["Matching"]
)
def get_profile_matches(
    profile_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    min_score: float = Query(default=0, ge=0, le=100)
):

    with get_connection() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            cursor.execute(
                """
                SELECT id
                FROM profiles
                WHERE id = %s;
                """,
                (profile_id,)
            )

            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Profil introuvable"
                )

            cursor.execute(
                """
                
                SELECT
                    j.id,
                    j.title,
                    j.company,
                    j.location,
                    j.url,
                    j.source,
                    j.published_at,
                    m.semantic_score,
                    m.role_score,
                    m.skill_score,
                    m.final_score,
                    COALESCE(m.adjusted_score, m.final_score)
                        AS adjusted_score,
                    m.matched_at

                FROM job_matches m

                INNER JOIN jobs j
                    ON j.id = m.job_id

                WHERE m.profile_id = %s
                AND COALESCE(m.adjusted_score, m.final_score) >= %s

                ORDER BY
                    COALESCE(m.adjusted_score, m.final_score) DESC,
                    j.id

                LIMIT %s OFFSET %s;

                """,
                (
                    profile_id,
                    min_score,
                    limit,
                    offset
                )
            )

            matches = cursor.fetchall()

    return {
        "profile_id": profile_id,
        "count": len(matches),
        "limit": limit,
        "offset": offset,
        "min_score": min_score,
        "matches": matches
    }


# ============================================================
# 8. ANALYSE AUTOMATIQUE DU CV
# ============================================================

@app.post("/cv/analyze", tags=["CV Analysis"])
async def analyze_cv(file: UploadFile = File(...)):

    filename = file.filename or ""

    if not filename.lower().endswith(
        (".pdf", ".docx")
    ):
        raise HTTPException(
            status_code=415,
            detail="Formats acceptés : PDF et DOCX."
        )

    max_size = 5 * 1024 * 1024

    content = await file.read(max_size + 1)
    await file.close()

    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail="Le CV ne doit pas dépasser 5 Mo."
        )

    text = extract_cv_text(
        filename,
        content
    )

    skills = extract_cv_skills(text)

    return {
        "filename": filename,
        "skills": skills,
        "total_skills": len(skills),
        "text_length": len(text)
    }
