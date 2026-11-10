from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from unittest import TestCase

from sqlalchemy import create_engine

from app.db.base import Base
from app.db.repository import DatabaseStore
from app.domain.monitoring import Metric, MonitoringEvent, MonitoringStatus, Observation, SymptomFact
from app.store import CheckInRecord


class DatabaseRepositoryTests(TestCase):
    def test_observation_and_check_in_round_trip_preserves_utc(self) -> None:
        with TemporaryDirectory() as directory:
            database_url = f"sqlite:///{directory}/medsi-care.db"
            engine = create_engine(database_url)
            Base.metadata.create_all(engine)
            store = DatabaseStore(database_url)
            measured_at = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
            observation = Observation(
                id="obs-db-1",
                profile_id="profile-demo",
                metric=Metric.SLEEP_HOURS,
                value=8.0,
                unit="hours",
                measured_at=measured_at,
                quality="good",
            )
            check_in = CheckInRecord(
                id="checkin-db-1",
                profile_id="profile-demo",
                text="Сегодня чувствую себя обычно",
                source="manual",
                created_at=measured_at,
            )

            store.add_observation(observation)
            store.add_check_in(check_in)

            self.assertEqual(store.list_observations("profile-demo"), [observation])
            self.assertEqual(store.list_check_ins("profile-demo"), [check_in])
            corrected = store.update_check_in_text(
                "profile-demo", check_in.id, "Исправленный текст о слабости", expected_revision=1
            )
            self.assertEqual(corrected.corrected_text, "Исправленный текст о слабости")
            self.assertEqual(store.list_symptom_facts(check_in.id), [])

            facts = [
                SymptomFact(
                    category="weakness",
                    polarity="present",
                    evidence="чувствую слабость",
                    confirmed=True,
                    temporal_context="сегодня",
                    confidence=0.9,
                )
            ]
            saved_facts = store.confirm_check_in(
                "profile-demo",
                check_in.id,
                corrected_text=corrected.corrected_text,
                expected_revision=corrected.text_revision,
                facts=facts,
            )
            self.assertEqual(store.list_symptom_facts(check_in.id), saved_facts)
            self.assertEqual(saved_facts[0].category, facts[0].category)
            self.assertTrue(saved_facts[0].id)
            self.assertEqual(store.get_check_in("profile-demo", check_in.id).corrected_text, corrected.corrected_text)

            event = MonitoringEvent(
                status=MonitoringStatus.ATTENTION,
                metric=Metric.SLEEP_HOURS,
                z_score=-3.1,
                evidence=("sleep_hours=5 hours", "baseline=8 hours"),
                message="Обнаружено изменение.",
                level="attention",
                source_observation_ids=(observation.id,),
                period_start=measured_at,
                period_end=measured_at,
            )
            saved_event = store.save_monitoring_event("profile-demo", event)
            self.assertEqual(store.list_monitoring_events("profile-demo")[0].event, event)
            notifications = store.list_notifications("demo-caregiver")
            self.assertEqual(len(notifications), 1)
            marked = store.mark_notification_read(notifications[0].id, "demo-caregiver")
            self.assertEqual(marked.status, "read")

            safety_event = MonitoringEvent(
                status=MonitoringStatus.SAFETY,
                metric=None,
                z_score=None,
                evidence=("chest_pain: боль в груди",),
                message="Обратитесь за экстренной медицинской помощью.",
                algorithm_version="safety-v1",
                level="safety",
                period_start=measured_at,
                period_end=measured_at,
            )
            store.save_monitoring_event("profile-demo", safety_event)
            saved_events = store.list_monitoring_events("profile-demo")
            self.assertEqual(saved_events[0].event.status, MonitoringStatus.SAFETY)
            self.assertEqual(len(store.list_notifications("demo-caregiver")), 2)
