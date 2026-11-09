"""SQLAlchemy repository implementing the first slice storage contract."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import CheckInModel, ObservationModel, ProfileModel, SymptomFactModel
from app.domain.monitoring import Metric, Observation, SymptomFact
from app.store import CheckInRecord


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
            session.add(
                ObservationModel(
                    id=observation.id,
                    profile_id=observation.profile_id,
                    metric=observation.metric.value,
                    value=observation.value,
                    unit=observation.unit,
                    measured_at=observation.measured_at,
                    source=observation.source,
                )
            )
            session.commit()
        return observation

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
                )
                for row in rows
            ]

    def add_check_in(self, check_in: CheckInRecord) -> CheckInRecord:
        with self.session_factory() as session:
            session.add(
                CheckInModel(
                    id=check_in.id,
                    profile_id=check_in.profile_id,
                    text=check_in.text,
                    source=check_in.source,
                    created_at=check_in.created_at,
                    corrected_text=check_in.corrected_text,
                )
            )
            session.commit()
        return check_in

    def list_check_ins(self, profile_id: str) -> list[CheckInRecord]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(CheckInModel)
                .where(CheckInModel.profile_id == profile_id)
                .order_by(CheckInModel.created_at.desc())
            ).all()
            return [
                CheckInRecord(
                    id=row.id,
                    profile_id=row.profile_id,
                    text=row.text,
                    source=row.source,
                    created_at=_as_utc(row.created_at),
                    corrected_text=row.corrected_text,
                )
                for row in rows
            ]

    def get_check_in(self, profile_id: str, check_in_id: str) -> CheckInRecord | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(CheckInModel).where(
                    CheckInModel.profile_id == profile_id,
                    CheckInModel.id == check_in_id,
                )
            )
            if row is None:
                return None
            return CheckInRecord(
                id=row.id,
                profile_id=row.profile_id,
                text=row.text,
                source=row.source,
                created_at=_as_utc(row.created_at),
                corrected_text=row.corrected_text,
            )

    def confirm_check_in(
        self,
        profile_id: str,
        check_in_id: str,
        *,
        corrected_text: str | None,
        facts: list[SymptomFact],
    ) -> list[SymptomFact]:
        with self.session_factory() as session:
            check_in = session.scalar(
                select(CheckInModel).where(
                    CheckInModel.profile_id == profile_id,
                    CheckInModel.id == check_in_id,
                )
            )
            if check_in is None:
                raise KeyError(check_in_id)
            check_in.corrected_text = corrected_text
            check_in.symptom_facts.clear()
            now = datetime.now(timezone.utc)
            for fact in facts:
                check_in.symptom_facts.append(
                    SymptomFactModel(
                        id=f"fact-{uuid4().hex}",
                        category=fact.category,
                        polarity=fact.polarity,
                        temporal_context=fact.temporal_context,
                        evidence=fact.evidence,
                        confidence=fact.confidence,
                        confirmed=fact.confirmed,
                        created_at=now,
                    )
                )
            session.commit()
        return list(facts)

    def list_symptom_facts(self, check_in_id: str) -> list[SymptomFact]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(SymptomFactModel)
                .where(SymptomFactModel.check_in_id == check_in_id)
                .order_by(SymptomFactModel.created_at)
            ).all()
            return [
                SymptomFact(
                    category=row.category,
                    polarity=row.polarity,
                    evidence=row.evidence,
                    confirmed=row.confirmed,
                    temporal_context=row.temporal_context,
                    confidence=row.confidence,
                )
                for row in rows
            ]
