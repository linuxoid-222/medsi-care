"""FastAPI entry point for the first manual-input vertical slice."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.auth import CurrentUser, authenticate, issue_token, require_profile_access
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
    analyze_observation,
    calculate_baseline,
    expected_unit,
)
from app.schemas import (
    AnalysisResponse,
    CaregiverSummaryResponse,
    CheckInConfirmRequest,
    CheckInConfirmResponse,
    CheckInCreate,
    CheckInResponse,
    FactExtractionResponse,
    LoginRequest,
    LoginResponse,
    ObservationCreate,
    ObservationResponse,
    SymptomFactResponse,
    TranscriptionResponse,
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
    )


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data_mode": "synthetic"}


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
    )
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
    return CheckInResponse(
        id=record.id,
        profile_id=record.profile_id,
        text=record.text,
        corrected_text=record.corrected_text,
        source=record.source,
        created_at=record.created_at,
        status="awaiting_analysis",
    )


@app.get(
    "/api/v1/profiles/{profile_id}/check-ins",
    response_model=list[CheckInResponse],
)
def list_check_ins(profile_id: str, user: CurrentUser) -> list[CheckInResponse]:
    _require_profile(profile_id)
    require_profile_access(profile_id, user)
    return [
        CheckInResponse(
            id=item.id,
            profile_id=item.profile_id,
            text=item.text,
            corrected_text=item.corrected_text,
            source=item.source,
            created_at=item.created_at,
            status=(
                "confirmed"
                if item.corrected_text or store.list_symptom_facts(item.id)
                else "awaiting_analysis"
            ),
        )
        for item in store.list_check_ins(profile_id)
    ]


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
        facts = provider.extract_facts(check_in.text)
    except (GigaChatRequestError, FactExtractionValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GigaChat extraction failed; no facts were saved",
        ) from exc
    finally:
        provider.close()
    return FactExtractionResponse(
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
    source_text = payload.corrected_text or check_in.corrected_text or check_in.text
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
    store.confirm_check_in(
        profile_id,
        check_in_id,
        corrected_text=payload.corrected_text or check_in.corrected_text,
        facts=facts,
    )
    return CheckInConfirmResponse(
        status="confirmed",
        check_in_id=check_in_id,
        facts=[_fact_response(fact) for fact in facts],
    )


@app.post(
    "/api/v1/profiles/{profile_id}/analysis",
    response_model=AnalysisResponse,
)
def analyze_profile(profile_id: str, user: CurrentUser) -> AnalysisResponse:
    _require_profile(profile_id)
    require_profile_access(profile_id, user)
    observations = store.list_observations(profile_id)
    if not observations:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No observations available for analysis",
        )
    latest = observations[-1]
    history = [item for item in observations if item.id != latest.id]
    baseline = calculate_baseline(history, latest.metric, as_of=latest.measured_at)
    event = analyze_observation(latest, baseline)
    return AnalysisResponse(
        status=event.status,
        metric=event.metric,
        z_score=event.z_score,
        evidence=list(event.evidence),
        message=event.message,
        algorithm_version=event.algorithm_version,
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
    latest_analysis = analyze_profile(profile_id, user) if observations else None
    return CaregiverSummaryResponse(
        profile={
            "id": PROFILE_ID,
            "display_name": "Демонстрационный профиль",
            "data_mode": "synthetic",
        },
        observations=observations,
        check_ins=check_ins,
        latest_analysis=latest_analysis,
    )
