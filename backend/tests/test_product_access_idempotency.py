"""Behavioral F6/F7 regressions shared by memory, SQLite and live PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.domain.monitoring import Metric, Observation
from tests.test_fact_lifecycle import NOW, USER, clock, repository  # noqa: F401


def client_for(role="demo-user"):
    client = TestClient(main.app)
    login = client.post("/api/v1/auth/login", json={"user_id": role, "password": role})
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    return client


def changed_sleep(store, id="changed"):
    store.add_observation(Observation(id, "profile-demo", Metric.SLEEP_HOURS, 4, "hours", NOW))


def snapshot(store):
    return (store.list_observations("profile-demo"), store.list_check_ins("profile-demo"),
            store.list_monitoring_events("profile-demo"),
            store.list_notifications("demo-user"), store.list_notifications("demo-caregiver"),
            [(check.id, store.list_symptom_facts(check.id)) for check in store.list_check_ins("profile-demo")])


def test_f6_caregiver_analysis_has_no_write_side_effects(repository):
    store, _ = repository
    changed_sleep(store)
    before = snapshot(store)
    with client_for("demo-caregiver") as client:
        response = client.post("/api/v1/profiles/profile-demo/analysis")
    assert snapshot(store) == before
    assert response.status_code == 403


def test_f7_repeat_analysis_reuses_event_and_read_notification(repository):
    store, _ = repository
    changed_sleep(store)
    with client_for() as client:
        first = client.post("/api/v1/profiles/profile-demo/analysis").json()
        notification = store.list_notifications("demo-caregiver")[0]
        store.mark_notification_read(notification.id, "demo-caregiver")
        read = store.list_notifications("demo-caregiver")
        with patch.object(main, "datetime", clock(NOW + timedelta(seconds=5))):
            second = client.post("/api/v1/profiles/profile-demo/analysis").json()
    assert len(store.list_monitoring_events("profile-demo")) == 1
    assert store.list_notifications("demo-caregiver") == read
    assert second == first


def test_f7_concurrent_analysis_creates_one_event(repository):
    store, _ = repository
    changed_sleep(store)
    barrier = Barrier(6)
    def analyze(_):
        barrier.wait(timeout=10)
        return main.analyze_profile("profile-demo", USER).model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(analyze, range(6)))
    assert len(store.list_monitoring_events("profile-demo")) == 1
    assert len(store.list_notifications("demo-caregiver")) == 1
    assert all(result == results[0] for result in results)


def test_f7_safety_confirmation_is_noop_for_same_fact_set(repository):
    store, _ = repository
    with client_for() as client:
        check = client.post("/api/v1/profiles/profile-demo/check-ins", json={"text": "Боль в груди"}).json()
        path = f"/api/v1/profiles/profile-demo/check-ins/{check['id']}/confirm"
        payload = {"text_revision": 1, "facts": [{"category": "chest_pain", "polarity": "present", "evidence": "Боль в груди"}]}
        first = client.post(path, json=payload).json()
        notification = store.list_notifications("demo-caregiver")[0]
        store.mark_notification_read(notification.id, "demo-caregiver")
        before = snapshot(store)
        with patch("app.store.datetime", clock(NOW + timedelta(seconds=5))), patch(
            "app.db.repository.datetime", clock(NOW + timedelta(seconds=5))
        ), patch.object(main, "datetime", clock(NOW + timedelta(seconds=5))):
            second = client.post(path, json=payload).json()
    assert snapshot(store) == before
    assert second == first


def test_f6_all_write_routes_denied_and_read_routes_preserved(repository):
    store, _ = repository
    changed_sleep(store)
    with client_for() as owner:
        check = owner.post("/api/v1/profiles/profile-demo/check-ins", json={"text": "Боль в груди"}).json()
        path = f"/api/v1/profiles/profile-demo/check-ins/{check['id']}"
        owner.post(path + "/confirm", json={"text_revision": 1, "facts": [
            {"category": "chest_pain", "polarity": "present", "evidence": "Боль в груди"}]})
        owner.post("/api/v1/profiles/profile-demo/analysis")
    before = snapshot(store)
    with client_for("demo-caregiver") as client:
        writes = [
            ("post", "/api/v1/profiles/profile-demo/analysis", None),
            ("post", "/api/v1/demo/load-scenario", {"reset": True}),
            ("post", "/api/v1/profiles/profile-demo/observations", {"metric": "sleep_hours", "value": 8, "unit": "hours", "measured_at": NOW.isoformat()}),
            ("post", "/api/v1/profiles/profile-demo/check-ins", {"text": "Слабость"}),
            ("patch", path, {"text_revision": 1, "corrected_text": "Другой текст"}),
            ("post", path + "/extract", None),
            ("post", path + "/confirm", {"text_revision": 1, "facts": []}),
        ]
        for method, route, body in writes:
            assert getattr(client, method)(route, json=body).status_code == 403
            assert snapshot(store) == before
        audio = client.post("/api/v1/profiles/profile-demo/audio/transcriptions", files={"audio": ("synthetic.wav", b"synthetic", "audio/wav")})
        assert audio.status_code == 403
        for route in ["/api/v1/caregiver/profiles/profile-demo/summary", "/api/v1/notifications",
                      "/api/v1/profiles/profile-demo", "/api/v1/profiles/profile-demo/trends",
                      "/api/v1/profiles/profile-demo/events", "/api/v1/profiles/profile-demo/observations",
                      "/api/v1/profiles/profile-demo/check-ins", path]:
            assert client.get(route).status_code == 200
            assert snapshot(store) == before
        other = store.list_notifications("demo-user")[0]
        assert client.post(f"/api/v1/notifications/{other.id}/read").status_code == 404
        assert snapshot(store) == before
        own = store.list_notifications("demo-caregiver")[0]
        assert client.post(f"/api/v1/notifications/{own.id}/read").json()["status"] == "read"
        assert len(store.list_monitoring_events("profile-demo")) == 2
        assert store.list_notifications("demo-user") == before[3]


def test_f7_new_observation_and_new_local_day_are_not_suppressed(repository):
    store, _ = repository
    changed_sleep(store)
    first = main.analyze_profile("profile-demo", USER)
    changed_sleep(store, "changed-again")
    second = main.analyze_profile("profile-demo", USER)
    assert first.event_id != second.event_id
    assert len(store.list_monitoring_events("profile-demo")) == 2
    with patch.object(main, "datetime", clock(NOW + timedelta(days=1))):
        third = main.analyze_profile("profile-demo", USER)
        again = main.analyze_profile("profile-demo", USER)
    assert third.event_id not in {first.event_id, second.event_id}
    assert third == again
    assert len(store.list_monitoring_events("profile-demo")) == 3


def test_f7_concurrent_safety_confirmation_creates_one_revision_and_notification(repository):
    store, _ = repository
    from app.schemas import CheckInConfirmRequest, CheckInCreate
    check = main.create_check_in("profile-demo", CheckInCreate(text="Боль в груди"), USER)
    payload = CheckInConfirmRequest(text_revision=1, facts=[{
        "category": "chest_pain", "polarity": "present", "evidence": "Боль в груди",
    }])
    barrier = Barrier(6)
    def confirm(_):
        barrier.wait(timeout=10)
        return main.confirm_check_in_facts("profile-demo", check.id, payload, USER).model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(confirm, range(6)))
    assert all(result == results[0] for result in results)
    assert store.get_check_in("profile-demo", check.id).facts_revision == 1
    assert len(store.list_symptom_facts(check.id)) == 1
    assert len(store.list_monitoring_events("profile-demo")) == 1
    assert len(store.list_notifications("demo-caregiver")) == 1


def test_f7_fact_order_is_irrelevant_but_new_fact_revision_can_alert_again(repository):
    store, _ = repository
    with client_for() as client:
        check = client.post("/api/v1/profiles/profile-demo/check-ins", json={"text": "Боль в груди и слабость"}).json()
        path = f"/api/v1/profiles/profile-demo/check-ins/{check['id']}/confirm"
        urgent = {"category": "chest_pain", "polarity": "present", "evidence": "Боль в груди"}
        ordinary = {"category": "weakness", "polarity": "present", "evidence": "слабость"}
        first = client.post(path, json={"text_revision": 1, "facts": [urgent, ordinary]}).json()
        reordered = client.post(path, json={"text_revision": 1, "facts": [ordinary, urgent]}).json()
        assert first == reordered
        assert first["facts_revision"] == 1
        assert len(store.list_monitoring_events("profile-demo")) == 1
        absent = client.post(path, json={"text_revision": 1, "facts": [{**urgent, "polarity": "absent"}]}).json()
        assert absent["facts_revision"] == 2
        assert absent["safety_event"] is None
        again = client.post(path, json={"text_revision": 1, "facts": [urgent, ordinary]}).json()
        assert again["facts_revision"] == 3
        assert again["safety_event"]["id"] != first["safety_event"]["id"]
        assert len(store.list_monitoring_events("profile-demo")) == 2
        assert len(store.list_notifications("demo-caregiver")) == 2


def test_f7_rule_version_is_part_of_identity(repository):
    from dataclasses import replace
    store, _ = repository
    changed_sleep(store)
    _, event = main._analysis_for_profile("profile-demo")
    first = store.save_monitoring_event("profile-demo", event)
    updated = store.save_monitoring_event("profile-demo", replace(event, algorithm_version="synthetic-test-new-rules"))
    assert first.id != updated.id
    assert len(store.list_monitoring_events("profile-demo")) == 2


def test_f7_independent_sql_repositories_use_database_uniqueness(repository):
    import pytest
    from sqlalchemy import insert, select
    from sqlalchemy.exc import IntegrityError
    from app.db.models import MonitoringEventModel
    from app.db.repository import DatabaseStore
    store, url = repository
    if not url:
        pytest.skip("SQL constraint test; memory has a process-local lock")
    changed_sleep(store)
    _, event = main._analysis_for_profile("profile-demo")
    repositories = [DatabaseStore(url) for _ in range(6)]
    barrier = Barrier(6)
    def save(repo):
        barrier.wait(timeout=10)
        return repo.save_monitoring_event("profile-demo", event)
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            records = list(pool.map(save, repositories))
        assert len({record.id for record in records}) == 1
        assert len(store.list_monitoring_events("profile-demo")) == 1
        assert len(store.list_notifications("demo-caregiver")) == 1
        with store.engine.connect() as connection:
            values = dict(connection.execute(select(MonitoringEventModel.__table__)).mappings().one())
        values["id"] = "forced-duplicate-identity"
        with pytest.raises(IntegrityError), store.engine.begin() as connection:
            connection.execute(insert(MonitoringEventModel).values(**values))
        assert len(store.list_monitoring_events("profile-demo")) == 1
    finally:
        for repo in repositories:
            repo.engine.dispose()


def test_f7_event_and_notifications_rollback_together(repository):
    import pytest
    from sqlalchemy import event as sql_event
    from app.db.models import NotificationModel
    store, url = repository
    if not url:
        pytest.skip("SQL transaction rollback test")
    changed_sleep(store)
    _, event = main._analysis_for_profile("profile-demo")
    def fail_notification(session, flush_context, instances):
        if any(isinstance(row, NotificationModel) for row in session.new):
            raise RuntimeError("synthetic notification write failure")
    sql_event.listen(store.session_factory, "before_flush", fail_notification)
    try:
        with pytest.raises(RuntimeError, match="synthetic notification"):
            store.save_monitoring_event("profile-demo", event)
    finally:
        sql_event.remove(store.session_factory, "before_flush", fail_notification)
    assert store.list_monitoring_events("profile-demo") == []
    assert store.list_notifications("demo-user") == []
    assert store.list_notifications("demo-caregiver") == []
    store.save_monitoring_event("profile-demo", event)
    assert len(store.list_monitoring_events("profile-demo")) == 1
    assert len(store.list_notifications("demo-caregiver")) == 1


def test_f8_failed_extraction_then_explicit_manual_safety_confirmation(repository, monkeypatch):
    store, _ = repository
    monkeypatch.delenv("GIGACHAT_AUTH_KEY", raising=False)
    with client_for() as owner:
        check = owner.post("/api/v1/profiles/profile-demo/check-ins", json={"text": "Боль в груди"}).json()
        path = f"/api/v1/profiles/profile-demo/check-ins/{check['id']}"
        before = snapshot(store)
        assert owner.post(path + "/extract").status_code == 503
        assert snapshot(store) == before
        invalid = {"text_revision": 1, "facts": [{"category": "chest_pain", "polarity": "present", "evidence": "Вымышленная цитата"}]}
        assert owner.post(path + "/confirm", json=invalid).status_code == 422
        assert snapshot(store) == before
        manual = {"text_revision": 1, "facts": [{"category": "chest_pain", "polarity": "present", "evidence": "Боль в груди"}]}
        response = owner.post(path + "/confirm", json=manual)
        assert response.status_code == 200
        event = response.json()["safety_event"]
        assert event["text_provenance"][0]["text_revision"] == 1
        assert event["text_provenance"][0]["facts_revision"] == 1
        assert event["text_provenance"][0]["evidence"] == "Боль в груди"
        assert len(store.list_monitoring_events("profile-demo")) == 1
    with client_for("demo-caregiver") as caregiver:
        summary = caregiver.get("/api/v1/caregiver/profiles/profile-demo/summary").json()
        assert summary["events"][0]["id"] == event["id"]
        assert summary["notifications"][0]["event_id"] == event["id"]


def test_f7_fact_expiry_changes_result_without_waiting_for_new_day(repository):
    from tests.test_fact_lifecycle import confirmed
    store, _ = repository
    confirmed(store, "expires", NOW - timedelta(hours=23))
    first = main.analyze_profile("profile-demo", USER)
    assert first.status.value == "attention"
    with patch.object(main, "datetime", clock(NOW + timedelta(hours=2))):
        expired = main.analyze_profile("profile-demo", USER)
        repeated = main.analyze_profile("profile-demo", USER)
    assert expired.status.value == "no_change"
    assert expired.event_id != first.event_id
    assert expired == repeated
    assert expired.text_provenance == []
    assert len(store.list_monitoring_events("profile-demo")) == 2


def test_f7_safety_new_text_revision_is_a_new_confirmation_episode(repository):
    store, _ = repository
    with client_for() as client:
        check = client.post("/api/v1/profiles/profile-demo/check-ins", json={"text": "Боль в груди"}).json()
        path = f"/api/v1/profiles/profile-demo/check-ins/{check['id']}"
        fact = {"category": "chest_pain", "polarity": "present", "evidence": "Боль в груди"}
        first = client.post(path + "/confirm", json={"text_revision": 1, "facts": [fact]}).json()
        assert client.patch(path, json={"text_revision": 1, "corrected_text": "Боль в груди снова"}).status_code == 200
        second = client.post(path + "/confirm", json={"text_revision": 2, "facts": [fact]}).json()
        assert second["safety_event"]["id"] != first["safety_event"]["id"]
        assert second["safety_event"]["text_provenance"][0]["text_revision"] == 2
        assert len(store.list_monitoring_events("profile-demo")) == 2
        assert len(store.list_notifications("demo-caregiver")) == 2
