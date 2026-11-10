"""Content identity for product events, independent of HTTP request time/IDs."""

from hashlib import sha256
import json

from app.domain.monitoring import MonitoringEvent, SymptomFact


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def fact_content(facts: list[SymptomFact]) -> list[dict]:
    """A fact set is unordered; persisted IDs/times are not a new confirmation."""
    return sorted([{
        "category": fact.category, "polarity": fact.polarity, "evidence": fact.evidence,
        "temporal_context": fact.temporal_context, "confidence": fact.confidence,
    } for fact in facts], key=canonical_json)


def event_identity(profile_id: str, event: MonitoringEvent) -> str:
    details = dict(event.analysis_details) if event.analysis_details is not None else None
    if details is not None:
        # The first saved event keeps its exact cutoff. A later request clock
        # alone is not a new input/episode within that same local calendar day.
        details.pop("as_of", None)
        details.pop("period_end", None)
    provenance = [{key: value for key, value in fact.items()
                   if key not in {"fact_id", "confirmed_at"}} for fact in event.text_provenance]
    payload = {
        "identity_version": "event-identity-v1", "profile_id": profile_id,
        "ruleset_version": event.algorithm_version,
        "kind": "safety" if event.status.value == "safety" else "analysis",
        "period_start": event.period_start.isoformat() if event.period_start else None,
        "status": event.status.value, "level": event.level,
        "metric": event.metric.value if event.metric else None, "z_score": event.z_score,
        "evidence": sorted(event.evidence), "source_observation_ids": sorted(event.source_observation_ids),
        "analysis_details": details, "text_provenance": sorted(provenance, key=canonical_json),
    }
    return sha256(canonical_json(payload).encode()).hexdigest()
