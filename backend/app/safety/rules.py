"""Small, explicit safety rule set for the research prototype.

The rules consume only user-confirmed facts. They do not parse raw text, call
an LLM, diagnose a condition, or recommend treatment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.domain.monitoring import SymptomFact


SAFETY_RULE_VERSION = "safety-v1"
_URGENT_CATEGORIES = frozenset(
    {"chest_pain", "shortness_of_breath", "loss_of_consciousness", "stroke_signs", "severe_bleeding"}
)


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    rule_version: str
    level: str
    evidence: tuple[str, ...]
    message: str
    facts: tuple[SymptomFact, ...] = ()


def evaluate_safety(facts: Iterable[SymptomFact]) -> SafetyDecision | None:
    """Return a conservative safety decision for confirmed urgent facts only."""

    confirmed = [
        fact
        for fact in facts
        if fact.confirmed and fact.polarity == "present" and fact.category in _URGENT_CATEGORIES
    ]
    if not confirmed:
        return None
    evidence = tuple(f"{fact.category}: {fact.evidence}" for fact in confirmed)
    return SafetyDecision(
        facts=tuple(confirmed),
        rule_version=SAFETY_RULE_VERSION,
        level="safety",
        evidence=evidence,
        message=(
            "По подтверждённой записи обнаружен признак, требующий срочной "
            "медицинской оценки. Обратитесь за экстренной медицинской помощью."
        ),
    )
