"""SQLAlchemy repository implementing the first slice storage contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, create_engine, select, update, delete
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError

from app.event_identity import event_identity, fact_content

from app.db.models import (
    CheckInModel,
    MonitoringEventModel,
    NotificationModel,
    ObservationModel,
    ProfileModel,
    SymptomFactModel,
)
from app.domain.monitoring import Metric, MonitoringEvent, MonitoringStatus, Observation, SymptomFact
from app.store import (
    CheckInCreationConflict, CheckInRecord, ConfirmationResult, MonitoringEventRecord,
    NotificationRecord, confirmation_safety_event,
)
from app.facts import TextRevisionConflict


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _check_in_record(row: CheckInModel) -> CheckInRecord:
    return CheckInRecord(
        id=row.id, profile_id=row.profile_id, text=row.text, source=row.source,
        created_at=_as_utc(row.created_at), corrected_text=row.corrected_text,
        text_revision=row.text_revision, facts_revision=row.facts_revision,
        confirmed_revision=row.confirmed_revision,
        confirmed_at=_as_utc(row.confirmed_at) if row.confirmed_at else None,
        creation_key=row.creation_key,
    )


def _check_in_row(record: CheckInRecord) -> CheckInModel:
    return CheckInModel(
        id=record.id, profile_id=record.profile_id, text=record.text, source=record.source,
        created_at=record.created_at, corrected_text=record.corrected_text,
        text_revision=record.text_revision, facts_revision=record.facts_revision,
        confirmed_revision=record.confirmed_revision, confirmed_at=record.confirmed_at,
        creation_key=record.creation_key,
    )


def _observation_row(observation: Observation) -> ObservationModel:
    return ObservationModel(
        id=observation.id, profile_id=observation.profile_id, metric=observation.metric.value,
        value=observation.value, unit=observation.unit, measured_at=observation.measured_at,
        source=observation.source, quality=observation.quality,
    )


def _event_record(row: MonitoringEventModel) -> MonitoringEventRecord:
    return MonitoringEventRecord(
        id=row.id,
        profile_id=row.profile_id,
        event=MonitoringEvent(
            status=MonitoringStatus(row.status),
            metric=Metric(row.metric) if row.metric else None,
            z_score=row.z_score,
            evidence=tuple(row.evidence_json),
            message=row.message,
            algorithm_version=row.ruleset_version,
            level=row.level,
            source_observation_ids=tuple(row.source_observation_ids),
            period_start=_as_utc(row.period_start) if row.period_start else None,
            period_end=_as_utc(row.period_end) if row.period_end else None,
            analysis_details=row.analysis_details,
            text_provenance=tuple(row.text_provenance or []),
        ),
        created_at=_as_utc(row.created_at),
        identity_key=row.identity_key,
    )


def _fact_record(row: SymptomFactModel, check_in: CheckInModel) -> SymptomFact:
    return SymptomFact(
        category=row.category, polarity=row.polarity, evidence=row.evidence,
        confirmed=row.confirmed, temporal_context=row.temporal_context,
        confidence=row.confidence, id=row.id, check_in_id=row.check_in_id,
        text_revision=row.text_revision, facts_revision=check_in.facts_revision,
        recorded_at=_as_utc(check_in.created_at), confirmed_at=_as_utc(row.created_at),
    )


class DatabaseStore:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self._ensure_demo_profile()

    def _ensure_demo_profile(self) -> None:
        with self.session_factory() as session:
            if session.get(ProfileModel, "profile-demo") is None:
                session.add(
                    ProfileModel(
                        id="profile-demo",
                        display_name="Демонстрационный профиль",
                        data_mode="synthetic",
                        created_at=datetime.now(timezone.utc),
                    )
                )
                session.commit()

    def add_observation(self, observation: Observation) -> Observation:
        with self.session_factory() as session:
            session.add(_observation_row(observation))
            session.commit()
        return observation

    def get_profile_timezone(self, profile_id: str) -> str:
        with self.session_factory() as session:
            row = session.get(ProfileModel, profile_id)
            if row is None:
                raise KeyError(profile_id)
            return row.timezone

    def list_observations(self, profile_id: str) -> list[Observation]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ObservationModel)
                .where(ObservationModel.profile_id == profile_id)
                .order_by(ObservationModel.measured_at)
            ).all()
            return [
                Observation(
                    id=row.id,
                    profile_id=row.profile_id,
                    metric=Metric(row.metric),
                    value=row.value,
                    unit=row.unit,
                    measured_at=_as_utc(row.measured_at),
                    source=row.source,
                    quality=row.quality,
                )
                for row in rows
            ]

    def add_check_in(self, check_in: CheckInRecord) -> CheckInRecord:
        with self.session_factory() as session:
            session.add(_check_in_row(check_in))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if check_in.creation_key is None:
                    raise
                original = session.scalar(select(CheckInModel).where(
                    CheckInModel.profile_id == check_in.profile_id,
                    CheckInModel.creation_key == check_in.creation_key,
                ))
                if original is None:
                    raise
                if (original.text, original.source) != (check_in.text, check_in.source):
                    raise CheckInCreationConflict() from None
                return _check_in_record(original)
        return check_in

    def list_check_ins(self, profile_id: str) -> list[CheckInRecord]:
        with self.session_factory() as session:
            rows = session.scalars(select(CheckInModel).where(
                CheckInModel.profile_id == profile_id,
            ).order_by(CheckInModel.created_at.desc()))
            return [_check_in_record(row) for row in rows]

    def get_check_in(self, profile_id: str, check_in_id: str) -> CheckInRecord | None:
        with self.session_factory() as session:
            row = session.scalar(select(CheckInModel).where(
                CheckInModel.profile_id == profile_id, CheckInModel.id == check_in_id,
            ))
            return _check_in_record(row) if row is not None else None

    def _check_in_snapshots(self, profile_id: str, check_in_id: str | None = None):
        # One SQL statement reads revision metadata and facts from the same snapshot.
        query = select(CheckInModel, SymptomFactModel).outerjoin(SymptomFactModel, and_(
            SymptomFactModel.check_in_id == CheckInModel.id,
            SymptomFactModel.text_revision == CheckInModel.text_revision,
            CheckInModel.confirmed_revision == CheckInModel.text_revision,
            SymptomFactModel.confirmed.is_(True),
        )).where(CheckInModel.profile_id == profile_id).order_by(
            CheckInModel.created_at.desc(), CheckInModel.id, SymptomFactModel.id,
        )
        if check_in_id is not None:
            query = query.where(CheckInModel.id == check_in_id)
        with self.session_factory() as session:
            snapshots = {}
            for row, fact in session.execute(query):
                if row.id not in snapshots:
                    snapshots[row.id] = (_check_in_record(row), [])
                if fact is not None:
                    snapshots[row.id][1].append(_fact_record(fact, row))
            return list(snapshots.values())

    def get_check_in_snapshot(self, profile_id: str, check_in_id: str):
        snapshots = self._check_in_snapshots(profile_id, check_in_id)
        return snapshots[0] if snapshots else None

    def list_check_in_snapshots(self, profile_id: str):
        return self._check_in_snapshots(profile_id)

    def update_check_in_text(
        self, profile_id: str, check_in_id: str, corrected_text: str, *, expected_revision: int,
    ) -> CheckInRecord | None:
        with self.session_factory() as session:
            row = session.scalar(select(CheckInModel).where(
                CheckInModel.id == check_in_id, CheckInModel.profile_id == profile_id,
            ).with_for_update())
            if row is None:
                return None
            if row.text_revision != expected_revision:
                raise TextRevisionConflict()
            changed = corrected_text != (row.corrected_text or row.text)
            values = {"corrected_text": corrected_text, "text_revision": expected_revision + int(changed)}
            if changed:
                values.update(confirmed_revision=None, confirmed_at=None)
            result = session.execute(update(CheckInModel).where(
                CheckInModel.id == check_in_id, CheckInModel.profile_id == profile_id,
                CheckInModel.text_revision == expected_revision,
            ).values(**values))
            if result.rowcount != 1:
                raise TextRevisionConflict()
            if changed:
                session.execute(delete(SymptomFactModel).where(SymptomFactModel.check_in_id == check_in_id))
            session.commit()
        return self.get_check_in(profile_id, check_in_id)

    def confirm_check_in(
        self, profile_id: str, check_in_id: str, *, corrected_text: str | None,
        facts: list[SymptomFact], expected_revision: int,
    ) -> ConfirmationResult:
        with self.session_factory.begin() as session:
            if self.engine.dialect.name == "sqlite":
                # SQLite has no SELECT FOR UPDATE. Reserve its writer before
                # reading the fact set so concurrent confirmations serialize.
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            row = session.scalar(select(CheckInModel).where(
                CheckInModel.id == check_in_id, CheckInModel.profile_id == profile_id,
            ).with_for_update())
            if row is None:
                raise KeyError(check_in_id)
            if row.text_revision != expected_revision or (
                corrected_text is not None and corrected_text != (row.corrected_text or row.text)
            ):
                raise TextRevisionConflict()
            current_rows = session.scalars(select(SymptomFactModel).where(
                SymptomFactModel.check_in_id == check_in_id,
                SymptomFactModel.text_revision == expected_revision,
                SymptomFactModel.confirmed.is_(True),
            ).order_by(SymptomFactModel.id)).all()
            current = [_fact_record(fact, row) for fact in current_rows]
            if row.confirmed_revision == expected_revision and fact_content(current) == fact_content(facts):
                return self._confirmation_result(session, _check_in_record(row), tuple(current))
            facts_revision = row.facts_revision + 1
            now = datetime.now(timezone.utc)
            result = session.execute(update(CheckInModel).where(
                CheckInModel.id == check_in_id, CheckInModel.profile_id == profile_id,
                CheckInModel.text_revision == expected_revision,
                CheckInModel.facts_revision == row.facts_revision,
            ).values(confirmed_revision=expected_revision, confirmed_at=now, facts_revision=facts_revision))
            if result.rowcount != 1:
                raise TextRevisionConflict()
            session.execute(delete(SymptomFactModel).where(SymptomFactModel.check_in_id == check_in_id))
            saved = []
            for fact in facts:
                fact_id = f"fact-{uuid4().hex}"
                saved.append(replace(fact, id=fact_id, check_in_id=check_in_id,
                                     text_revision=expected_revision, facts_revision=facts_revision,
                                     recorded_at=_as_utc(row.created_at),
                                     confirmed_at=now, confirmed=True))
                session.add(SymptomFactModel(
                    id=fact_id, check_in_id=check_in_id,
                    category=fact.category, polarity=fact.polarity,
                    temporal_context=fact.temporal_context, evidence=fact.evidence,
                    confidence=fact.confidence, confirmed=True,
                    text_revision=expected_revision, created_at=now,
                ))
            record = _check_in_record(row)
            return self._confirmation_result(session, record, tuple(sorted(saved, key=lambda fact: fact.id)))

    def _confirmation_result(
        self, session: Session, record: CheckInRecord, facts: tuple[SymptomFact, ...],
    ) -> ConfirmationResult:
        event = confirmation_safety_event(record, facts)
        saved = self._write_monitoring_event(session, record.profile_id, event) if event else None
        return ConfirmationResult(record, facts, saved)

    def list_symptom_facts(self, check_in_id: str) -> list[SymptomFact]:
        with self.session_factory() as session:
            rows = session.execute(select(SymptomFactModel, CheckInModel).join(CheckInModel).where(
                SymptomFactModel.check_in_id == check_in_id,
                SymptomFactModel.confirmed.is_(True),
                CheckInModel.confirmed_revision == CheckInModel.text_revision,
                SymptomFactModel.text_revision == CheckInModel.text_revision,
            ).order_by(SymptomFactModel.id)).all()
            return [_fact_record(fact, check_in) for fact, check_in in rows]

    def save_monitoring_event(self, profile_id: str, event: MonitoringEvent) -> MonitoringEventRecord:
        with self.session_factory.begin() as session:
            self._sqlite_write_lock(session)
            return self._write_monitoring_event(session, profile_id, event)

    def _write_monitoring_event(
        self, session: Session, profile_id: str, event: MonitoringEvent,
    ) -> MonitoringEventRecord:
        key = event_identity(profile_id, event)
        now = datetime.now(timezone.utc)
        event_id = f"event-{uuid4().hex}"
        row = MonitoringEventModel(
            id=event_id, profile_id=profile_id, identity_key=key,
            status=event.status.value, level=event.level,
            metric=event.metric.value if event.metric else None, z_score=event.z_score,
            message=event.message, evidence_json=list(event.evidence),
            source_observation_ids=list(event.source_observation_ids),
            period_start=event.period_start, period_end=event.period_end,
            ruleset_version=event.algorithm_version, analysis_details=event.analysis_details,
            text_provenance=list(event.text_provenance), created_at=now,
        )
        try:
            # A savepoint isolates a duplicate-key failure while preserving the
            # outer transaction of a confirmation.
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            existing = session.scalar(select(MonitoringEventModel).where(
                MonitoringEventModel.profile_id == profile_id,
                MonitoringEventModel.identity_key == key,
            ))
            if existing is None:
                raise
            return _event_record(existing)
        if event.status.value in {"attention", "insufficient_data", "safety"}:
            for recipient_id in ("demo-user", "demo-caregiver"):
                session.add(NotificationModel(
                    id=f"notification-{uuid4().hex}", event_id=event_id,
                    recipient_id=recipient_id, status="unread", read_at=None, created_at=now,
                ))
        return _event_record(row)

    def list_monitoring_events(self, profile_id: str) -> list[MonitoringEventRecord]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(MonitoringEventModel)
                .where(MonitoringEventModel.profile_id == profile_id)
                .order_by(MonitoringEventModel.created_at.desc())
            ).all()
            return [
                _event_record(row)
                for row in rows
            ]

    def list_notifications(self, recipient_id: str) -> list[NotificationRecord]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(NotificationModel)
                .where(NotificationModel.recipient_id == recipient_id)
                .order_by(NotificationModel.created_at.desc())
            ).all()
            return [
                NotificationRecord(
                    id=row.id,
                    event_id=row.event_id,
                    recipient_id=row.recipient_id,
                    status=row.status,
                    read_at=_as_utc(row.read_at) if row.read_at else None,
                    created_at=_as_utc(row.created_at),
                )
                for row in rows
            ]

    def mark_notification_read(self, notification_id: str, recipient_id: str) -> NotificationRecord | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(NotificationModel).where(
                    NotificationModel.id == notification_id,
                    NotificationModel.recipient_id == recipient_id,
                )
            )
            if row is None:
                return None
            row.status = "read"
            row.read_at = datetime.now(timezone.utc)
            session.commit()
            return NotificationRecord(
                id=row.id,
                event_id=row.event_id,
                recipient_id=row.recipient_id,
                status=row.status,
                read_at=_as_utc(row.read_at),
                created_at=_as_utc(row.created_at),
            )

    def _sqlite_write_lock(self, session: Session) -> None:
        if self.engine.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")

    def _lock_demo_profile(self, session: Session, profile_id: str) -> None:
        self._sqlite_write_lock(session)
        session.execute(select(ProfileModel.id).where(
            ProfileModel.id == profile_id,
        ).with_for_update(key_share=True))

    def _remove_check_ins(self, session, check_in_ids):
        if check_in_ids:
            session.execute(delete(SymptomFactModel).where(SymptomFactModel.check_in_id.in_(check_in_ids)))
            session.execute(delete(CheckInModel).where(CheckInModel.id.in_(check_in_ids)))

    def _reset_demo_profile(self, session: Session, profile_id: str) -> None:
        check_in_ids = session.scalars(select(CheckInModel.id).where(
            CheckInModel.profile_id == profile_id,
        ).with_for_update()).all()
        event_ids = session.scalars(select(MonitoringEventModel.id).where(
            MonitoringEventModel.profile_id == profile_id,
        )).all()
        if event_ids:
            session.execute(delete(NotificationModel).where(NotificationModel.event_id.in_(event_ids)))
            session.execute(delete(MonitoringEventModel).where(MonitoringEventModel.id.in_(event_ids)))
        self._remove_check_ins(session, check_in_ids)
        session.execute(delete(ObservationModel).where(ObservationModel.profile_id == profile_id))

    def replace_demo_scenario(
        self, profile_id: str, observations: tuple[Observation, ...],
        check_ins: tuple[CheckInRecord, ...], *, reset: bool,
    ) -> None:
        with self.session_factory.begin() as session:
            self._lock_demo_profile(session, profile_id)
            if reset:
                self._reset_demo_profile(session, profile_id)
            observation_ids = {item.id for item in observations}
            check_in_ids = {item.id for item in check_ins}
            existing_observations = set(session.scalars(select(ObservationModel.id).where(
                ObservationModel.profile_id == profile_id,
                ObservationModel.source == "simulator",
                ObservationModel.id.like("demo-%"),
            )))
            existing_check_ins = set(session.scalars(select(CheckInModel.id).where(
                CheckInModel.profile_id == profile_id,
                CheckInModel.source == "simulator",
                CheckInModel.id.like("demo-%"),
            ).with_for_update()))
            obsolete_observations = existing_observations - observation_ids
            if obsolete_observations:
                session.execute(delete(ObservationModel).where(ObservationModel.id.in_(obsolete_observations)))
            self._remove_check_ins(session, existing_check_ins - check_in_ids)
            session.add_all(_observation_row(item) for item in observations if item.id not in existing_observations)
            session.add_all(_check_in_row(item) for item in check_ins if item.id not in existing_check_ins)

    def reset_demo_profile(self, profile_id: str) -> None:
        with self.session_factory.begin() as session:
            self._lock_demo_profile(session, profile_id)
            self._reset_demo_profile(session, profile_id)
