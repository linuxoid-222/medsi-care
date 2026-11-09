"""HTTP schemas for the manual-input vertical slice."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.monitoring import Metric, MonitoringStatus


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    user_id: str
    role: Literal["user", "caregiver"]
    profile_id: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    user: UserResponse


class CaregiverSummaryResponse(BaseModel):
    profile: dict[str, str]
    observations: list["ObservationResponse"]
    check_ins: list["CheckInResponse"]
    latest_analysis: "AnalysisResponse | None" = None
    events: list["MonitoringEventResponse"] = []
    notifications: list["NotificationResponse"] = []


class ObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Metric
    value: float = Field(..., allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=16)
    measured_at: datetime
    source: Literal["manual", "simulator"] = "manual"

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str) -> str:
        return value.strip()


class ObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    profile_id: str
    metric: Metric
    value: float
    unit: str
    measured_at: datetime
    source: str


class CheckInCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    source: Literal["manual"] = "manual"

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value


class CheckInResponse(BaseModel):
    id: str
    profile_id: str
    text: str
    corrected_text: str | None = None
    source: str
    created_at: datetime
    status: Literal["awaiting_analysis", "confirmed"]


class CheckInCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrected_text: str = Field(min_length=1, max_length=4000)

    @field_validator("corrected_text")
    @classmethod
    def strip_corrected_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("corrected_text must not be blank")
        return value


class SymptomFactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    polarity: str
    temporal_context: str | None = None
    evidence: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    confirmed: bool


class FactExtractionResponse(BaseModel):
    status: Literal["awaiting_confirmation"]
    provider: Literal["gigachat"]
    facts: list[SymptomFactResponse]


class SymptomFactConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=64)
    polarity: Literal["present", "absent", "uncertain"]
    temporal_context: str | None = Field(default=None, max_length=256)
    evidence: str = Field(min_length=1, max_length=500)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class CheckInConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrected_text: str | None = Field(default=None, max_length=4000)
    facts: list[SymptomFactConfirmInput] = Field(max_length=10)

    @field_validator("corrected_text")
    @classmethod
    def strip_corrected_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("corrected_text must not be blank")
        return value


class CheckInConfirmResponse(BaseModel):
    status: Literal["confirmed"]
    check_in_id: str
    facts: list[SymptomFactResponse]


class TranscriptionResponse(BaseModel):
    status: Literal["awaiting_review"]
    provider: Literal["faster-whisper"]
    text: str
    language: str
    duration_seconds: float | None


class AnalysisResponse(BaseModel):
    status: MonitoringStatus
    metric: Metric | None
    z_score: float | None
    evidence: list[str]
    message: str
    algorithm_version: str


class MonitoringEventResponse(BaseModel):
    id: str
    profile_id: str
    status: MonitoringStatus
    level: str
    metric: Metric | None
    z_score: float | None
    message: str
    evidence: list[str]
    source_observation_ids: list[str]
    period_start: datetime | None
    period_end: datetime | None
    ruleset_version: str
    created_at: datetime


class NotificationResponse(BaseModel):
    id: str
    event_id: str
    recipient_id: str
    status: Literal["unread", "read"]
    read_at: datetime | None
    created_at: datetime


class TrendPointResponse(BaseModel):
    measured_at: datetime
    value: float
    baseline: float | None
    event_ids: list[str]
