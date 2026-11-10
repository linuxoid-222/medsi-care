"""Explicit extractor boundary used by reproducible experiments.

The deterministic implementation is a transparent text heuristic. It is an
engineering baseline, not a clinically trained model.
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


EXTRACTOR_VERSION = "deterministic-ru-v1"


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=64)
    polarity: str = Field(pattern="^(present|absent|uncertain)$")
    evidence: str = Field(min_length=1, max_length=500)


class ExtractorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extractor_version: str = Field(min_length=1, max_length=64)
    facts: list[ExtractedFact] = Field(default_factory=list, max_length=10)


class FactExtractor(Protocol):
    version: str

    def extract(self, text: str) -> ExtractorResult:
        """Extract facts from text only; no labels or scenario metadata."""


class LlmFactProvider(Protocol):
    def extract_facts(self, text: str) -> list[object]:
        """Optional provider contract; the provider remains outside Method C."""


class LlmExtractorAdapter:
    """Optional adapter for an existing LLM provider, never required by tests."""

    def __init__(self, provider: LlmFactProvider, *, version: str = "llm-adapter-v1") -> None:
        self.provider = provider
        self.version = version

    def extract(self, text: str) -> ExtractorResult:
        facts = []
        for item in self.provider.extract_facts(text):
            facts.append(
                ExtractedFact(
                    category=str(item.category),
                    polarity=str(item.polarity),
                    evidence=str(item.evidence),
                )
            )
        return ExtractorResult(extractor_version=self.version, facts=facts)


class DeterministicRuExtractor:
    """Small reproducible Russian heuristic for synthetic experiment text."""

    version = EXTRACTOR_VERSION

    def extract(self, text: str) -> ExtractorResult:
        normalized = " ".join(text.lower().split())
        if "слабост" not in normalized:
            return ExtractorResult(extractor_version=self.version, facts=[])
        if re.search(r"(?:нет\s+|без\s+)?слабост\w*", normalized) and (
            "нет" in normalized or "без" in normalized
        ):
            polarity = "absent"
            evidence = "слабости сегодня нет" if "сегодня" in normalized else "слабости нет"
        elif any(marker in normalized for marker in ("возможно", "кажется", "не уверен")):
            polarity = "uncertain"
            evidence = "чувствую слабость"
        else:
            polarity = "present"
            evidence = "чувствую слабость"
        return ExtractorResult(
            extractor_version=self.version,
            facts=[ExtractedFact(category="weakness", polarity=polarity, evidence=evidence)],
        )
