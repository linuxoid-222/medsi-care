"""Behavioral regressions for F2/F3/F9, shared by memory and SQL."""

from datetime import datetime, timedelta, timezone
import os
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app import main
from app.auth import UserContext
from app.db.base import Base
from app.db.repository import DatabaseStore
from app.domain.monitoring import Metric, Observation, SymptomFact
from app.schemas import CheckInCorrectionRequest
from app.store import CheckInRecord, InMemoryStore

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
USER = UserContext("demo-user", "user", "profile-demo")


def clock(value):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    return Clock


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def repository(request, tmp_path, monkeypatch):
    if request.param == "memory":
        store, url = InMemoryStore(), None
    elif request.param == "postgres":
        url = os.getenv("MEDSI_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("MEDSI_TEST_POSTGRES_URL not set; PostgreSQL not tested")
        parsed = make_url(url)
        if parsed.get_backend_name() != "postgresql" or not (parsed.database or "").startswith("medsi_test_"):
            pytest.fail("Dedicated medsi_test_* PostgreSQL database required")
        store = DatabaseStore(url)
        store.reset_demo_profile("profile-demo")
    else:
        url = f"sqlite:///{tmp_path}/facts.db"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()
        store = DatabaseStore(url)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "datetime", clock(NOW))
    monkeypatch.setattr("app.store.datetime", clock(NOW))
    monkeypatch.setattr("app.db.repository.datetime", clock(NOW))
    for day in range(9):
        store.add_observation(Observation(f"sleep-{day}", "profile-demo", Metric.SLEEP_HOURS,
                                          8, "hours", NOW - timedelta(days=day)))
    yield store, url
    if url:
        store.reset_demo_profile("profile-demo")
        main.store.engine.dispose()
        store.engine.dispose()


def confirmed(store, id, when, polarity="present", empty=False):
    text = "Сегодня чувствую слабость" if polarity == "present" else "Слабости нет"
    record = store.add_check_in(CheckInRecord(id, "profile-demo", text, "manual", when))
    facts = [] if empty else [SymptomFact("weakness", polarity, text, True)]
    with patch("app.store.datetime", clock(when)), patch("app.db.repository.datetime", clock(when)):
        store.confirm_check_in("profile-demo", id, corrected_text=None, facts=facts, expected_revision=1)
    return record


def test_f2_sixty_day_old_complaint_is_not_current(repository):
    store, _ = repository
    confirmed(store, "old", NOW - timedelta(days=60))
    assert main.analyze_profile("profile-demo", USER).status.value == "no_change"


def test_f2_current_negation_overrides_earlier_positive(repository):
    store, _ = repository
    confirmed(store, "positive", NOW - timedelta(hours=6))
    confirmed(store, "negative", NOW - timedelta(hours=1), polarity="absent")
    assert main.analyze_profile("profile-demo", USER).status.value == "no_change"


def test_f3_edit_invalidates_previously_confirmed_facts(repository):
    store, _ = repository
    confirmed(store, "edited", NOW - timedelta(hours=1))
    main.correct_check_in("profile-demo", "edited", CheckInCorrectionRequest(text_revision=1,
        corrected_text="Сегодня всё обычно, жалоб нет",
    ), USER)
    assert store.list_symptom_facts("edited") == []
    assert main.analyze_profile("profile-demo", USER).status.value == "no_change"


def test_f9_empty_confirmation_persists_get_and_sql_restart(repository, monkeypatch):
    store, url = repository
    confirmed(store, "empty", NOW - timedelta(minutes=1), empty=True)
    if url:
        monkeypatch.setattr(main, "store", DatabaseStore(url))
    record = next(row for row in main.list_check_ins("profile-demo", USER) if row.id == "empty")
    assert record.status == "confirmed"
    assert main.analyze_profile("profile-demo", USER).status.value == "no_change"


