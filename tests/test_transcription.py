import os
from pathlib import Path
import threading
import time
import unittest
import wave
from voice.transcription import WhisperRecognizer
from voice.provider_contracts import ProviderFailure, WorkBudget


class TranscriptionTests(unittest.TestCase):
    def test_invalid_audio_and_cancelled_work_fail_before_model_execution(self):
        recognizer = WhisperRecognizer(None, None)
        with self.assertRaises(ProviderFailure) as caught:
            recognizer.transcribe(
                b"odd", WorkBudget(threading.Event(), time.monotonic() + 1)
            )
        self.assertEqual(caught.exception.code, "invalid_audio")
        stop = threading.Event()
        stop.set()
        with self.assertRaises(ProviderFailure) as caught:
            recognizer.transcribe(
                b"\x00\x00" * 320, WorkBudget(stop, time.monotonic() + 1)
            )
        self.assertEqual(caught.exception.code, "cancelled")

    @unittest.skipUnless(
        os.getenv("VOICE_WHISPER_PATH"), "actual Whisper checkpoint not selected"
    )
    def test_actual_whisper_transcribes_synthesized_speech(self):
        recognizer = WhisperRecognizer.load(os.environ["VOICE_WHISPER_PATH"])
        path = Path(__file__).parents[1] / "fixtures/status.wav"
        with wave.open(str(path)) as source:
            pcm = source.readframes(source.getnframes())
        result = recognizer.transcribe(
            pcm, WorkBudget(threading.Event(), time.monotonic() + 20)
        )
        self.assertTrue(result["text"].strip())
        self.assertGreater(result["generated_tokens"], 1)
        self.assertGreater(result["latency_ms"], 0)
