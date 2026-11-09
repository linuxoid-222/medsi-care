"""Small, explicit GigaChat adapter for structured symptom extraction."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.domain.monitoring import SymptomFact


class GigaChatConfigurationError(RuntimeError):
    """Raised when required provider configuration is absent."""


class GigaChatRequestError(RuntimeError):
    """Raised when GigaChat rejects or cannot complete a request."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class FactExtractionValidationError(RuntimeError):
    """Raised when an LLM response violates the trusted fact boundary."""


class SymptomFactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=64)
    polarity: str = Field(pattern="^(present|absent|uncertain)$")
    evidence: str = Field(min_length=1, max_length=500)

    @field_validator("category", "evidence")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class FactExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[SymptomFactPayload] = Field(default_factory=list, max_length=10)


@dataclass(frozen=True, slots=True)
class GigaChatSettings:
    base_url: str
    oauth_url: str
    auth_key: str
    scope: str
    model: str
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "GigaChatSettings":
        auth_key = os.getenv("GIGACHAT_AUTH_KEY", "").strip()
        model = os.getenv("GIGACHAT_MODEL", "").strip()
        if not auth_key:
            raise GigaChatConfigurationError("GIGACHAT_AUTH_KEY is not configured")
        if not model:
            raise GigaChatConfigurationError("GIGACHAT_MODEL is not configured")
        return cls(
            base_url=os.getenv("GIGACHAT_BASE_URL", "https://api.giga.chat").rstrip("/"),
            oauth_url=os.getenv(
                "GIGACHAT_OAUTH_URL",
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            ),
            auth_key=auth_key,
            scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            model=model,
            timeout_seconds=float(os.getenv("GIGACHAT_TIMEOUT_SECONDS", "30")),
        )


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("error") or response.text)
    except (ValueError, json.JSONDecodeError):
        pass
    return response.text[:300] or f"HTTP {response.status_code}"


def validate_fact_payload(text: str, payload: FactExtractionPayload) -> list[SymptomFact]:
    """Apply semantic checks after Pydantic schema validation."""

    normalized_text = " ".join(text.split())
    facts: list[SymptomFact] = []
    for fact in payload.facts:
        if fact.evidence not in normalized_text:
            raise FactExtractionValidationError(
                f"Evidence is not present in source text for category {fact.category!r}"
            )
        facts.append(
            SymptomFact(
                category=fact.category,
                polarity=fact.polarity,
                evidence=fact.evidence,
                confirmed=False,
            )
        )
    return facts


def validate_confirmed_facts(
    text: str,
    items: list[dict[str, Any]],
) -> list[SymptomFact]:
    """Validate user-confirmed facts before persistence."""

    normalized_text = " ".join(text.split())
    facts: list[SymptomFact] = []
    for item in items:
        evidence = str(item["evidence"])
        if evidence not in normalized_text:
            raise FactExtractionValidationError(
                f"Evidence is not present in source text for category {item['category']!r}"
            )
        facts.append(
            SymptomFact(
                category=str(item["category"]),
                polarity=str(item["polarity"]),
                evidence=evidence,
                confirmed=True,
                temporal_context=item.get("temporal_context"),
                confidence=item.get("confidence"),
            )
        )
    return facts


class GigaChatProvider:
    """GigaChat v2 adapter; it never decides monitoring events."""

    def __init__(
        self,
        settings: GigaChatSettings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.timeout_seconds)
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def close(self) -> None:
        self.client.close()

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token
        try:
            response = self.client.post(
                self.settings.oauth_url,
                headers={
                    "Accept": "application/json",
                    "RqUID": str(uuid4()),
                    "Authorization": f"Basic {self.settings.auth_key}",
                },
                data={"scope": self.settings.scope},
            )
        except httpx.HTTPError as exc:
            raise GigaChatRequestError("GigaChat token request failed") from exc
        if response.is_error:
            raise GigaChatRequestError(
                f"GigaChat token request failed: {_error_message(response)}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
            token = str(payload["access_token"])
            expires_at = float(payload["expires_at"])
        except (ValueError, KeyError, TypeError) as exc:
            raise GigaChatRequestError("GigaChat token response is invalid") from exc
        self._access_token = token
        self._token_expires_at = expires_at
        return token

    def extract_facts(self, text: str) -> list[SymptomFact]:
        if not text.strip():
            raise FactExtractionValidationError("Source text must not be blank")
        token = self._get_access_token()
        schema = FactExtractionPayload.model_json_schema()
        request = {
            "model": self.settings.model,
            "temperature": 0.0,
            "max_tokens": 512,
            "messages": [
                {
                    "role": "system",
                    "content": [{
                        "text": (
                            "Извлеки только явно сказанные сведения о самочувствии. "
                            "Не добавляй измерения, диагнозы или сведения, которых нет в тексте."
                        )
                    }],
                },
                {"role": "user", "content": [{"text": text}]},
            ],
            "model_options": {
                "response_format": {
                    "type": "json_schema",
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        try:
            response = self.client.post(
                f"{self.settings.base_url}/v2/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json=request,
            )
        except httpx.HTTPError as exc:
            raise GigaChatRequestError("GigaChat completion request failed") from exc
        if response.is_error:
            raise GigaChatRequestError(
                f"GigaChat completion failed: {_error_message(response)}",
                status_code=response.status_code,
            )
        try:
            response_payload: dict[str, Any] = response.json()
            raw_content = response_payload["messages"][0]["content"][0]["text"]
            parsed = FactExtractionPayload.model_validate_json(raw_content)
        except (ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            raise FactExtractionValidationError("GigaChat structured response is invalid") from exc
        return validate_fact_payload(text, parsed)