def test_historical_event_keeps_original_text_provenance_after_edit(repository, monkeypatch):
    store, url = repository
    confirmed(store, "original", NOW - timedelta(hours=1))
    main.analyze_profile("profile-demo", USER)
    original = main.list_events("profile-demo", USER)[0].model_dump(mode="json")
    provenance = original.get("text_provenance", [])
    assert len(provenance) == 1
    assert provenance[0]["check_in_id"] == "original"
    assert provenance[0]["fact_id"]
    assert provenance[0]["evidence"] == "Сегодня чувствую слабость"
    main.correct_check_in("profile-demo", "original", CheckInCorrectionRequest(text_revision=1,
        corrected_text="Слабости нет",
    ), USER)
    if url:
        monkeypatch.setattr(main, "store", DatabaseStore(url))
    assert main.list_events("profile-demo", USER)[0].model_dump(mode="json") == original


@pytest.mark.parametrize("age, expected", [
    (timedelta(hours=24), "attention"),
    (timedelta(hours=24, microseconds=1), "no_change"),
    (timedelta(), "attention"),
    (-timedelta(microseconds=1), "no_change"),
])
def test_f2_explicit_window_boundaries(repository, age, expected):
    store, _ = repository
    confirmed(store, "boundary", NOW - age)
    assert main.analyze_profile("profile-demo", USER).status.value == expected


def test_f2_uncertain_supersedes_positive_but_empty_is_not_negation(repository):
    store, _ = repository
    confirmed(store, "positive", NOW - timedelta(hours=3))
    confirmed(store, "empty", NOW - timedelta(hours=2), empty=True)
    assert main.analyze_profile("profile-demo", USER).status.value == "attention"
    confirmed(store, "uncertain", NOW - timedelta(hours=1), polarity="uncertain")
    result = main.analyze_profile("profile-demo", USER)
    assert result.status.value == "no_change"
    assert [fact.polarity for fact in result.text_provenance] == ["uncertain"]


def test_f2_confirmation_after_cutoff_is_not_future_knowledge(repository):
    store, _ = repository
    # The first confirmation, not a no-op retry, occurs after the cutoff.
    store.add_check_in(CheckInRecord("late", "profile-demo", "Слабость", "manual", NOW - timedelta(hours=1)))
    facts = [SymptomFact("weakness", "present", "Слабость", True)]
    with patch("app.store.datetime", clock(NOW + timedelta(hours=1))), patch(
        "app.db.repository.datetime", clock(NOW + timedelta(hours=1))
    ):
        store.confirm_check_in("profile-demo", "late", corrected_text=None, facts=facts, expected_revision=1)
    assert main.analyze_profile("profile-demo", USER).status.value == "no_change"


def test_f2_late_confirmation_does_not_rejuvenate_old_record(repository):
    store, _ = repository
    store.add_check_in(CheckInRecord("late-old", "profile-demo", "Слабость", "manual", NOW - timedelta(days=60)))
    facts = [SymptomFact("weakness", "present", "Слабость", True)]
    with patch("app.store.datetime", clock(NOW)), patch("app.db.repository.datetime", clock(NOW)):
        store.confirm_check_in("profile-demo", "late-old", corrected_text=None, facts=facts, expected_revision=1)
    assert main.analyze_profile("profile-demo", USER).status.value == "no_change"


def test_f2_identical_timestamp_conflict_is_conservative(repository):
    store, _ = repository
    confirmed(store, "tie-positive", NOW - timedelta(hours=1))
    confirmed(store, "tie-negative", NOW - timedelta(hours=1), polarity="absent")
    result = main.analyze_profile("profile-demo", USER)
    assert result.status.value == "no_change"
    assert {row.resolution for row in result.text_provenance} == {"conflict"}
    assert {row.polarity for row in result.text_provenance} == {"present", "absent"}


