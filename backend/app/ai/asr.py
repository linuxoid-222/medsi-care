"""Local Russian speech-to-text adapter backed by faster-whisper."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable


class ASRConfigurationError(RuntimeError):
    """Raised when local ASR configuration is invalid."""


class ASRInputError(RuntimeError):
    """Raised when an uploaded audio input is empty or unsupported."""


class ASRProcessingError(RuntimeError):
    """Raised when faster-whisper cannot process an audio file."""


@dataclass(frozen=True, slots=True)
class ASRSettings:
    model: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "ru"
    max_audio_bytes: int = 25_000_000

    @classmethod
    def from_env(cls) -> "ASRSettings":
        try:
            max_audio_bytes = int(os.getenv("FASTER_WHISPER_MAX_AUDIO_BYTES", "25000000"))
        except ValueError as exc:
            raise ASRConfigurationError("FASTER_WHISPER_MAX_AUDIO_BYTES must be an integer") from exc
        if max_audio_bytes <= 0:
            raise ASRConfigurationError("FASTER_WHISPER_MAX_AUDIO_BYTES must be positive")
        return cls(
            model=os.getenv("FASTER_WHISPER_MODEL", "base").strip() or "base",
            device=os.getenv("FASTER_WHISPER_DEVICE", "cpu").strip() or "cpu",
            compute_type=os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
            language=os.getenv("FASTER_WHISPER_LANGUAGE", "ru").strip() or "ru",
            max_audio_bytes=max_audio_bytes,
        )


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str
    duration_seconds: float | None
    provider: str = "faster-whisper"


ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}


def validate_audio_filename(filename: str | None) -> None:
    if not filename:
        return
    suffix = Path(filename).suffix.lower()
    if suffix and suffix not in ALLOWED_AUDIO_SUFFIXES:
        raise ASRInputError("Unsupported audio format")


class FasterWhisperTranscriber:
    def __init__(
        self,
        settings: ASRSettings,
        *,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self._model_factory = model_factory
        self._model: Any | None = None

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        factory = self._model_factory
        if factory is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise ASRConfigurationError("faster-whisper is not installed") from exc
            factory = WhisperModel
        try:
            self._model = factory(
                self.settings.model,
                device=self.settings.device,
                compute_type=self.settings.compute_type,
            )
        except Exception as exc:  # model loading errors vary by backend
            raise ASRProcessingError("faster-whisper model could not be loaded") from exc
        return self._model

    def transcribe(self, audio: str | Path | BinaryIO) -> Transcript:
        model = self._get_model()
        try:
            segments, info = model.transcribe(
                audio,
                language=self.settings.language,
                vad_filter=True,
                beam_size=5,
            )
            text = " ".join(
                segment.text.strip()
                for segment in segments
                if getattr(segment, "text", "").strip()
            ).strip()
        except Exception as exc:  # backend/codec errors vary by input
            raise ASRProcessingError("Audio transcription failed") from exc
        if not text:
            raise ASRInputError("No speech detected in audio")
        language = str(getattr(info, "language", self.settings.language) or self.settings.language)
        duration = getattr(info, "duration", None)
        return Transcript(
            text=text,
            language=language,
            duration_seconds=float(duration) if duration is not None else None,
        )


def build_transcriber() -> FasterWhisperTranscriber:
    return FasterWhisperTranscriber(ASRSettings.from_env())
