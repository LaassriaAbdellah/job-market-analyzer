import os
import json
import logging
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_batch
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
        port=os.getenv("POSTGRES_PORT", "5432")
    )


def create_jobs_table():
    """
    Crée la table jobs si elle n'existe pas.
    """
    query = """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
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

    logging.info("Table 'jobs' prête.")


def load_normalized_jobs(filepath: Path = NORMALIZED_JOBS_PATH):
    """
    Charge les offres normalisées dans PostgreSQL.

    Si une offre existe déjà, elle est mise à jour
    grâce à ON CONFLICT.
    """

    with filepath.open("r", encoding="utf-8") as f:
        jobs = json.load(f)

    query = """
    INSERT INTO jobs (
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
    )
    VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s::jsonb
    )

    ON CONFLICT (id)
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

    with get_connection() as conn:
        with conn.cursor() as cursor:
            execute_batch(
                cursor,
                query,
                values,
                page_size=100
            )

    logging.info(
        "%s offres chargées/mises à jour dans PostgreSQL.",
        len(jobs)
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