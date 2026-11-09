"""Small in-memory repository used by the first vertical slice.

The repository boundary is intentional: PostgreSQL/SQLAlchemy can replace this
implementation without changing the API or monitoring domain logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.monitoring import Observation, SymptomFact


@dataclass(frozen=True, slots=True)
class CheckInRecord:
    id: str
    profile_id: str
    text: str
    source: str
    created_at: datetime
    corrected_text: str | None = None


class InMemoryStore:
    def __init__(self) -> None:
        self.observations: list[Observation] = []
        self.check_ins: list[CheckInRecord] = []
        self.symptom_facts: dict[str, list[SymptomFact]] = {}

    def add_observation(self, observation: Observation) -> Observation:
        self.observations.append(observation)
        return observation

    def list_observations(self, profile_id: str) -> list[Observation]:
        return sorted(
            [item for item in self.observations if item.profile_id == profile_id],
            key=lambda item: item.measured_at,
        )

    def add_check_in(self, check_in: CheckInRecord) -> CheckInRecord:
        self.check_ins.append(check_in)
        return check_in

    def list_check_ins(self, profile_id: str) -> list[CheckInRecord]:
        return sorted(
            [item for item in self.check_ins if item.profile_id == profile_id],
            key=lambda item: item.created_at,
            reverse=True,
        )

    def get_check_in(self, profile_id: str, check_in_id: str) -> CheckInRecord | None:
        return next(
            (
                item
                for item in self.check_ins
                if item.profile_id == profile_id and item.id == check_in_id
            ),
            None,
        )

    def confirm_check_in(
        self,
        profile_id: str,
        check_in_id: str,
        *,
        corrected_text: str | None,
        facts: list[SymptomFact],
    ) -> list[SymptomFact]:
        check_in = self.get_check_in(profile_id, check_in_id)
        if check_in is None:
            raise KeyError(check_in_id)
        replacement = CheckInRecord(
            id=check_in.id,
            profile_id=check_in.profile_id,
            text=check_in.text,
            source=check_in.source,
            created_at=check_in.created_at,
            corrected_text=corrected_text,
        )
        self.check_ins = [
            replacement if item.id == check_in_id else item for item in self.check_ins
        ]
        self.symptom_facts[check_in_id] = list(facts)
        return list(facts)

    def list_symptom_facts(self, check_in_id: str) -> list[SymptomFact]:
        return list(self.symptom_facts.get(check_in_id, []))


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
