"""Orchestrate collection, normalization, PostgreSQL loading, and parsing."""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Make direct `python -m scripts.pipeline` and the Docker PYTHONPATH invocation equivalent.
SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import database
import parser as job_parser
from common import RAW_DIR, RAW_JOBS_PATH, deduplicate_jobs
from normalizer import run_normalization
from scraper import fetch_jobicy_tech_jobs, fetch_remotive_tech_jobs
from web_scraper import scrape_freework_broad_tech

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("job_market.pipeline")

REMOTIVE_CATEGORIES = ("software-dev", "data", "devops")
JOBICY_INDUSTRIES = ("dev", "data-science", "supporting")
FREEWORK_KEYWORDS = ("developpeur", "devops", "cloud", "intelligence artificielle", "cybersecurite")


def _write_latest_raw(jobs: List[Dict[str, Any]]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = RAW_JOBS_PATH.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8") as output_file:
        json.dump(jobs, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    temporary_path.replace(RAW_JOBS_PATH)


def run_pipeline() -> Dict[str, Any]:
    """Run one complete collection and persistence cycle."""
    lock_connection = database.get_connection()
    run_id = None
    lock_acquired = False
    stats: Dict[str, Any] = {
        "collected_count": 0,
        "normalized_count": 0,
        "rejected_count": 0,
        "duplicates_removed": 0,
        "inserted_count": 0,
        "updated_count": 0,
        "source_counts": {},
        "collected_source_counts": {},
    }
    errors: List[str] = []
    try:
        with lock_connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtext('job-market-pipeline'));")
            lock_acquired = bool(cursor.fetchone()[0])
        if not lock_acquired:
            logger.warning("Un autre pipeline est déjà en cours ; cette exécution est ignorée.")
            return {"status": "skipped", **stats}

        database.create_jobs_table()
        run_id = database.start_pipeline_run()
        collected: List[Dict[str, Any]] = []
        source_failures = 0

        collectors = (
            ("remotive", lambda source_errors: fetch_remotive_tech_jobs(list(REMOTIVE_CATEGORIES), source_errors)),
            ("jobicy", lambda source_errors: fetch_jobicy_tech_jobs(list(JOBICY_INDUSTRIES), source_errors)),
            ("free-work", lambda source_errors: scrape_freework_broad_tech(list(FREEWORK_KEYWORDS), errors=source_errors)),
        )
        for source, collect in collectors:
            source_errors: List[str] = []
            try:
                source_jobs = collect(source_errors)
                collected.extend(source_jobs)
                stats["collected_source_counts"][source] = len(source_jobs)
                if source_errors:
                    errors.extend(f"{source}: {message}" for message in source_errors)
                    source_failures += 1
                logger.info("Source %s : %s offres récupérées.", source, len(source_jobs))
            except Exception as error:
                source_failures += 1
                message = f"{source}: {type(error).__name__}: {error}"
                errors.append(message)
                stats["collected_source_counts"][source] = 0
                logger.exception("Collecteur %s en échec.", source)

        if source_failures == len(collectors) and not collected:
            raise RuntimeError("Tous les collecteurs ont échoué ; chargement annulé.")

        stats["collected_count"] = len(collected)
        unique_jobs = deduplicate_jobs(collected)
        collection_duplicates = len(collected) - len(unique_jobs)
        stats["duplicates_removed"] = collection_duplicates
        minimum_jobs = max(1, int(os.getenv("PIPELINE_MIN_JOBS", "1")))
        if len(unique_jobs) < minimum_jobs:
            raise RuntimeError(
                f"Volume collecté trop faible : {len(unique_jobs)} offre(s), minimum requis {minimum_jobs}."
            )

        _write_latest_raw(unique_jobs)
        normalization = run_normalization(raw_path=RAW_JOBS_PATH)
        stats["normalized_count"] = normalization["normalized_count"]
        stats["rejected_count"] = normalization["rejected_count"]
        stats["duplicates_removed"] += normalization["duplicates_removed"]
        stats["source_counts"] = normalization["source_counts"]
        if stats["normalized_count"] < minimum_jobs:
            raise RuntimeError(
                f"Volume normalisé trop faible : {stats['normalized_count']} offre(s), "
                f"minimum requis {minimum_jobs}."
            )

        with open(normalization["output_path"], "r", encoding="utf-8") as normalized_file:
            normalized_jobs = json.load(normalized_file)

        load_stats = database.load_normalized_jobs(jobs=normalized_jobs)
        stats["inserted_count"] = load_stats["inserted"]
        stats["updated_count"] = load_stats["updated"]
        try:
            job_parser.run_filtered_parser()
        except Exception as error:
            errors.append(f"parser: {type(error).__name__}: {error}")
            logger.exception("Les offres sont chargées, mais l'analyse des compétences a échoué.")

        status = "partial" if errors else "succeeded"
        database.finish_pipeline_run(run_id, status, stats, errors)
        logger.info("Pipeline %s terminé : %s", run_id, json.dumps(stats, ensure_ascii=False))
        return {"run_id": str(run_id), "status": status, **stats, "errors": errors}
    except Exception as error:
        if run_id is not None:
            errors.append(f"pipeline: {type(error).__name__}: {error}")
            database.finish_pipeline_run(run_id, "failed", stats, errors)
        logger.exception("Échec du pipeline%s.", f" {run_id}" if run_id else "")
        raise
    finally:
        if lock_acquired:
            try:
                with lock_connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(hashtext('job-market-pipeline'));")
            finally:
                lock_connection.close()
        elif not lock_connection.closed:
            lock_connection.close()


def run_scheduler() -> None:
    interval_hours = max(1, int(os.getenv("PIPELINE_INTERVAL_HOURS", "6")))
    run_on_start = os.getenv("PIPELINE_RUN_ON_START", "true").lower() in {"1", "true", "yes"}
    scheduler = BlockingScheduler(timezone=timezone.utc)
    trigger = IntervalTrigger(hours=interval_hours, timezone=timezone.utc)
    scheduler.add_job(
        run_pipeline,
        trigger=trigger,
        id="job-market-collection-pipeline",
        name="Job collection and analysis pipeline",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        next_run_time=datetime.now(timezone.utc) if run_on_start else None,
        replace_existing=True,
    )
    logger.info(
        "Planificateur lancé : intervalle=%s h, exécution au démarrage=%s.",
        interval_hours,
        run_on_start,
    )
    scheduler.start()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--once", action="store_true", help="Exécuter le pipeline une seule fois puis quitter.")
    arguments = cli.parse_args()
    if arguments.once:
        run_pipeline()
    else:
        run_scheduler()