def test_f3_same_text_keeps_confirmation_and_stale_operations_return_409(repository):
    store, _ = repository
    confirmed(store, "revision", NOW - timedelta(hours=1))
    with TestClient(main.app) as client:
        login = client.post("/api/v1/auth/login", json={"user_id": "demo-user", "password": "demo-user"})
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        path = "/api/v1/profiles/profile-demo/check-ins/revision"
        original = client.get(path).json()
        assert original["facts"][0]["id"]
        same = client.patch(path, json={"text_revision": 1, "corrected_text": original["text"]})
        assert same.status_code == 200
        assert same.json()["status"] == "confirmed"
        assert same.json()["text_revision"] == 1
        changed = client.patch(path, json={"text_revision": 1, "corrected_text": "Слабости нет"})
        assert changed.status_code == 200
        assert changed.json()["text_revision"] == 2
        assert changed.json()["confirmed_revision"] is None
        assert changed.json()["facts"] == []
        assert changed.json()["status"] == "awaiting_analysis"
        assert client.post(path + "/confirm", json={"text_revision": 1, "facts": []}).status_code == 409
        assert client.patch(path, json={"text_revision": 1, "corrected_text": "Старый текст"}).status_code == 409
        # Even the current revision cannot silently change text in confirmation.
        mismatch = client.post(path + "/confirm", json={
            "text_revision": 2, "corrected_text": "Другой текст", "facts": [],
        })
        assert mismatch.status_code == 409
        assert "Текст изменён" in mismatch.json()["detail"]
        assert client.get(path).json() == changed.json()
        done = client.post(path + "/confirm", json={"text_revision": 2, "facts": []})
        assert done.status_code == 200
        assert client.get(path).json()["status"] == "confirmed"
        assert client.get(path).json()["facts"] == []


def test_f3_extraction_for_old_revision_is_rejected(repository, monkeypatch):
    store, _ = repository
    record = store.add_check_in(CheckInRecord("race", "profile-demo", "Сегодня слабость", "manual", NOW))
    class EditingProvider:
        def __init__(self, settings):
            pass
        def extract_facts(self, text):
            assert text == record.text
            store.update_check_in_text("profile-demo", record.id, "Слабости нет", expected_revision=1)
            return [SymptomFact("weakness", "present", "слабость", False)]
        def close(self):
            pass
    monkeypatch.setattr(main, "GigaChatProvider", EditingProvider)
    monkeypatch.setattr(main.GigaChatSettings, "from_env", lambda: object())
    with TestClient(main.app) as client:
        login = client.post("/api/v1/auth/login", json={"user_id": "demo-user", "password": "demo-user"})
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        response = client.post("/api/v1/profiles/profile-demo/check-ins/race/extract")
    assert response.status_code == 409
    assert store.get_check_in("profile-demo", "race").text_revision == 2
    assert store.list_symptom_facts("race") == []
    assert store.list_monitoring_events("profile-demo") == []


def test_f9_delete_one_then_all_facts_and_keep_numeric_monitoring(repository):
    store, url = repository
    with TestClient(main.app) as client:
        login = client.post("/api/v1/auth/login", json={"user_id": "demo-user", "password": "demo-user"})
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        created = client.post("/api/v1/profiles/profile-demo/check-ins", json={"text": "Слабость и кашель"}).json()
        path = f"/api/v1/profiles/profile-demo/check-ins/{created['id']}"
        fact = {"category": "weakness", "polarity": "present", "evidence": "Слабость"}
        assert client.post(path + "/confirm", json={"text_revision": 1, "facts": [fact]}).status_code == 200
        assert len(client.get(path).json()["facts"]) == 1
        assert client.post(path + "/confirm", json={"text_revision": 1, "facts": []}).status_code == 200
        if url:
            reopened = DatabaseStore(url)
            try:
                assert reopened.get_check_in("profile-demo", created["id"]).is_confirmed
                assert reopened.list_symptom_facts(created["id"]) == []
            finally:
                reopened.engine.dispose()
        assert client.get(path).json()["status"] == "confirmed"
        assert client.get(path).json()["facts"] == []
        store.add_observation(Observation("changed-sleep", "profile-demo", Metric.SLEEP_HOURS,
                                          4, "hours", NOW + timedelta(microseconds=1)))
        # Fixed test clock advances to include a newly arrived changed observation.
        with patch.object(main, "datetime", clock(NOW + timedelta(seconds=1))):
            result = client.post("/api/v1/profiles/profile-demo/analysis").json()
        assert result["status"] == "attention"
        assert result["text_provenance"] == []


