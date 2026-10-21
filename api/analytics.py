from fastapi import APIRouter
from api.database import get_connection
from fastapi import HTTPException

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"]
)


@router.get("/overview")
def get_overview():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    (SELECT COUNT(*) FROM jobs) AS total_jobs,
                    (SELECT COUNT(DISTINCT company)
                     FROM jobs
                     WHERE company IS NOT NULL) AS total_companies,
                    (SELECT COUNT(DISTINCT source)
                     FROM jobs) AS total_sources,
                    (SELECT COUNT(*) FROM profiles) AS total_profiles;
            """)
            row = cursor.fetchone()

    return dict(row)


@router.get("/sources")
def get_sources():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT source, COUNT(*) AS count
                FROM jobs
                GROUP BY source
                ORDER BY count DESC;
            """)
            rows = cursor.fetchall()

    return [dict(row) for row in rows]


@router.get("/skills")
def get_skills():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    skill.value AS skill,
                    COUNT(*) AS count
                FROM jobs j
                CROSS JOIN LATERAL
                    jsonb_array_elements_text(j.skills) AS skill(value)
                GROUP BY skill.value
                ORDER BY count DESC
                LIMIT 15;
            """)
            rows = cursor.fetchall()

    return [dict(row) for row in rows]

@router.get("/contracts")
def get_contracts():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    COALESCE(
                        NULLIF(TRIM(employment_type), ''),
                        'Non précisé'
                    ) AS contract_type,
                    COUNT(*) AS count
                FROM jobs
                GROUP BY 1
                ORDER BY count DESC;
            """)
            rows = cursor.fetchall()

    return [dict(row) for row in rows]


@router.get("/locations")
def get_locations():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    COALESCE(
                        NULLIF(TRIM(location), ''),
                        'Non précisée'
                    ) AS location,
                    COUNT(*) AS count
                FROM jobs
                GROUP BY 1
                ORDER BY count DESC
                LIMIT 15;
            """)
            rows = cursor.fetchall()

    return [dict(row) for row in rows]


@router.get("/matching/{profile_id}")
def get_matching_analytics(profile_id: int):
    with get_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                "SELECT id FROM profiles WHERE id = %s",
                (profile_id,)
            )

            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Profil introuvable"
                )

            cursor.execute("""
                SELECT
                    COALESCE(adjusted_score, final_score)
                        AS score
                FROM job_matches
                WHERE profile_id = %s
                ORDER BY score DESC;
            """, (profile_id,))

            rows = cursor.fetchall()

    scores = [float(row["score"]) for row in rows]

    return {
        "profile_id": profile_id,
        "total_matches": len(scores),
        "average_score": (
            round(sum(scores) / len(scores), 2)
            if scores else 0
        ),
        "max_score": max(scores) if scores else 0,
        "scores": scores
    }