from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app import main
from app.auth import UserContext, authenticate, issue_token
from app.domain.monitoring import Metric, SymptomFact
from app.schemas import (
    CheckInConfirmRequest,
    CheckInCorrectionRequest,
    CheckInCreate,
    DemoLoadRequest,
    LoginRequest,
    ObservationCreate,
)
from app.store import InMemoryStore


class _FakeExtractionProvider:
    calls = 0

    def __init__(self, settings) -> None:
        self.settings = settings

    def extract_facts(self, text: str) -> list[SymptomFact]:
        type(self).calls += 1
        return [
            SymptomFact(
                category="weakness",
                polarity="present",
                evidence="чувствую слабость",
                confirmed=False,
            )
        ]

    def close(self) -> None:
        return None


class ApiIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.previous_store = main.store
        main.store = InMemoryStore()
        _FakeExtractionProvider.calls = 0
        self.user = UserContext("demo-user", "user", "profile-demo")
        self.caregiver = UserContext("demo-caregiver", "caregiver", "profile-demo")

    def tearDown(self) -> None:
        main.store = self.previous_store

    def test_full_api_scenario_and_safety_are_integrated(self) -> None:
        login = main.login(LoginRequest(user_id="demo-user", password="demo-user"))
        self.assertEqual(login.user.user_id, self.user.user_id)
        self.assertTrue(issue_token(authenticate("demo-user", "demo-user")))

        loaded = main.load_demo_scenario(
            DemoLoadRequest(seed=20261110, days=21, reset=True), self.user
        )
        self.assertEqual((loaded.observation_count, loaded.check_in_count), (63, 21))
        self.assertEqual(len(main.list_observations("profile-demo", self.user)), 63)
        self.assertEqual(len(main.list_check_ins("profile-demo", self.user)), 21)
        self.assertEqual(
            len(main.trends("profile-demo", self.user, metric=Metric.SLEEP_HOURS, days=28)),
            21,
        )

        check_in = main.create_check_in(
            "profile-demo",
            CheckInCreate(text="Сегодня чувствую слабость"),
            self.user,
        )
        with (
            patch.object(main, "GigaChatProvider", _FakeExtractionProvider),
            patch.object(main.GigaChatSettings, "from_env", return_value=object()),
        ):
            extracted = main.extract_check_in_facts("profile-demo", check_in.id, self.user)
            self.assertEqual(extracted.status, "awaiting_confirmation")
            self.assertEqual(_FakeExtractionProvider.calls, 1)
            self.assertEqual(main.store.list_monitoring_events("profile-demo"), [])

            corrected = main.correct_check_in(
                "profile-demo",
                check_in.id,
                CheckInCorrectionRequest(corrected_text="Сегодня чувствую слабость"),
                self.user,
            )
            self.assertEqual(corrected.corrected_text, "Сегодня чувствую слабость")
            confirmed = main.confirm_check_in_facts(
                "profile-demo",
                check_in.id,
                CheckInConfirmRequest(
                    corrected_text="Сегодня чувствую слабость",
                    facts=[{
                        "category": "weakness",
                        "polarity": "present",
                        "evidence": "чувствую слабость",
                    }],
                ),
                self.user,
            )
            self.assertIsNone(confirmed.safety_event)
            self.assertEqual(_FakeExtractionProvider.calls, 1)

            safety_check_in = main.create_check_in(
                "profile-demo",
                CheckInCreate(text="У меня сильная боль в груди"),
                self.user,
            )
            safety = main.confirm_check_in_facts(
                "profile-demo",
                safety_check_in.id,
                CheckInConfirmRequest(facts=[{
                    "category": "chest_pain",
                    "polarity": "present",
                    "evidence": "сильная боль в груди",
                }]),
                self.user,
            )
            self.assertIsNotNone(safety.safety_event)
            self.assertEqual(_FakeExtractionProvider.calls, 1)

        # A caregiver cannot add observations, while a user can add a valid one.
        with self.assertRaises(HTTPException) as forbidden:
            main.create_observation(
                "profile-demo",
                ObservationCreate(
                    metric=Metric.PULSE_BPM,
                    value=70,
                    unit="bpm",
                    measured_at=datetime.now(timezone.utc),
                ),
                self.caregiver,
            )
        self.assertEqual(forbidden.exception.status_code, 403)
        main.create_observation(
            "profile-demo",
            ObservationCreate(
                metric=Metric.SLEEP_HOURS,
                value=5,
                unit="hours",
                measured_at=datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
            ),
            self.user,
        )
        pressure_time = datetime(2026, 10, 22, 11, tzinfo=timezone.utc)
        main.create_observation(
            "profile-demo",
            ObservationCreate(
                metric=Metric.SYSTOLIC_BP,
                value=80,
                unit="mmHg",
                measured_at=pressure_time,
            ),
            self.user,
        )
        with self.assertRaises(HTTPException) as invalid_pressure:
            main.create_observation(
                "profile-demo",
                ObservationCreate(
                    metric=Metric.DIASTOLIC_BP,
                    value=120,
                    unit="mmHg",
                    measured_at=pressure_time,
                ),
                self.user,
            )
        self.assertEqual(invalid_pressure.exception.status_code, 422)
        # Demo dates are fixed in October: request an explicit historical snapshot.
        analysis = main.analyze_profile(
            "profile-demo", self.user, as_of=datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(analysis.status.value, "attention")
        self.assertGreaterEqual(len(main.store.list_monitoring_events("profile-demo")), 2)

        caregiver_summary = main.caregiver_summary("profile-demo", self.caregiver)
        self.assertTrue(any(item.level == "safety" for item in caregiver_summary.events))
        self.assertTrue(caregiver_summary.notifications)
        unread = caregiver_summary.notifications[0]
        read = main.mark_notification_read(unread.id, self.caregiver)
        self.assertEqual(read.status, "read")

        reloaded = main.load_demo_scenario(
            DemoLoadRequest(seed=20261110, days=21, reset=True), self.user
        )
        self.assertEqual(reloaded, loaded)
        self.assertEqual(main.store.list_monitoring_events("profile-demo"), [])
        self.assertEqual(main.store.list_notifications("demo-caregiver"), [])
