
import os
import pytest
import httpx

BASE_URL = os.getenv(
    "API_BASE_URL",
    "http://127.0.0.1:8000"
)


@pytest.fixture(scope="module")
def client():
    with httpx.Client(
        base_url=BASE_URL,
        timeout=30
    ) as client:
        yield client


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200


def test_jobs(client):
    response = client.get("/jobs")

    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, (list, dict))


def test_profiles(client):
    response = client.get("/profiles")

    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, (list, dict))


def test_analytics_overview(client):
    response = client.get("/analytics/overview")

    assert response.status_code == 200

    data = response.json()

    assert "total_jobs" in data
    assert "total_companies" in data
    assert "total_sources" in data
    assert "total_profiles" in data

    assert data["total_jobs"] >= 0


def test_analytics_sources(client):
    response = client.get("/analytics/sources")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)

    for item in data:
        assert "source" in item
        assert "count" in item
        assert int(item["count"]) >= 0


def test_analytics_skills(client):
    response = client.get("/analytics/skills")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)

    for item in data:
        assert "skill" in item
        assert "count" in item


def test_analytics_contracts(client):
    response = client.get("/analytics/contracts")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)

    for item in data:
        assert "contract_type" in item
        assert "count" in item


def test_analytics_locations(client):
    response = client.get("/analytics/locations")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)

    for item in data:
        assert "location" in item
        assert "count" in item


def test_matching_analytics(client):
    response = client.get("/analytics/matching/6")

    assert response.status_code == 200

    data = response.json()

    assert "total_matches" in data
    assert "average_score" in data
    assert "max_score" in data
    assert "scores" in data

    assert isinstance(data["scores"], list)

    assert data["total_matches"] == len(data["scores"])

    for score in data["scores"]:
        assert 0 <= float(score) <= 100


def test_unknown_profile_matching(client):
    response = client.get(
        "/analytics/matching/999999999"
    )

    assert response.status_code == 404
