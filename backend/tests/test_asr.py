from io import BytesIO
from unittest import TestCase

from app.ai.asr import (
    ASRInputError,
    ASRSettings,
    FasterWhisperTranscriber,
    validate_audio_filename,
)


class _Segment:
    def __init__(self, text: str) -> None:
        self.text = text


class _Info:
    language = "ru"
    duration = 2.5


class _FakeModel:
    def transcribe(self, audio, **kwargs):
        assert kwargs["language"] == "ru"
        assert kwargs["vad_filter"] is True
        return iter([_Segment(" Сегодня"), _Segment(" чувствую себя лучше ")]), _Info()


class ASRAdapterTests(TestCase):
    def test_transcriber_uses_local_model_contract_without_downloading_one(self) -> None:
        transcriber = FasterWhisperTranscriber(
            ASRSettings(model="synthetic-fake"),
            model_factory=lambda *args, **kwargs: _FakeModel(),
        )
        result = transcriber.transcribe(BytesIO(b"synthetic-audio"))
        self.assertEqual(result.text, "Сегодня чувствую себя лучше")
        self.assertEqual(result.language, "ru")
        self.assertEqual(result.duration_seconds, 2.5)

    def test_empty_model_output_is_rejected(self) -> None:
        class EmptyModel:
            def transcribe(self, audio, **kwargs):
                return iter(()), _Info()

        transcriber = FasterWhisperTranscriber(
            ASRSettings(), model_factory=lambda *args, **kwargs: EmptyModel()
        )
        with self.assertRaises(ASRInputError):
            transcriber.transcribe(BytesIO(b"synthetic-audio"))

    def test_unsupported_extension_is_rejected(self) -> None:
        with self.assertRaises(ASRInputError):
            validate_audio_filename("recording.exe")
