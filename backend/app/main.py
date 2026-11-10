"""FastAPI entry point for the first manual-input vertical slice."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.auth import CurrentUser, authenticate, issue_token, require_profile_access
from app.demo import build_demo_scenario
from app.ai.asr import (
    ASRConfigurationError,
    ASRInputError,
    ASRProcessingError,
    build_transcriber,
    validate_audio_filename,
)
from app.ai.gigachat import (
    FactExtractionValidationError,
    GigaChatConfigurationError,
    GigaChatProvider,
    GigaChatRequestError,
    GigaChatSettings,
    validate_confirmed_facts,
)
from app.domain.monitoring import (
    Metric,
    Observation,
    MonitoringEvent,
    MonitoringStatus,
    analyze_metrics,
    aggregate_daily,
    baseline_details,
    calculate_baseline,
    expected_unit,
    validate_pressure_pair,
)
from app.facts import (MONITORING_RULE_VERSION, TextRevisionConflict, fact_provenance, select_current_facts)
from app.safety import evaluate_safety
from app.schemas import (
    AnalysisResponse,
    CaregiverSummaryResponse,
    CheckInConfirmRequest,
    CheckInConfirmResponse,
    CheckInCorrectionRequest,
    CheckInCreate,
    CheckInResponse,
    DemoLoadRequest,
    DemoLoadResponse,
    FactExtractionResponse,
    LoginRequest,
    LoginResponse,
    MonitoringEventResponse,
    NotificationResponse,
    ObservationCreate,
    ObservationResponse,
    SymptomFactResponse,
    TranscriptionResponse,
    TrendPointResponse,
    UserResponse,
)
from app.store import CheckInRecord, build_store


PROFILE_ID = "profile-demo"
store = build_store()
app = FastAPI(title="MEDSI Care API", version="0.1.0")


def _require_profile(profile_id: str) -> None:
    # The first slice has one explicitly synthetic profile. Authentication and
    # caregiver grants are added after the manual flow is stable.
    if profile_id != PROFILE_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")


def _fact_response(fact) -> SymptomFactResponse:
    return SymptomFactResponse(
        category=fact.category,
        polarity=fact.polarity,
        temporal_context=fact.temporal_context,
        evidence=fact.evidence,
        confidence=fact.confidence,
        confirmed=fact.confirmed,
        id=fact.id, check_in_id=fact.check_in_id, text_revision=fact.text_revision,
        recorded_at=fact.recorded_at, confirmed_at=fact.confirmed_at,
    )


def _event_response(record) -> MonitoringEventResponse:
    event = record.event
    return MonitoringEventResponse(
        id=record.id,
        profile_id=record.profile_id,
        status=event.status,
        level=event.level,
        metric=event.metric,
        z_score=event.z_score,
        message=event.message,
        evidence=list(event.evidence),
        source_observation_ids=list(event.source_observation_ids),
        period_start=event.period_start,
        period_end=event.period_end,
        ruleset_version=event.algorithm_version,
        created_at=record.created_at,
        analysis_details=event.analysis_details,
        text_provenance=list(event.text_provenance),
    )


def _analysis_cutoff(value: datetime | None) -> datetime:
    now = datetime.now(timezone.utc)
    value = value or now
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if value > now:
        raise HTTPException(status_code=422, detail="as_of cannot be in the future")
    return value


def _analysis_for_profile(profile_id: str, as_of: datetime | None = None):
    cutoff = _analysis_cutoff(as_of)
    observations = store.list_observations(profile_id)
    facts = [fact for check_in in store.list_check_ins(profile_id)
             for fact in store.list_symptom_facts(check_in.id)]
    selection = select_current_facts(facts, as_of=cutoff)
    event = analyze_metrics(
        observations, as_of=cutoff,
        profile_timezone=store.get_profile_timezone(profile_id), symptom_facts=selection.attention_facts,
    )
    event = replace(event, algorithm_version=MONITORING_RULE_VERSION,
                    text_provenance=selection.provenance())
    return AnalysisResponse(
        status=event.status, metric=event.metric, z_score=event.z_score,
        evidence=list(event.evidence), message=event.message,
        algorithm_version=event.algorithm_version, analysis_details=event.analysis_details,
        text_provenance=list(event.text_provenance),
    ), event


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data_mode": "synthetic"}


@app.post("/api/v1/demo/load-scenario", response_model=DemoLoadResponse)
def load_demo_scenario(payload: DemoLoadRequest, user: CurrentUser) -> DemoLoadResponse:
    _require_profile(user.profile_id)
    require_profile_access(user.profile_id, user, write=True)
    if os.getenv("MEDSI_DEMO_MODE", "true").lower() != "true":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo mode is disabled")
    scenario = build_demo_scenario(profile_id=user.profile_id, seed=payload.seed, days=payload.days)
    if payload.reset:
        store.reset_demo_profile(user.profile_id)
    for observation in scenario.observations:
        store.add_observation(observation)
    for check_in in scenario.check_ins:
        store.add_check_in(check_in)
    return DemoLoadResponse(
        status="loaded",
        synthetic=True,
        seed=scenario.seed,
        days=scenario.days,
        observation_count=len(scenario.observations),
        check_in_count=len(scenario.check_ins),
        changed_from_day=14,
    )


@app.post("/api/v1/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    user = authenticate(payload.user_id, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return LoginResponse(
        access_token=issue_token(user),
        token_type="bearer",
        user=UserResponse(user_id=user.user_id, role=user.role, profile_id=user.profile_id),
    )


@app.get("/api/v1/me", response_model=UserResponse)
def me(user: CurrentUser) -> UserResponse:
    return UserResponse(user_id=user.user_id, role=user.role, profile_id=user.profile_id)


@app.get("/api/v1/profiles/{profile_id}")
def profile(profile_id: str, user: CurrentUser) -> dict[str, str]:
    _require_profile(profile_id)
    require_profile_access(profile_id, user)
    return {
        "id": PROFILE_ID,
        "display_name": "Демонстрационный профиль",
        "data_mode": "synthetic",
        "timezone": store.get_profile_timezone(profile_id),
    }


@app.post(
    "/api/v1/profiles/{profile_id}/observations",
    response_model=ObservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_observation(profile_id: str, payload: ObservationCreate, user: CurrentUser) -> Observation:
    _require_profile(profile_id)
    require_profile_access(profile_id, user, write=True)
    if payload.unit != expected_unit(payload.metric):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Expected unit for {payload.metric.value}: {expected_unit(payload.metric)}",
        )
    measured_at = payload.measured_at
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone.utc)
    observation = Observation(
        id=f"obs-{uuid4().hex}",
        profile_id=profile_id,
        metric=payload.metric,
        value=payload.value,
        unit=payload.unit,
        measured_at=measured_at.astimezone(timezone.utc),
        source=payload.source,
        quality=payload.quality,
    )
    if payload.metric in {Metric.SYSTOLIC_BP, Metric.DIASTOLIC_BP}:
        counterpart_metric = (
            Metric.DIASTOLIC_BP if payload.metric == Metric.SYSTOLIC_BP else Metric.SYSTOLIC_BP
        )
        counterpart = next(
            (
                item
                for item in store.list_observations(profile_id)
                if item.metric == counterpart_metric and item.measured_at == observation.measured_at
            ),
            None,
        )
        if counterpart is not None:
            systolic = observation.value if observation.metric == Metric.SYSTOLIC_BP else counterpart.value
            diastolic = observation.value if observation.metric == Metric.DIASTOLIC_BP else counterpart.value
            try:
                validate_pressure_pair(systolic, diastolic)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=str(exc),
                ) from exc
    return store.add_observation(observation)


@app.get(
    "/api/v1/profiles/{profile_id}/observations",
    response_model=list[ObservationResponse],
)
def list_observations(profile_id: str, user: CurrentUser) -> list[Observation]:
    _require_profile(profile_id)
    require_profile_access(profile_id, user)
    return store.list_observations(profile_id)


@app.post(
    "/api/v1/profiles/{profile_id}/check-ins",
    response_model=CheckInResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_check_in(profile_id: str, payload: CheckInCreate, user: CurrentUser) -> CheckInResponse:
    _require_profile(profile_id)
    require_profile_access(profile_id, user, write=True)
    record = store.add_check_in(
        CheckInRecord(
            id=f"checkin-{uuid4().hex}",
            profile_id=profile_id,
            text=payload.text,
            source=payload.source,
            created_at=datetime.now(timezone.utc),
        )
    )
    return _check_in_response(record)


def _check_in_response(record) -> CheckInResponse:
    return CheckInResponse(
        id=record.id, profile_id=record.profile_id, text=record.text,
        corrected_text=record.corrected_text, source=record.source, created_at=record.created_at,
        text_revision=record.text_revision, confirmed_revision=record.confirmed_revision,
        confirmed_at=record.confirmed_at,
        status="confirmed" if record.is_confirmed else "awaiting_analysis",
        facts=[_fact_response(fact) for fact in store.list_symptom_facts(record.id)],
    )


def _revision_conflict() -> HTTPException:
    return HTTPException(status_code=409, detail="Текст изменён. Загрузите актуальную запись и повторите проверку фактов.")


@app.get("/api/v1/profiles/{profile_id}/check-ins", response_model=list[CheckInResponse])
def list_check_ins(profile_id: str, user: CurrentUser) -> list[CheckInResponse]:
    _require_profile(profile_id)
    require_profile_access(profile_id, user)
    return [_check_in_response(item) for item in store.list_check_ins(profile_id)]


@app.get("/api/v1/profiles/{profile_id}/check-ins/{check_in_id}", response_model=CheckInResponse)
def get_check_in(profile_id: str, check_in_id: str, user: CurrentUser) -> CheckInResponse:
    _require_profile(profile_id)
    require_profile_access(profile_id, user)
    record = store.get_check_in(profile_id, check_in_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Check-in not found")
    return _check_in_response(record)


@app.patch("/api/v1/profiles/{profile_id}/check-ins/{check_in_id}", response_model=CheckInResponse)
def correct_check_in(
    profile_id: str, check_in_id: str, payload: CheckInCorrectionRequest, user: CurrentUser,
) -> CheckInResponse:
    _require_profile(profile_id)
    require_profile_access(profile_id, user, write=True)
    try:
        record = store.update_check_in_text(profile_id, check_in_id, payload.corrected_text,
                                          expected_revision=payload.text_revision)
    except TextRevisionConflict as exc:
        raise _revision_conflict() from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Check-in not found")
    return _check_in_response(record)


@app.post(
    "/api/v1/profiles/{profile_id}/audio/transcriptions",
    response_model=TranscriptionResponse,
)
async def transcribe_audio(
    profile_id: str,
    audio: UploadFile = File(...),
    user: CurrentUser = None,
) -> TranscriptionResponse:
    _require_profile(profile_id)
    require_profile_access(profile_id, user, write=True)
    try:
        validate_audio_filename(audio.filename)
        transcriber = build_transcriber()
        settings = transcriber.settings
        content = await audio.read(settings.max_audio_bytes + 1)
        if not content:
            raise ASRInputError("Audio file is empty")
        if len(content) > settings.max_audio_bytes:
            raise ASRInputError("Audio file is too large")
        suffix = Path(audio.filename or "audio.wav").suffix or ".wav"
        with NamedTemporaryFile(suffix=suffix) as temporary:
            temporary.write(content)
            temporary.flush()
            transcript = await run_in_threadpool(transcriber.transcribe, temporary.name)
    except ASRInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except ASRConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local speech recognition is not configured",
        ) from exc
    except ASRProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Audio transcription failed",
        ) from exc
    finally:
        await audio.close()
    return TranscriptionResponse(
        status="awaiting_review",
        provider=transcript.provider,
        text=transcript.text,
        language=transcript.language,
        duration_seconds=transcript.duration_seconds,
    )


@app.post(
    "/api/v1/profiles/{profile_id}/check-ins/{check_in_id}/extract",
    response_model=FactExtractionResponse,
)
def extract_check_in_facts(profile_id: str, check_in_id: str, user: CurrentUser) -> FactExtractionResponse:
    _require_profile(profile_id)
    require_profile_access(profile_id, user, write=True)
    check_in = store.get_check_in(profile_id, check_in_id)
    if check_in is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Check-in not found")
    try:
        provider = GigaChatProvider(GigaChatSettings.from_env())
    except GigaChatConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GigaChat is not configured",
        ) from exc
    try:
        facts = provider.extract_facts(check_in.corrected_text or check_in.text)
    except (GigaChatRequestError, FactExtractionValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GigaChat extraction failed; no facts were saved",
        ) from exc
    finally:
        provider.close()
    current = store.get_check_in(profile_id, check_in_id)
    if current is None or current.text_revision != check_in.text_revision:
        raise _revision_conflict()
    return FactExtractionResponse(
        text_revision=check_in.text_revision,
        status="awaiting_confirmation",
        provider="gigachat",
        facts=[_fact_response(fact) for fact in facts],
    )


@app.post(
    "/api/v1/profiles/{profile_id}/check-ins/{check_in_id}/confirm",
    response_model=CheckInConfirmResponse,
)
def confirm_check_in_facts(
    profile_id: str,
    check_in_id: str,
    payload: CheckInConfirmRequest,
    user: CurrentUser,
) -> CheckInConfirmResponse:
    _require_profile(profile_id)
    require_profile_access(profile_id, user, write=True)
    check_in = store.get_check_in(profile_id, check_in_id)
    if check_in is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Check-in not found")
    source_text = check_in.corrected_text or check_in.text
    if payload.text_revision != check_in.text_revision or (
        payload.corrected_text is not None and payload.corrected_text != source_text
    ):
        raise _revision_conflict()
    try:
        facts = validate_confirmed_facts(
            source_text,
            [item.model_dump() for item in payload.facts],
        )
    except FactExtractionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Fact evidence must be present in the confirmed text",
        ) from exc
    try:
        facts = store.confirm_check_in(
            profile_id, check_in_id, corrected_text=payload.corrected_text,
            facts=facts, expected_revision=payload.text_revision,
        )
    except TextRevisionConflict as exc:
        raise _revision_conflict() from exc
    reviewed = store.get_check_in(profile_id, check_in_id)
    if reviewed is None or not reviewed.is_confirmed or reviewed.text_revision != payload.text_revision:
        raise _revision_conflict()
    safety_decision = evaluate_safety(facts)
    safety_event_response = None
    if safety_decision is not None:
        now = datetime.now(timezone.utc)
        safety_event = MonitoringEvent(
            status=MonitoringStatus.SAFETY,
            metric=None,
            z_score=None,
            evidence=safety_decision.evidence,
            message=safety_decision.message,
            algorithm_version=safety_decision.rule_version,
            level=safety_decision.level,
            period_start=check_in.created_at,
            period_end=now,
            text_provenance=tuple(fact_provenance(fact, rule_version=safety_decision.rule_version,
                                                 resolution="direct_confirmation") for fact in safety_decision.facts),
        )
        safety_event_response = _event_response(store.save_monitoring_event(profile_id, safety_event))
    return CheckInConfirmResponse(
        text_revision=payload.text_revision,
        confirmed_at=reviewed.confirmed_at,
        status="confirmed",
        check_in_id=check_in_id,
        facts=[_fact_response(fact) for fact in facts],
        safety_event=safety_event_response,
    )


@app.post(
    "/api/v1/profiles/{profile_id}/analysis",
    response_model=AnalysisResponse,
)
def analyze_profile(profile_id: str, user: CurrentUser, as_of: datetime | None = None) -> AnalysisResponse:
    _require_profile(profile_id)
    require_profile_access(profile_id, user)
    response, event = _analysis_for_profile(profile_id, as_of)
    store.save_monitoring_event(profile_id, event)
    return response


@app.get(
    "/api/v1/profiles/{profile_id}/events",
    response_model=list[MonitoringEventResponse],
)
def list_events(profile_id: str, user: CurrentUser) -> list[MonitoringEventResponse]:
    _require_profile(profile_id)
    require_profile_access(profile_id, user)
    return [_event_response(record) for record in store.list_monitoring_events(profile_id)]


@app.get(
    "/api/v1/profiles/{profile_id}/trends",
    response_model=list[TrendPointResponse],
)
def trends(
    profile_id: str,
    user: CurrentUser,
    metric: Metric = Query(Metric.SLEEP_HOURS),
    days: int = Query(28, ge=1, le=90),
    as_of: datetime | None = None,
) -> list[TrendPointResponse]:
    _require_profile(profile_id)
    require_profile_access(profile_id, user)
    cutoff = _analysis_cutoff(as_of)
    profile_timezone = store.get_profile_timezone(profile_id)
    observations = store.list_observations(profile_id)
    daily = aggregate_daily(observations, metric, as_of=cutoff, profile_timezone=profile_timezone)
    if not daily:
        return []
    # Default viewport ends on the latest available measurement day. An explicit
    # cutoff selects a historical calendar range ending on that local date.
    end = cutoff.astimezone(ZoneInfo(profile_timezone)).date() if as_of is not None else daily[-1].day
    start = end - timedelta(days=days - 1)
    event_records = store.list_monitoring_events(profile_id)
    points: list[TrendPointResponse] = []
    for observation in daily:
        if not start <= observation.day <= end:
            continue
        baseline = calculate_baseline(observations, metric, as_of=observation.measured_at,
                                      profile_timezone=profile_timezone)
        related_events = []
        for record in event_records:
            event = record.event
            if event.analysis_details is not None:
                current_ids = {id for item in event.analysis_details["metrics"]
                               if item["metric"] == metric.value
                               for id in item["source_observation_ids"]}
                related = bool(current_ids.intersection(observation.observation_ids))
            else:
                related = event.metric == metric and bool(
                    set(event.source_observation_ids).intersection(observation.observation_ids)
                )
            if related:
                related_events.append(record.id)
        points.append(TrendPointResponse(
            measured_at=observation.measured_at, value=observation.value,
            baseline=baseline.center, event_ids=related_events, day=observation.day,
            quality=observation.quality, source_observation_ids=list(observation.observation_ids),
            baseline_details=baseline_details(baseline),
        ))
    return points


@app.get("/api/v1/notifications", response_model=list[NotificationResponse])
def list_notifications(user: CurrentUser) -> list[NotificationResponse]:
    return [
        NotificationResponse(
            id=item.id,
            event_id=item.event_id,
            recipient_id=item.recipient_id,
            status=item.status,
            read_at=item.read_at,
            created_at=item.created_at,
        )
        for item in store.list_notifications(user.user_id)
    ]


@app.post("/api/v1/notifications/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(notification_id: str, user: CurrentUser) -> NotificationResponse:
    item = store.mark_notification_read(notification_id, user.user_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return NotificationResponse(
        id=item.id,
        event_id=item.event_id,
        recipient_id=item.recipient_id,
        status=item.status,
        read_at=item.read_at,
        created_at=item.created_at,
    )


@app.get(
    "/api/v1/caregiver/profiles/{profile_id}/summary",
    response_model=CaregiverSummaryResponse,
)
def caregiver_summary(profile_id: str, user: CurrentUser) -> CaregiverSummaryResponse:
    _require_profile(profile_id)
    if user.role != "caregiver":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Caregiver role required")
    require_profile_access(profile_id, user)
    observations = list_observations(profile_id, user)
    check_ins = list_check_ins(profile_id, user)
    latest_analysis = None
    if observations:
        latest_analysis, _ = _analysis_for_profile(profile_id)
    events = [_event_response(record) for record in store.list_monitoring_events(profile_id)]
    notifications = [
        NotificationResponse(
            id=item.id,
            event_id=item.event_id,
            recipient_id=item.recipient_id,
            status=item.status,
            read_at=item.read_at,
            created_at=item.created_at,
        )
        for item in store.list_notifications(user.user_id)
    ]
    return CaregiverSummaryResponse(
        profile={
            "id": PROFILE_ID,
            "display_name": "Демонстрационный профиль",
            "data_mode": "synthetic",
        },
        observations=observations,
        check_ins=check_ins,
        latest_analysis=latest_analysis,
        events=events,
        notifications=notifications,
    )
