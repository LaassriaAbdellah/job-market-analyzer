import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from uuid import UUID, uuid4

import psycopg2
from psycopg2.extras import Json, execute_batch, execute_values
from dotenv import load_dotenv

from common import BASE_DIR, NORMALIZED_JOBS_PATH


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Charger le fichier .env situé à la racine du projet
load_dotenv(BASE_DIR / ".env")


def get_connection():
    """
    Crée une connexion à PostgreSQL.
    """
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        connect_timeout=int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10")),
    )


def create_jobs_table():
    """
    Crée la table jobs si elle n'existe pas.
    """
    query = """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        external_id TEXT NOT NULL,
        title TEXT NOT NULL,
        company TEXT,
        location TEXT,
        description TEXT,
        url TEXT NOT NULL,
        source TEXT NOT NULL,
        published_at TIMESTAMPTZ,
        employment_type TEXT,
        remote BOOLEAN,
        skills JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query)
            cursor.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS external_id TEXT;")
            cursor.execute("""
                UPDATE jobs
                SET external_id = COALESCE(NULLIF(substring(id FROM position('_' IN id) + 1), ''), id)
                WHERE external_id IS NULL OR external_id = '';
            """)
            cursor.execute("ALTER TABLE jobs ALTER COLUMN external_id SET NOT NULL;")
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_source_external_id
                ON jobs (source, external_id);
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_analysis (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                    cleaned_description TEXT NOT NULL DEFAULT '',
                    extracted_skills JSONB NOT NULL DEFAULT '{}'::jsonb,
                    total_skills_count INTEGER NOT NULL DEFAULT 0,
                    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id UUID PRIMARY KEY,
                    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ,
                    collected_count INTEGER NOT NULL DEFAULT 0,
                    normalized_count INTEGER NOT NULL DEFAULT 0,
                    rejected_count INTEGER NOT NULL DEFAULT 0,
                    duplicates_removed INTEGER NOT NULL DEFAULT 0,
                    inserted_count INTEGER NOT NULL DEFAULT 0,
                    updated_count INTEGER NOT NULL DEFAULT 0,
                    collected_source_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
                    source_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
                    errors JSONB NOT NULL DEFAULT '[]'::jsonb
                );
            """)

    logging.info("Table 'jobs' prête.")


def load_normalized_jobs(
    filepath: Path = NORMALIZED_JOBS_PATH,
    jobs: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, int]:
    """
    Charge les offres normalisées dans PostgreSQL.

    Si une offre existe déjà, elle est mise à jour
    grâce à ON CONFLICT.
    """

    if jobs is None:
        with Path(filepath).open("r", encoding="utf-8") as f:
            jobs = json.load(f)
    jobs = list(jobs)

    query = """
    INSERT INTO jobs (
        id,
        external_id,
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
    )
    VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s::jsonb
    )

    ON CONFLICT (source, external_id)
    DO UPDATE SET
        title = EXCLUDED.title,
        company = EXCLUDED.company,
        location = EXCLUDED.location,
        description = EXCLUDED.description,
        url = EXCLUDED.url,
        source = EXCLUDED.source,
        published_at = EXCLUDED.published_at,
        employment_type = EXCLUDED.employment_type,
        remote = EXCLUDED.remote,
        skills = EXCLUDED.skills,
        updated_at = NOW();
    """

    values = []

    for job in jobs:
        values.append(
            (
                job.get("id"),
                job.get("external_id"),
                job.get("title"),
                job.get("company"),
                job.get("location"),
                job.get("description"),
                job.get("url"),
                job.get("source"),
                job.get("published_at"),
                job.get("employment_type"),
                job.get("remote"),
                json.dumps(
                    job.get("skills", []),
                    ensure_ascii=False
                )
            )
        )

    identities = list(dict.fromkeys(
        (job.get("source"), job.get("external_id"))
        for job in jobs
        if job.get("source") and job.get("external_id")
    ))
    if not identities:
        return {"inserted": 0, "updated": 0}

    with get_connection() as conn:
        with conn.cursor() as cursor:
            # Serialize this loader so insert/update counters remain accurate across workers.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('job-market-jobs-upsert'));")
            existing = set()
            identity_batch_size = 100
            for offset in range(0, len(identities), identity_batch_size):
                identity_batch = identities[offset:offset + identity_batch_size]
                execute_values(
                    cursor,
                    "SELECT source, external_id FROM jobs WHERE (source, external_id) IN (%s)",
                    identity_batch,
                    template="(%s, %s)",
                )
                # execute_values executes each page separately; collect every page's rows
                # before the next SELECT replaces the cursor result.
                existing.update(cursor.fetchall())
            execute_batch(
                cursor,
                query,
                values,
                page_size=100
            )

    inserted = sum(identity not in existing for identity in identities)
    updated = len(identities) - inserted
    stats = {"inserted": inserted, "updated": updated}
    logging.info("PostgreSQL : %s insérées, %s mises à jour.", inserted, updated)
    return stats


def start_pipeline_run() -> UUID:
    run_id = uuid4()
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO pipeline_runs (id, status) VALUES (%s, 'running');",
                (str(run_id),),
            )
    return run_id


def finish_pipeline_run(run_id: UUID, status: str, stats: Dict[str, Any], errors: list[str]) -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE pipeline_runs SET status=%s, completed_at=NOW(),
                   collected_count=%s, normalized_count=%s, rejected_count=%s,
                   duplicates_removed=%s, inserted_count=%s, updated_count=%s,
                   collected_source_counts=%s, source_counts=%s, errors=%s WHERE id=%s;""",
                (
                    status,
                    stats.get("collected_count", 0),
                    stats.get("normalized_count", 0),
                    stats.get("rejected_count", 0),
                    stats.get("duplicates_removed", 0),
                    stats.get("inserted_count", 0),
                    stats.get("updated_count", 0),
                    Json(stats.get("collected_source_counts", {})),
                    Json(stats.get("source_counts", {})),
                    Json(errors),
                    str(run_id),
                ),
            )


def show_stats():
    """
    Affiche quelques statistiques pour vérifier le chargement.
    """

    with get_connection() as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                "SELECT COUNT(*) FROM jobs;"
            )

            total = cursor.fetchone()[0]

            cursor.execute("""
                SELECT source, COUNT(*)
                FROM jobs
                GROUP BY source
                ORDER BY source;
            """)

            sources = cursor.fetchall()

    print("\n===== POSTGRESQL =====")
    print(f"Total : {total} offres")

    for source, count in sources:
        print(f"{source}: {count}")


if __name__ == "__main__":
    create_jobs_table()
    load_normalized_jobs()
    show_stats()
