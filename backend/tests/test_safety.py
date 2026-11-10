from datetime import datetime, timezone
from unittest import TestCase

from app.domain.monitoring import MonitoringEvent, MonitoringStatus, SymptomFact
from app.safety import SAFETY_RULE_VERSION, evaluate_safety
from app.store import CheckInRecord, InMemoryStore


class SafetyRuleTests(TestCase):
    def test_confirmed_urgent_fact_creates_deterministic_decision(self) -> None:
        decision = evaluate_safety([
            SymptomFact(
                category="chest_pain",
                polarity="present",
                evidence="сильная боль в груди",
                confirmed=True,
            )
        ])
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.rule_version, SAFETY_RULE_VERSION)
        self.assertEqual(decision.level, "safety")
        self.assertIn("срочной медицинской оценки", decision.message)
        self.assertEqual(decision.evidence, ("chest_pain: сильная боль в груди",))

    def test_unconfirmed_and_ordinary_facts_do_not_create_safety(self) -> None:
        self.assertIsNone(evaluate_safety([
            SymptomFact(category="chest_pain", polarity="present", evidence="боль", confirmed=False)
        ]))
        self.assertIsNone(evaluate_safety([
            SymptomFact(category="weakness", polarity="present", evidence="слабость", confirmed=True)
        ]))

    def test_safety_event_creates_caregiver_notification(self) -> None:
        store = InMemoryStore()
        event = MonitoringEvent(
            status=MonitoringStatus.SAFETY,
            metric=None,
            z_score=None,
            evidence=("chest_pain: боль в груди",),
            message="Обратитесь за экстренной медицинской помощью.",
            algorithm_version=SAFETY_RULE_VERSION,
            level="safety",
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc),
        )
        store.save_monitoring_event("profile-demo", event)
        notifications = store.list_notifications("demo-caregiver")
        self.assertEqual(len(notifications), 1)
        self.assertEqual(store.list_monitoring_events("profile-demo")[0].event.status, MonitoringStatus.SAFETY)

    def test_confirm_endpoint_persists_safety_without_llm(self) -> None:
        from app import main
        from app.auth import UserContext
        from app.schemas import CheckInConfirmRequest

        main.store = InMemoryStore()
        check_in = main.store.add_check_in(
            CheckInRecord(
                id="checkin-safety-test",
                profile_id="profile-demo",
                text="У меня сильная боль в груди",
                source="manual",
                created_at=datetime.now(timezone.utc),
            )
        )
        response = main.confirm_check_in_facts(
            "profile-demo",
            check_in.id,
            CheckInConfirmRequest(text_revision=1,
                facts=[{
                    "category": "chest_pain",
                    "polarity": "present",
                    "evidence": "сильная боль в груди",
                }]
            ),
            UserContext("demo-user", "user", "profile-demo"),
        )
        self.assertIsNotNone(response.safety_event)
        assert response.safety_event is not None
        self.assertEqual(response.safety_event.status, MonitoringStatus.SAFETY)
        self.assertEqual(len(main.store.list_notifications("demo-caregiver")), 1)