def test_safety_snapshot_survives_edit_and_regular_fact_expiry(repository):
    store, _ = repository
    with TestClient(main.app) as client:
        login = client.post("/api/v1/auth/login", json={"user_id": "demo-user", "password": "demo-user"})
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        check = client.post("/api/v1/profiles/profile-demo/check-ins", json={"text": "Боль в груди"}).json()
        path = f"/api/v1/profiles/profile-demo/check-ins/{check['id']}"
        saved = client.post(path + "/confirm", json={"text_revision": 1, "facts": [
            {"category": "chest_pain", "polarity": "present", "evidence": "Боль в груди"}
        ]}).json()["safety_event"]
        assert saved["text_provenance"][0]["rule_version"] == "safety-v1"
        assert saved["text_provenance"][0]["resolution"] == "direct_confirmation"
        assert client.patch(path, json={"text_revision": 1, "corrected_text": "Боли нет"}).status_code == 200
        assert client.post(path + "/confirm", json={"text_revision": 2, "facts": []}).status_code == 200
        assert client.get("/api/v1/profiles/profile-demo/events").json() == [saved]
        assert len(store.list_notifications("demo-caregiver")) == 1


def test_confirm_cas_rejects_edit_between_validation_and_write(repository, monkeypatch):
    store, _ = repository
    store.add_check_in(CheckInRecord("confirm-race", "profile-demo", "Слабость", "manual", NOW))
    original_validator = main.validate_confirmed_facts
    def edit_during_validation(source_text, facts):
        validated = original_validator(source_text, facts)
        store.update_check_in_text("profile-demo", "confirm-race", "Больше жалоб нет", expected_revision=1)
        return validated
    monkeypatch.setattr(main, "validate_confirmed_facts", edit_during_validation)
    with TestClient(main.app) as client:
        login = client.post("/api/v1/auth/login", json={"user_id": "demo-user", "password": "demo-user"})
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        response = client.post("/api/v1/profiles/profile-demo/check-ins/confirm-race/confirm", json={
            "text_revision": 1, "facts": [{"category": "weakness", "polarity": "present", "evidence": "Слабость"}],
        })
        assert response.status_code == 409
    assert store.list_symptom_facts("confirm-race") == []
    assert not store.get_check_in("profile-demo", "confirm-race").is_confirmed
    assert store.list_monitoring_events("profile-demo") == []


def test_confirmation_validates_evidence_and_required_revision(repository):
    store, _ = repository
    confirmed(store, "validated", NOW - timedelta(minutes=1), empty=True)
    with TestClient(main.app) as client:
        login = client.post("/api/v1/auth/login", json={"user_id": "demo-user", "password": "demo-user"})
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        path = "/api/v1/profiles/profile-demo/check-ins/validated"
        before = client.get(path).json()
        assert client.post(path + "/confirm", json={"facts": []}).status_code == 422
        assert client.post(path + "/confirm", json={"text_revision": 1, "facts": [{
            "category": "chest_pain", "polarity": "present", "evidence": "Несуществующая цитата",
        }]}).status_code == 422
        assert client.get(path).json() == before
        assert store.list_monitoring_events("profile-demo") == []


def test_safety_provenance_contains_only_triggering_facts(repository):
    with TestClient(main.app) as client:
        login = client.post("/api/v1/auth/login", json={"user_id": "demo-user", "password": "demo-user"})
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        check = client.post("/api/v1/profiles/profile-demo/check-ins", json={"text": "Боль в груди, слабости нет"}).json()
        response = client.post(f"/api/v1/profiles/profile-demo/check-ins/{check['id']}/confirm", json={
            "text_revision": 1, "facts": [
                {"category": "chest_pain", "polarity": "present", "evidence": "Боль в груди"},
                {"category": "weakness", "polarity": "absent", "evidence": "слабости нет"},
            ],
        })
        assert response.status_code == 200
        assert len(response.json()["facts"]) == 2
        provenance = response.json()["safety_event"]["text_provenance"]
        assert len(provenance) == 1
        assert provenance[0]["category"] == "chest_pain"
