"""Focused tests for database UPSERT counters across multiple identity batches."""

import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import database


class FakeCursor:
    def __init__(self, database_state):
        self.database_state = database_state
        self.selected_rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query):
        # The production function takes an advisory lock before reading identities.
        assert "pg_advisory_xact_lock" in query

    def fetchall(self):
        return self.selected_rows


class FakeConnection:
    def __init__(self, database_state):
        self.database_state = database_state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self):
        return FakeCursor(self.database_state)


def _jobs(count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": f"remotive_{index}",
            "external_id": str(index),
            "title": f"Job {index}",
            "company": "Example",
            "location": "Remote",
            "description": f"Description {index}",
            "url": f"https://example.test/jobs/{index}",
            "source": "remotive",
            "published_at": None,
            "employment_type": None,
            "remote": True,
            "skills": [],
        }
        for index in range(count)
    ]


def _install_fake_database(monkeypatch, existing_identities):
    database_state = set(existing_identities)
    actual_operations = {"inserted": 0, "updated": 0}
    select_batch_sizes = []

    monkeypatch.setattr(database, "get_connection", lambda: FakeConnection(database_state))

    def fake_execute_values(cursor, query, identities, template):
        assert "SELECT source, external_id" in query
        assert len(identities) <= 100
        select_batch_sizes.append(len(identities))
        cursor.selected_rows = [identity for identity in identities if identity in database_state]

    def fake_execute_batch(cursor, query, values, page_size):
        for row in values:
            identity = (row[7], row[1])
            if identity in database_state:
                actual_operations["updated"] += 1
            else:
                database_state.add(identity)
                actual_operations["inserted"] += 1

    monkeypatch.setattr(database, "execute_values", fake_execute_values)
    monkeypatch.setattr(database, "execute_batch", fake_execute_batch)
    return database_state, actual_operations, select_batch_sizes


@pytest.mark.parametrize(
    ("existing_count", "expected_inserted", "expected_updated"),
    [
        (0, 250, 0),
        (250, 0, 250),
        (125, 125, 125),
    ],
    ids=["all-new", "all-existing", "mixed"],
)
def test_upsert_counts_match_operations_over_multiple_batches(
    monkeypatch, existing_count, expected_inserted, expected_updated
):
    jobs = _jobs(250)
    initial_identities = {
        (job["source"], job["external_id"])
        for job in jobs[:existing_count]
    }
    database_state, actual_operations, select_batch_sizes = _install_fake_database(
        monkeypatch, initial_identities
    )

    stats = database.load_normalized_jobs(jobs=jobs)

    assert stats == {
        "inserted": expected_inserted,
        "updated": expected_updated,
    }
    assert stats == actual_operations
    assert len(database_state) == existing_count + expected_inserted
    assert select_batch_sizes == [100, 100, 50]
