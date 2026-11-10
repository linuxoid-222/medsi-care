"""HTTP schemas for the manual-input vertical slice."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.monitoring import Metric, MonitoringStatus, validate_observation_fields


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
    quality: Literal["unknown", "good", "questionable"] = "unknown"

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_technical_constraints(self) -> "ObservationCreate":
        try:
            validate_observation_fields(
                self.metric,
                self.value,
                self.unit,
                self.measured_at,
                source=self.source,
                quality=self.quality,
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return self


class ObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    profile_id: str
    metric: Metric
    value: float
    unit: str
    measured_at: datetime
    source: str
    quality: str


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
    text_revision: int
    confirmed_revision: int | None = None
    confirmed_at: datetime | None = None
    facts: list["SymptomFactResponse"] = Field(default_factory=list)


class CheckInCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_revision: int = Field(ge=1)

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
    id: str | None = None
    check_in_id: str | None = None
    text_revision: int | None = None
    recorded_at: datetime | None = None
    confirmed_at: datetime | None = None


class FactExtractionResponse(BaseModel):
    text_revision: int
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

    text_revision: int = Field(ge=1)

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
    text_revision: int
    confirmed_at: datetime
    status: Literal["confirmed"]
    check_in_id: str
    facts: list[SymptomFactResponse]
    safety_event: "MonitoringEventResponse | None" = None


class TranscriptionResponse(BaseModel):
    status: Literal["awaiting_review"]
    provider: Literal["faster-whisper"]
    text: str
    language: str
    duration_seconds: float | None


class TextProvenance(BaseModel):
    check_in_id: str
    fact_id: str
    text_revision: int
    category: str
    polarity: Literal["present", "absent", "uncertain"]
    evidence: str
    temporal_context: str | None
    recorded_at: datetime
    confirmed_at: datetime
    rule_version: str
    resolution: Literal["latest", "conflict", "direct_confirmation"]


class AnalysisResponse(BaseModel):
    status: MonitoringStatus
    metric: Metric | None
    z_score: float | None
    evidence: list[str]
    message: str
    algorithm_version: str
    analysis_details: "NumericAnalysisDetails | None" = None
    text_provenance: list[TextProvenance] = Field(default_factory=list)


class BaselineResponse(BaseModel):
    metric: Metric
    center: float | None
    mad: float | None
    scale: float | None
    sample_count: int
    window_start: date
    window_end: date
    timezone: str
    days: list[date]
    source_observation_ids: list[str]
    aggregation: Literal["latest_daily_value", "daily_median"]
    quality: Literal["good", "unknown"]


class MetricAnalysisResponse(BaseModel):
    metric: Metric
    status: Literal["missing_measurement", "insufficient_data", "no_change", "attention"]
    value: float | None
    unit: str
    measured_at: datetime | None
    day: date
    quality: Literal["good", "unknown", "missing"]
    z_score: float | None
    baseline: BaselineResponse
    source_observation_ids: list[str]
    excluded_observation_ids: list[str]


class NumericAnalysisDetails(BaseModel):
    as_of: datetime
    timezone: str
    period_start: datetime
    period_end: datetime
    data_complete: bool
    metrics: list[MetricAnalysisResponse]


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
    analysis_details: NumericAnalysisDetails | None = None
    text_provenance: list[TextProvenance] = Field(default_factory=list)


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
    day: date | None = None
    quality: str = "unknown"
    source_observation_ids: list[str] = Field(default_factory=list)
    baseline_details: BaselineResponse | None = None


class DemoLoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int = Field(default=20261110, ge=0, le=2_147_483_647)
    days: int = Field(default=21, ge=14, le=28)
    reset: bool = True


class DemoLoadResponse(BaseModel):
    status: Literal["loaded"]
    synthetic: bool
    seed: int
    days: int
    observation_count: int
    check_in_count: int
    changed_from_day: int
