"""Regression cases from acceptance of 0233065, using real SQL commits."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main
from app.db.repository import DatabaseStore
from tests.test_fact_lifecycle import NOW, clock, repository  # noqa: F401

PROFILE = "/api/v1/profiles/profile-demo"
TEXT = "Синтетическая запись: есть боль в груди."
SAFETY_FACT = {"category": "chest_pain", "polarity": "present", "evidence": "боль в груди"}


def auth(client):
    login = client.post("/api/v1/auth/login", json={"user_id": "demo-user", "password": "demo-user"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_save_retry_after_commit_and_lost_response(repository, monkeypatch):
    store, _ = repository
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth(client) | {"Idempotency-Key": str(uuid4())}
        response_builder = main._check_in_response

        def lose_response(record):
            assert store.get_check_in(record.profile_id, record.id) is not None
            raise ConnectionError("synthetic transport failure after commit")

        monkeypatch.setattr(main, "_check_in_response", lose_response)
        response = client.post(f"{PROFILE}/check-ins", json={"text": TEXT}, headers=headers)
        assert response.status_code == 500
        first, = store.list_check_ins("profile-demo")
        monkeypatch.setattr(main, "_check_in_response", response_builder)
        retry = client.post(f"{PROFILE}/check-ins", json={"text": TEXT}, headers=headers)
        assert retry.status_code == 201
        assert retry.json()["id"] == first.id, {
            "committed_id": first.id, "retry_id": retry.json()["id"],
            "check_in_count": len(store.list_check_ins("profile-demo")),
        }
        assert len(store.list_check_ins("profile-demo")) == 1


def test_demo_next_local_day_replaces_overlapping_history(repository, monkeypatch):
    store, _ = repository
    with TestClient(main.app) as client:
        headers = auth(client)
        first = client.post("/api/v1/demo/load-scenario", json={}, headers=headers)
        assert first.status_code == 200
        assert client.post(f"{PROFILE}/analysis", headers=headers).json()["status"] == "attention"
        monkeypatch.setattr(main, "datetime", clock(NOW + timedelta(days=1)))
        second = client.post("/api/v1/demo/load-scenario", json={"reset": False}, headers=headers)
        assert second.status_code == 200
        result = client.post(f"{PROFILE}/analysis", headers=headers).json()
        assert len(store.list_observations("profile-demo")) == 63 and result["status"] == "attention", {
            "observations": len(store.list_observations("profile-demo")),
            "check_ins": len(store.list_check_ins("profile-demo")),
            "analysis": result["status"],
            "baseline": {item["metric"]: item["baseline"]["center"]
                         for item in result["analysis_details"]["metrics"]},
        }


def test_different_confirmations_return_own_committed_revision(repository, monkeypatch):
    store, url = repository
    other = DatabaseStore(url) if url else store
    committed, release = Event(), Event()

    class PausedStore:
        def __getattr__(self, name):
            return getattr(store, name)

        def confirm_check_in(self, *args, **kwargs):
            result = store.confirm_check_in(*args, **kwargs)
            committed.set()
            assert release.wait(10)
            return result

    try:
        with TestClient(main.app) as client, ThreadPoolExecutor(max_workers=1) as executor:
            headers = auth(client)
            created = client.post(f"{PROFILE}/check-ins", json={"text": TEXT}, headers=headers).json()
            path = f"{PROFILE}/check-ins/{created['id']}"
            monkeypatch.setattr(main, "store", PausedStore())
            first = executor.submit(client.post, f"{path}/confirm",
                                    json={"text_revision": 1, "facts": [SAFETY_FACT]}, headers=headers)
            try:
                assert committed.wait(10)
                monkeypatch.setattr(main, "store", other)
                second = client.post(f"{path}/confirm", json={"text_revision": 1, "facts": []}, headers=headers)
                assert second.status_code == 200
            finally:
                release.set()
            result = first.result(timeout=10).json()
            assert result["facts_revision"] == result["facts"][0]["facts_revision"] == 1, {
                "response_revision": result["facts_revision"],
                "fact_revision": result["facts"][0]["facts_revision"],
                "later_revision": second.json()["facts_revision"],
            }
            assert result["confirmed_at"] == result["facts"][0]["confirmed_at"]
            assert result["safety_event"]["text_provenance"][0]["facts_revision"] == 1
            current = client.get(path, headers=headers).json()
            assert current["facts_revision"] == 2 and current["facts"] == []
            assert other.get_check_in("profile-demo", created["id"]).facts_revision == 2
            assert len(other.list_monitoring_events("profile-demo")) == 1
            assert len(other.list_notifications("demo-caregiver")) == 1
    finally:
        monkeypatch.setattr(main, "store", store)
        if url:
            other.engine.dispose()


def test_creation_key_after_precommit_error_and_new_intent(repository):
    store, _ = repository
    with TestClient(main.app) as client:
        headers = auth(client) | {"Idempotency-Key": str(uuid4())}
        invalid = client.post(f"{PROFILE}/check-ins", json={"text": " "}, headers=headers)
        assert invalid.status_code == 422
        assert store.list_check_ins("profile-demo") == []
        first = client.post(f"{PROFILE}/check-ins", json={"text": TEXT}, headers=headers)
        assert first.status_code == 201
        conflict = client.post(f"{PROFILE}/check-ins", json={"text": "Другой текст"}, headers=headers)
        assert conflict.status_code == 409
        assert len(store.list_check_ins("profile-demo")) == 1
        headers["Idempotency-Key"] = str(uuid4())
        intentional = client.post(f"{PROFILE}/check-ins", json={"text": TEXT}, headers=headers)
        assert intentional.status_code == 201
        assert intentional.json()["id"] != first.json()["id"]
        assert len(store.list_check_ins("profile-demo")) == 2
        assert store.list_monitoring_events("profile-demo") == []
        assert store.list_notifications("demo-caregiver") == []


def test_concurrent_creation_key_retries_across_repositories(repository):
    from threading import Barrier
    from app.store import CheckInRecord

    store, url = repository
    other = DatabaseStore(url) if url else store
    key = str(uuid4())
    barrier = Barrier(2)

    def create(repo):
        barrier.wait(10)
        return repo.add_check_in(CheckInRecord(
            uuid4().hex, "profile-demo", TEXT, "manual", NOW, creation_key=key,
        ))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(create, store)
            second = executor.submit(create, other)
            assert first.result(timeout=10).id == second.result(timeout=10).id
        assert len(other.list_check_ins("profile-demo")) == 1
        assert other.list_monitoring_events("profile-demo") == []
    finally:
        if url:
            other.engine.dispose()


def test_demo_replacement_preserves_user_data_and_historical_events(repository):
    store, _ = repository
    with TestClient(main.app) as client:
        headers = auth(client)
        load = lambda **body: client.post("/api/v1/demo/load-scenario", json=body, headers=headers)
        assert load(reset=True, seed=41).status_code == 200
        original = store.list_observations("profile-demo")
        demo_check_in = store.list_check_ins("profile-demo")[0]
        assert load(reset=False, seed=41).status_code == 200
        assert store.list_observations("profile-demo") == original
        assert store.get_check_in("profile-demo", demo_check_in.id) == demo_check_in
        # A fact attached to the old simulated check-in is dependent on that row.
        fact = {"category": "weakness", "polarity": "present", "evidence": "слабость"}
        assert client.post(f"{PROFILE}/check-ins/{demo_check_in.id}/confirm",
                           json={"text_revision": 1, "facts": [fact]}, headers=headers).status_code == 200
        saved = client.post(f"{PROFILE}/check-ins", json={"text": TEXT}, headers=headers).json()
        assert client.post(f"{PROFILE}/check-ins/{saved['id']}/confirm",
                           json={"text_revision": 1, "facts": [SAFETY_FACT]}, headers=headers).status_code == 200
        manual = client.post(f"{PROFILE}/observations", json={
            "metric": "sleep_hours", "value": 5, "unit": "hours", "measured_at": NOW.isoformat(),
        }, headers=headers)
        assert manual.status_code == 201
        old_events = store.list_monitoring_events("profile-demo")
        assert load(reset=False, seed=42).status_code == 200
        assert store.get_check_in("profile-demo", demo_check_in.id) is None
        assert store.list_symptom_facts(demo_check_in.id) == []
        assert store.get_check_in("profile-demo", saved["id"]).is_confirmed
        assert len(store.list_symptom_facts(saved["id"])) == 1
        assert store.list_monitoring_events("profile-demo") == old_events
        assert len(store.list_notifications("demo-caregiver")) == 1
        observations = store.list_observations("profile-demo")
        assert len(observations) == 64 and len(store.list_check_ins("profile-demo")) == 22
        assert manual.json()["id"] in {item.id for item in observations}
        assert not {item.id for item in original} & {item.id for item in observations}
        assert load(reset=True, seed=42).status_code == 200
        assert len(store.list_observations("profile-demo")) == 63
        assert store.get_check_in("profile-demo", saved["id"]) is None
        assert store.list_monitoring_events("profile-demo") == []


def test_demo_insertion_failure_rolls_back_reset_and_replacement(repository):
    import pytest
    from sqlalchemy import event
    from app.db.models import CheckInModel

    store, url = repository
    if url is None:
        pytest.skip("SQL rollback test")
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth(client)
        path = "/api/v1/demo/load-scenario"
        assert client.post(path, json={}, headers=headers).status_code == 200
        client.post(f"{PROFILE}/analysis", headers=headers).raise_for_status()
        before = (store.list_observations("profile-demo"), store.list_check_ins("profile-demo"),
                  store.list_monitoring_events("profile-demo"), store.list_notifications("demo-caregiver"))

        def reject_new_row(*_):
            raise RuntimeError("synthetic insert failure")

        event.listen(CheckInModel, "before_insert", reject_new_row)
        try:
            for reset in (False, True):
                assert client.post(path, json={"seed": 42, "reset": reset}, headers=headers).status_code == 500
                assert (store.list_observations("profile-demo"), store.list_check_ins("profile-demo"),
                        store.list_monitoring_events("profile-demo"), store.list_notifications("demo-caregiver")) == before
        finally:
            event.remove(CheckInModel, "before_insert", reject_new_row)


def test_same_confirmations_across_repositories_share_revision_and_safety_event(repository):
    from threading import Barrier
    from app.ai.gigachat import validate_confirmed_facts

    store, url = repository
    other = DatabaseStore(url) if url else store
    with TestClient(main.app) as client:
        headers = auth(client)
        saved = client.post(f"{PROFILE}/check-ins", json={"text": TEXT}, headers=headers).json()
    barrier = Barrier(2)
    facts = validate_confirmed_facts(TEXT, [SAFETY_FACT])

    def confirm(repo):
        barrier.wait(10)
        return repo.confirm_check_in(
            "profile-demo", saved["id"], corrected_text=None, facts=facts, expected_revision=1,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(confirm, store)
            second = executor.submit(confirm, other)
            result = first.result(timeout=10)
            assert result == second.result(timeout=10)
        assert result.record.facts_revision == 1
        assert result.safety_event.event.text_provenance[0]["fact_id"] == result.facts[0].id
        assert len(other.list_monitoring_events("profile-demo")) == 1
        assert len(other.list_notifications("demo-caregiver")) == 1
        assert other.get_check_in_snapshot("profile-demo", saved["id"]) == (result.record, list(result.facts))
    finally:
        if url:
            other.engine.dispose()


def test_text_edit_after_confirmation_commit_preserves_response_and_history(repository, monkeypatch):
    store, url = repository
    other = DatabaseStore(url) if url else store
    committed, release = Event(), Event()

    class PausedStore:
        def __getattr__(self, name):
            return getattr(store, name)

        def confirm_check_in(self, *args, **kwargs):
            result = store.confirm_check_in(*args, **kwargs)
            committed.set()
            assert release.wait(10)
            return result

    try:
        with TestClient(main.app) as client, ThreadPoolExecutor(max_workers=1) as executor:
            headers = auth(client)
            saved = client.post(f"{PROFILE}/check-ins", json={"text": TEXT}, headers=headers).json()
            path = f"{PROFILE}/check-ins/{saved['id']}"
            monkeypatch.setattr(main, "store", PausedStore())
            pending = executor.submit(client.post, f"{path}/confirm",
                                      json={"text_revision": 1, "facts": [SAFETY_FACT]}, headers=headers)
            try:
                assert committed.wait(10)
                assert other.update_check_in_text("profile-demo", saved["id"], "Уточнение.",
                                                  expected_revision=1).text_revision == 2
            finally:
                release.set()
            response = pending.result(timeout=10)
            assert response.status_code == 200
            result = response.json()
            assert result["text_revision"] == result["safety_event"]["text_provenance"][0]["text_revision"] == 1
            assert result["facts_revision"] == result["facts"][0]["facts_revision"] == 1
            get = client.get(path, headers=headers).json()
            assert get["text_revision"] == 2 and get["facts"] == [] and get["confirmed_at"] is None
            assert client.post(f"{path}/confirm", json={"text_revision": 1, "facts": [SAFETY_FACT]},
                               headers=headers).status_code == 409
            assert len(other.list_monitoring_events("profile-demo")) == 1
            assert len(other.list_notifications("demo-caregiver")) == 1
    finally:
        monkeypatch.setattr(main, "store", store)
        if url:
            other.engine.dispose()


def test_save_retry_with_same_payload_after_precommit_failure(repository):
    import pytest
    from sqlalchemy import event
    from app.db.models import CheckInModel

    store, url = repository
    if url is None:
        pytest.skip("SQL rollback test")
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth(client) | {"Idempotency-Key": str(uuid4())}
        path = f"{PROFILE}/check-ins"

        def reject_insert(*_):
            raise RuntimeError("synthetic failure before commit")

        event.listen(CheckInModel, "before_insert", reject_insert)
        try:
            assert client.post(path, json={"text": TEXT}, headers=headers).status_code == 500
            assert store.list_check_ins("profile-demo") == []
        finally:
            event.remove(CheckInModel, "before_insert", reject_insert)
        response = client.post(path, json={"text": TEXT}, headers=headers)
        assert response.status_code == 201
        assert [item.id for item in store.list_check_ins("profile-demo")] == [response.json()["id"]]


def test_failed_safety_notification_rolls_back_confirmation(repository):
    import pytest
    from sqlalchemy import event
    from app.db.models import NotificationModel

    store, url = repository
    if url is None:
        pytest.skip("SQL rollback test")
    with TestClient(main.app, raise_server_exceptions=False) as client:
        headers = auth(client)
        created = client.post(f"{PROFILE}/check-ins", json={"text": TEXT}, headers=headers).json()
        path = f"{PROFILE}/check-ins/{created['id']}"
        payload = {"text_revision": 1, "facts": [SAFETY_FACT]}

        def reject_notification(*_):
            raise RuntimeError("synthetic notification failure")

        event.listen(NotificationModel, "before_insert", reject_notification)
        try:
            assert client.post(f"{path}/confirm", json=payload, headers=headers).status_code == 500
            assert client.get(path, headers=headers).json() == created
            assert store.list_monitoring_events("profile-demo") == []
            assert store.list_notifications("demo-caregiver") == []
        finally:
            event.remove(NotificationModel, "before_insert", reject_notification)
        assert client.post(f"{path}/confirm", json=payload, headers=headers).json()["facts_revision"] == 1
        assert len(store.list_monitoring_events("profile-demo")) == 1
        assert len(store.list_notifications("demo-caregiver")) == 1
