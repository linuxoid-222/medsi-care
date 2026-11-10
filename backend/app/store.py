"""Small in-memory repository used by the first vertical slice.

The repository boundary is intentional: PostgreSQL/SQLAlchemy can replace this
implementation without changing the API or monitoring domain logic.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4
from threading import RLock

from app.event_identity import event_identity, fact_content

from app.facts import TextRevisionConflict, fact_provenance
from app.safety import evaluate_safety

from app.domain.monitoring import MonitoringEvent, MonitoringStatus, Observation, SymptomFact


@dataclass(frozen=True, slots=True)
class CheckInRecord:
    id: str
    profile_id: str
    text: str
    source: str
    created_at: datetime
    corrected_text: str | None = None
    text_revision: int = 1
    facts_revision: int = 0
    confirmed_revision: int | None = None
    confirmed_at: datetime | None = None
    creation_key: str | None = None

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_revision == self.text_revision


@dataclass(frozen=True, slots=True)
class MonitoringEventRecord:
    id: str
    profile_id: str
    event: MonitoringEvent
    created_at: datetime
    identity_key: str | None = None


class CheckInCreationConflict(ValueError):
    """A creation key was reused with a different original payload."""


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    record: CheckInRecord
    facts: tuple[SymptomFact, ...]
    safety_event: MonitoringEventRecord | None


def confirmation_safety_event(record: CheckInRecord, facts: tuple[SymptomFact, ...]) -> MonitoringEvent | None:
    decision = evaluate_safety(facts)
    if decision is None:
        return None
    return MonitoringEvent(
        status=MonitoringStatus.SAFETY, metric=None, z_score=None,
        evidence=decision.evidence, message=decision.message,
        algorithm_version=decision.rule_version, level=decision.level,
        period_start=record.created_at, period_end=record.confirmed_at,
        text_provenance=tuple(
            fact_provenance(fact, rule_version=decision.rule_version, resolution="direct_confirmation")
            for fact in decision.facts
        ),
    )


@dataclass(frozen=True, slots=True)
class NotificationRecord:
    id: str
    event_id: str
    recipient_id: str
    status: str
    read_at: datetime | None
    created_at: datetime


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self.profile_timezones = {"profile-demo": "Europe/Moscow"}
        self.observations: list[Observation] = []
        self.check_ins: list[CheckInRecord] = []
        self.symptom_facts: dict[str, list[SymptomFact]] = {}
        self.monitoring_events: list[MonitoringEventRecord] = []
        self.notifications: list[NotificationRecord] = []

    def add_observation(self, observation: Observation) -> Observation:
        with self._lock:
            self.observations.append(observation)
        return observation

    def get_profile_timezone(self, profile_id: str) -> str:
        return self.profile_timezones[profile_id]

    def list_observations(self, profile_id: str) -> list[Observation]:
        with self._lock:
            return sorted(
                [item for item in self.observations if item.profile_id == profile_id],
                key=lambda item: item.measured_at,
            )

    def add_check_in(self, check_in: CheckInRecord) -> CheckInRecord:
        with self._lock:
            if check_in.creation_key is not None:
                for record in self.check_ins:
                    if (record.profile_id, record.creation_key) == (check_in.profile_id, check_in.creation_key):
                        if (record.text, record.source) != (check_in.text, check_in.source):
                            raise CheckInCreationConflict()
                        return record
            self.check_ins.append(check_in)
            return check_in

    def list_check_ins(self, profile_id: str) -> list[CheckInRecord]:
        with self._lock:
            return sorted(
                [item for item in self.check_ins if item.profile_id == profile_id],
                key=lambda item: item.created_at,
                reverse=True,
            )

    def get_check_in(self, profile_id: str, check_in_id: str) -> CheckInRecord | None:
        with self._lock:
            return next(
                (
                    item
                    for item in self.check_ins
                    if item.profile_id == profile_id and item.id == check_in_id
                ),
                None,
            )

    def get_check_in_snapshot(self, profile_id: str, check_in_id: str):
        with self._lock:
            record = self.get_check_in(profile_id, check_in_id)
            return (record, self.list_symptom_facts(check_in_id)) if record else None

    def list_check_in_snapshots(self, profile_id: str):
        with self._lock:
            return [(record, self.list_symptom_facts(record.id))
                    for record in self.list_check_ins(profile_id)]

    def update_check_in_text(
        self, profile_id: str, check_in_id: str, corrected_text: str, *, expected_revision: int,
    ) -> CheckInRecord | None:
        with self._lock:
            check_in = self.get_check_in(profile_id, check_in_id)
            if check_in is None:
                return None
            if check_in.text_revision != expected_revision:
                raise TextRevisionConflict()
            changed = corrected_text != (check_in.corrected_text or check_in.text)
            replacement = replace(
                check_in, corrected_text=corrected_text,
                text_revision=check_in.text_revision + int(changed),
                confirmed_revision=None if changed else check_in.confirmed_revision,
                confirmed_at=None if changed else check_in.confirmed_at,
            )
            self.check_ins = [replacement if item.id == check_in_id else item for item in self.check_ins]
            if changed:
                self.symptom_facts.pop(check_in_id, None)
            return replacement

    def confirm_check_in(
        self, profile_id: str, check_in_id: str, *, corrected_text: str | None,
        facts: list[SymptomFact], expected_revision: int,
    ) -> ConfirmationResult:
        with self._lock:
            check_in = self.get_check_in(profile_id, check_in_id)
            if check_in is None:
                raise KeyError(check_in_id)
            if check_in.text_revision != expected_revision or (
                corrected_text is not None and corrected_text != (check_in.corrected_text or check_in.text)
            ):
                raise TextRevisionConflict()
            current = self.list_symptom_facts(check_in_id)
            if check_in.is_confirmed and fact_content(current) == fact_content(facts):
                return self._confirmation_result(check_in, tuple(current))
            now = datetime.now(timezone.utc)
            facts_revision = check_in.facts_revision + 1
            replacement = replace(check_in, confirmed_revision=expected_revision, confirmed_at=now,
                                  facts_revision=facts_revision)
            saved = [replace(fact, id=f"fact-{uuid4().hex}", check_in_id=check_in.id,
                             text_revision=expected_revision, facts_revision=facts_revision,
                             recorded_at=check_in.created_at,
                             confirmed_at=now, confirmed=True) for fact in facts]
            saved.sort(key=lambda fact: fact.id)
            result = self._confirmation_result(replacement, tuple(saved))
            self.check_ins = [replacement if item.id == check_in_id else item for item in self.check_ins]
            self.symptom_facts[check_in_id] = saved
            return result

    def _confirmation_result(self, record: CheckInRecord, facts: tuple[SymptomFact, ...]) -> ConfirmationResult:
        event = confirmation_safety_event(record, facts)
        saved = self.save_monitoring_event(record.profile_id, event) if event else None
        return ConfirmationResult(record, facts, saved)

    def list_symptom_facts(self, check_in_id: str) -> list[SymptomFact]:
        with self._lock:
            check_in = next((item for item in self.check_ins if item.id == check_in_id), None)
            if check_in is None or not check_in.is_confirmed:
                return []
            return [fact for fact in self.symptom_facts.get(check_in_id, [])
                    if fact.confirmed and fact.text_revision == check_in.text_revision]

    def save_monitoring_event(self, profile_id: str, event: MonitoringEvent) -> MonitoringEventRecord:
        with self._lock:
            key = event_identity(profile_id, event)
            existing = next((row for row in self.monitoring_events if row.identity_key == key), None)
            if existing is not None:
                return existing
            now = datetime.now().astimezone()
            record = MonitoringEventRecord(
                id=f"event-{len(self.monitoring_events) + 1:08d}",
                profile_id=profile_id,
                event=deepcopy(event),
                identity_key=key,
                created_at=now,
            )
            self.monitoring_events.append(record)
            if event.status.value in {"attention", "insufficient_data", "safety"}:
                for recipient_id in ("demo-user", "demo-caregiver"):
                    self.notifications.append(
                        NotificationRecord(
                            id=f"notification-{len(self.notifications) + 1:08d}",
                            event_id=record.id,
                            recipient_id=recipient_id,
                            status="unread",
                            read_at=None,
                            created_at=now,
                        )
                    )
            return record

    def list_monitoring_events(self, profile_id: str) -> list[MonitoringEventRecord]:
        with self._lock:
            return [item for item in self.monitoring_events if item.profile_id == profile_id]

    def list_notifications(self, recipient_id: str) -> list[NotificationRecord]:
        with self._lock:
            return [item for item in self.notifications if item.recipient_id == recipient_id]

    def mark_notification_read(self, notification_id: str, recipient_id: str) -> NotificationRecord | None:
        with self._lock:
            for index, item in enumerate(self.notifications):
                if item.id == notification_id and item.recipient_id == recipient_id:
                    replacement = NotificationRecord(
                        id=item.id,
                        event_id=item.event_id,
                        recipient_id=item.recipient_id,
                        status="read",
                        read_at=datetime.now().astimezone(),
                        created_at=item.created_at,
                    )
                    self.notifications[index] = replacement
                    return replacement
            return None

    def replace_demo_scenario(
        self, profile_id: str, observations: tuple[Observation, ...],
        check_ins: tuple[CheckInRecord, ...], *, reset: bool,
    ) -> None:
        with self._lock:
            if reset:
                self.reset_demo_profile(profile_id)
            observation_ids = {item.id for item in observations}
            check_in_ids = {item.id for item in check_ins}
            self.observations = [item for item in self.observations if not (
                item.profile_id == profile_id and item.source == "simulator"
                and item.id.startswith("demo-") and item.id not in observation_ids
            )]
            obsolete = {item.id for item in self.check_ins if (
                item.profile_id == profile_id and item.source == "simulator"
                and item.id.startswith("demo-") and item.id not in check_in_ids
            )}
            self.check_ins = [item for item in self.check_ins if item.id not in obsolete]
            for check_in_id in obsolete:
                self.symptom_facts.pop(check_in_id, None)
            existing_observations = {item.id for item in self.observations}
            existing_check_ins = {item.id for item in self.check_ins}
            self.observations.extend(item for item in observations if item.id not in existing_observations)
            self.check_ins.extend(item for item in check_ins if item.id not in existing_check_ins)

    def reset_demo_profile(self, profile_id: str) -> None:
        with self._lock:
            self.observations = [item for item in self.observations if item.profile_id != profile_id]
            check_in_ids = {item.id for item in self.check_ins if item.profile_id == profile_id}
            self.check_ins = [item for item in self.check_ins if item.profile_id != profile_id]
            for check_in_id in check_in_ids:
                self.symptom_facts.pop(check_in_id, None)
            event_ids = {item.id for item in self.monitoring_events if item.profile_id == profile_id}
            self.monitoring_events = [item for item in self.monitoring_events if item.profile_id != profile_id]
            self.notifications = [item for item in self.notifications if item.event_id not in event_ids]



def build_store() -> InMemoryStore:
    """Build the configured store without importing SQLAlchemy for unit tests."""

    import os

    if os.getenv("MEDSI_STORAGE", "memory").lower() == "postgres":
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required when MEDSI_STORAGE=postgres")
        from app.db.repository import DatabaseStore

        return DatabaseStore(database_url)  # type: ignore[return-value]
    return InMemoryStore()
