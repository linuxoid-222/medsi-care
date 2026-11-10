"""HTTP/persistence regressions; optional live PostgreSQL uses a dedicated DB."""

from datetime import datetime, timedelta, timezone
import os

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app import main
from app.db.base import Base
from app.db.repository import DatabaseStore
from app.domain.monitoring import Metric, Observation
from app.schemas import NumericAnalysisDetails


NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


@pytest.fixture(params=["sqlite", "postgres"])
def api(request, tmp_path, monkeypatch):
    if request.param == "postgres":
        url = os.getenv("MEDSI_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("MEDSI_TEST_POSTGRES_URL not set; PostgreSQL not tested")
        parsed = make_url(url)
        if parsed.get_backend_name() != "postgresql" or not parsed.database.startswith("medsi_test_"):
            pytest.fail("PostgreSQL tests require a dedicated medsi_test_* database")
    else:
        url = f"sqlite:///{tmp_path}/monitoring.db"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()
    repository = DatabaseStore(url)
    repository.reset_demo_profile("profile-demo")
    monkeypatch.setattr(main, "store", repository)
    monkeypatch.setenv("MEDSI_DEMO_MODE", "true")
    with TestClient(main.app) as client:
        login = client.post("/api/v1/auth/login", json={"user_id": "demo-user", "password": "demo-user"})
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield client, repository, url
    repository.reset_demo_profile("profile-demo")
    repository.engine.dispose()


def test_http_multimetric_snapshot_survives_sql_roundtrip(api):
    client, repository, url = api
    for day in range(1, 9):
        for metric, value, unit in ((Metric.SLEEP_HOURS, 8, "hours"), (Metric.PULSE_BPM, 70, "bpm")):
            repository.add_observation(Observation(f"{metric.value}-{day}", "profile-demo", metric,
                                                  value, unit, NOW - timedelta(days=day), quality="good"))
    for metric, value, unit in (("sleep_hours", 4, "hours"), ("pulse_bpm", 70, "bpm")):
        response = client.post("/api/v1/profiles/profile-demo/observations", json={
            "metric": metric, "value": value, "unit": unit,
            "quality": "good", "measured_at": NOW.isoformat(),
        })
        assert response.status_code == 201
    response = client.post("/api/v1/profiles/profile-demo/analysis", params={"as_of": NOW.isoformat()})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "attention"
    assert result["algorithm_version"] == "daily-multimetric-v2+facts-window-v1"
    metrics = {item["metric"]: item for item in result["analysis_details"]["metrics"]}
    assert metrics["sleep_hours"]["status"] == "attention"
    assert metrics["pulse_bpm"]["status"] == "no_change"
    assert metrics["activity_minutes"]["status"] == "missing_measurement"
    assert metrics["sleep_hours"]["baseline"]["sample_count"] == 8
    assert metrics["sleep_hours"]["quality"] == "good"
    reopened = DatabaseStore(url)
    try:
        stored = reopened.list_monitoring_events("profile-demo")[0].event
        assert NumericAnalysisDetails.model_validate(stored.analysis_details).model_dump(mode="json") == result["analysis_details"]
        assert len(stored.source_observation_ids) == 18
        assert reopened.get_profile_timezone("profile-demo") == "Europe/Moscow"
        assert len(reopened.list_notifications("demo-caregiver")) == 1
    finally:
        reopened.engine.dispose()
    listed = client.get("/api/v1/profiles/profile-demo/events").json()
    assert listed[0]["analysis_details"] == result["analysis_details"]


def test_http_daily_history_and_trends_do_not_depend_on_viewport(api):
    client, repository, _ = api
    for day in range(1, 9):
        repository.add_observation(Observation(f"duplicate-{day}", "profile-demo", Metric.SLEEP_HOURS,
                                              8, "hours", NOW - timedelta(days=1, seconds=day)))
    repository.add_observation(Observation("current", "profile-demo", Metric.SLEEP_HOURS, 4, "hours", NOW))
    response = client.post("/api/v1/profiles/profile-demo/analysis", params={"as_of": NOW.isoformat()})
    assert response.status_code == 200
    metric = response.json()["analysis_details"]["metrics"][0]
    assert metric["status"] == "insufficient_data"
    assert metric["baseline"]["sample_count"] == 1
    repository.reset_demo_profile("profile-demo")
    for day in range(21):
        repository.add_observation(Observation(f"day-{day}", "profile-demo", Metric.SLEEP_HOURS,
                                              8, "hours", NOW - timedelta(days=day)))
    short = client.get("/api/v1/profiles/profile-demo/trends", params={"days": 7}).json()
    full = client.get("/api/v1/profiles/profile-demo/trends", params={"days": 28}).json()
    assert len(short) == 7
    assert short[-1]["baseline_details"] == full[-1]["baseline_details"]
    assert short[-1]["baseline"] == 8
    assert short[-1]["baseline_details"]["sample_count"] == 14
    assert len({item["day"] for item in full}) == len(full)


def test_http_demo_safety_notifications_and_reset(api):
    client, repository, _ = api
    payload = {"seed": 20261110, "days": 21, "reset": True, "anchor_date": "2026-10-21"}
    response = client.post("/api/v1/demo/load-scenario", json=payload)
    assert response.status_code == 200
    loaded = response.json()
    assert (loaded["observation_count"], loaded["check_in_count"]) == (63, 21)
    result = client.post("/api/v1/profiles/profile-demo/analysis", params={"as_of": "2026-10-21T12:00:00Z"}).json()
    assert result["status"] == "attention"
    assert sum(item["status"] == "attention" for item in result["analysis_details"]["metrics"]) == 3
    # An explicitly historical scenario still cannot pretend to be current data.
    today = client.post("/api/v1/profiles/profile-demo/analysis").json()
    assert today["status"] == "insufficient_data"
    assert all(item["status"] == "missing_measurement" for item in today["analysis_details"]["metrics"])
    check = client.post("/api/v1/profiles/profile-demo/check-ins", json={"text": "У меня боль в груди"}).json()
    response = client.post(f"/api/v1/profiles/profile-demo/check-ins/{check['id']}/confirm", json={
        "text_revision": check["text_revision"],
        "facts": [{"category": "chest_pain", "polarity": "present", "evidence": "боль в груди"}],
    })
    assert response.status_code == 200
    assert response.json()["safety_event"]["level"] == "safety"
    login = client.post("/api/v1/auth/login", json={"user_id": "demo-caregiver", "password": "demo-caregiver"})
    caregiver_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    summary = client.get("/api/v1/caregiver/profiles/profile-demo/summary", headers=caregiver_headers).json()
    assert any(event["level"] == "safety" for event in summary["events"])
    notification = summary["notifications"][0]
    read = client.post(f"/api/v1/notifications/{notification['id']}/read", headers=caregiver_headers)
    assert read.status_code == 200 and read.json()["status"] == "read"
    assert client.post("/api/v1/demo/load-scenario", json=payload).json() == loaded
    assert client.get("/api/v1/profiles/profile-demo/events").json() == []
    assert client.get("/api/v1/notifications", headers=caregiver_headers).json() == []
    assert len(client.get("/api/v1/profiles/profile-demo/observations").json()) == 63
    assert len(client.get("/api/v1/profiles/profile-demo/check-ins").json()) == 21
    assert repository.list_symptom_facts(check["id"]) == []


def test_demo_default_anchor_matches_profile_midnight_and_manual_input(api, monkeypatch):
    from tests.test_fact_lifecycle import clock
    client, repository, _ = api
    midnight = datetime(2026, 11, 9, 21, tzinfo=timezone.utc)
    monkeypatch.setattr(main, "datetime", clock(midnight - timedelta(microseconds=1)))
    first = client.post("/api/v1/demo/load-scenario", json={}).json()
    assert first["anchor_date"] == "2026-11-09"

    now = midnight + timedelta(seconds=1)
    monkeypatch.setattr(main, "datetime", clock(now))
    loaded = client.post("/api/v1/demo/load-scenario", json={}).json()
    assert loaded["anchor_date"] == "2026-11-10"
    assert loaded["timezone"] == "Europe/Moscow"
    assert loaded["seed"] == 20261110
    observations = repository.list_observations("profile-demo")
    assert len(observations) == 63 and observations[-1].measured_at == midnight
    assert max(check.created_at for check in repository.list_check_ins("profile-demo")) == midnight

    # Reject a future anchor before reset can delete the existing history.
    assert client.post("/api/v1/demo/load-scenario", json={"anchor_date": "2026-11-11"}).status_code == 422
    assert repository.list_observations("profile-demo") == observations
    manual = client.post("/api/v1/profiles/profile-demo/observations", json={
        "metric": "sleep_hours", "value": 5, "unit": "hours", "measured_at": now.isoformat(),
    })
    assert manual.status_code == 201
    check = client.post("/api/v1/profiles/profile-demo/check-ins", json={"text": "Сегодня я чувствую слабость"})
    assert check.status_code == 201
    assert client.post("/api/v1/demo/load-scenario", json={"reset": False}).json() == loaded
    assert len(repository.list_observations("profile-demo")) == 64
    assert len(repository.list_check_ins("profile-demo")) == 22
    result = client.post("/api/v1/profiles/profile-demo/analysis").json()
    assert result["status"] == "attention"
    sleep = result["analysis_details"]["metrics"][0]
    assert sleep["day"] == loaded["anchor_date"]
    assert sleep["baseline"]["sample_count"] == 14
    assert sleep["source_observation_ids"] == [manual.json()["id"]]
    assert client.post("/api/v1/demo/load-scenario", json={"anchor_date": loaded["anchor_date"]}).json() == loaded
    assert repository.list_observations("profile-demo") == observations
