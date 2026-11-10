"""Minimal current-revision fact lifecycle and deterministic temporal selection."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.domain.monitoring import SymptomFact

FACT_RULE_VERSION = "facts-window-v1"
MONITORING_RULE_VERSION = "daily-multimetric-v2+facts-window-v1"
FACT_WINDOW = timedelta(hours=24)


class TextRevisionConflict(ValueError):
    """The caller used an outdated text revision."""


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def fact_provenance(fact: SymptomFact, *, rule_version: str, resolution: str) -> dict:
    return {
        "check_in_id": fact.check_in_id, "fact_id": fact.id,
        "text_revision": fact.text_revision, "facts_revision": fact.facts_revision,
        "category": fact.category,
        "polarity": fact.polarity, "evidence": fact.evidence,
        "temporal_context": fact.temporal_context,
        "recorded_at": utc(fact.recorded_at).isoformat() if fact.recorded_at else None,
        "confirmed_at": utc(fact.confirmed_at).isoformat() if fact.confirmed_at else None,
        "rule_version": rule_version, "resolution": resolution,
    }


@dataclass(frozen=True)
class FactSelection:
    selected: tuple[SymptomFact, ...]
    attention_facts: tuple[SymptomFact, ...]
    conflicts: tuple[str, ...]

    def provenance(self) -> tuple[dict, ...]:
        return tuple(fact_provenance(
            fact, rule_version=MONITORING_RULE_VERSION,
            resolution="conflict" if fact.category.strip().casefold() in self.conflicts else "latest",
        ) for fact in self.selected)


def select_current_facts(facts: Iterable[SymptomFact], *, as_of: datetime) -> FactSelection:
    cutoff = utc(as_of)
    by_category: dict[str, list[SymptomFact]] = {}
    for fact in facts:
        if not (fact.confirmed and fact.id and fact.check_in_id and fact.text_revision
                and fact.recorded_at and fact.confirmed_at):
            continue
        recorded, confirmed = utc(fact.recorded_at), utc(fact.confirmed_at)
        if not cutoff - FACT_WINDOW <= recorded <= confirmed <= cutoff:
            continue
        by_category.setdefault(fact.category.strip().casefold(), []).append(fact)
    selected, attention, conflicts = [], [], []
    for category, rows in sorted(by_category.items()):
        # Recorded time determines which statement is newer. Confirming an old
        # statement today must not move its occurrence time to today.
        latest = max((utc(row.recorded_at), utc(row.confirmed_at)) for row in rows)
        winners = sorted((row for row in rows if (utc(row.recorded_at), utc(row.confirmed_at)) == latest),
                         key=lambda row: (row.check_in_id, row.id))
        selected.extend(winners)
        polarities = {row.polarity for row in winners}
        if len(polarities) > 1:
            conflicts.append(category)
        elif polarities == {"present"}:
            attention.extend(winners)
    return FactSelection(tuple(selected), tuple(attention), tuple(conflicts))
