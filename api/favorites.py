"""Endpoints FastAPI pour les offres favorites."""
from fastapi import APIRouter, HTTPException
from psycopg2.extras import RealDictCursor

from api.database import get_connection

router = APIRouter(prefix="/profiles", tags=["Favorites"])


def ensure_profile(cursor, profile_id: int):
    cursor.execute("SELECT 1 FROM profiles WHERE id = %s", (profile_id,))
    if cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail="Profil introuvable")


@router.post("/{profile_id}/favorites/{job_id}", status_code=201)
def add_favorite(profile_id: int, job_id: str):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            ensure_profile(cursor, profile_id)
            cursor.execute("SELECT 1 FROM jobs WHERE id = %s", (job_id,))
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Offre introuvable")
            cursor.execute(
                """
                INSERT INTO job_favorites (profile_id, job_id)
                VALUES (%s, %s)
                ON CONFLICT (profile_id, job_id) DO NOTHING
                RETURNING profile_id, job_id, created_at
                """,
                (profile_id, job_id),
            )
            added = cursor.fetchone()
            if added is None:
                cursor.execute(
                    """
                    SELECT profile_id, job_id, created_at
                    FROM job_favorites
                    WHERE profile_id = %s AND job_id = %s
                    """,
                    (profile_id, job_id),
                )
                return {"status": "already_saved", "favorite": cursor.fetchone()}
            return {"status": "added", "favorite": added}


@router.get("/{profile_id}/favorites")
def list_favorites(profile_id: int):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            ensure_profile(cursor, profile_id)
            cursor.execute(
                """
                SELECT
                    f.profile_id, f.job_id, f.created_at AS saved_at,
                    j.title, j.company, j.location, j.url,
                    j.source, j.published_at,
                    m.final_score, m.adjusted_score
                FROM job_favorites AS f
                JOIN jobs AS j ON j.id = f.job_id
                LEFT JOIN job_matches AS m
                    ON m.profile_id = f.profile_id AND m.job_id = f.job_id
                WHERE f.profile_id = %s
                ORDER BY f.created_at DESC, f.job_id
                """,
                (profile_id,),
            )
            favorites = cursor.fetchall()
    return {"profile_id": profile_id, "count": len(favorites), "favorites": favorites}


@router.delete("/{profile_id}/favorites/{job_id}")
def remove_favorite(profile_id: int, job_id: str):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            ensure_profile(cursor, profile_id)
            cursor.execute(
                """
                DELETE FROM job_favorites
                WHERE profile_id = %s AND job_id = %s
                RETURNING job_id
                """,
                (profile_id, job_id),
            )
            if cursor.fetchone() is None:
                raise HTTPException(status_code=404, detail="Favori introuvable")
    return {"status": "removed", "profile_id": profile_id, "job_id": job_id}
