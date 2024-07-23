"""Portable eSpeak NG synthesis via a bounded, cancellable subprocess."""
import io
import subprocess
import wave
from .provider_contracts import ProviderFailure, SpeechAudio


class EspeakSynthesizer:
    def __init__(self, binary):
        self.binary = str(binary)

    def synthesize(self, text, budget):
        budget.check()
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            raise ProviderFailure("invalid_speech_text")
        process = None
        try:
            process = subprocess.Popen(
                [self.binary, "--stdout", "-v", "en-us", "-s", "170", "--stdin"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            payload = text.encode("utf-8")
            while True:
                budget.check()
                try:
                    raw, _ = process.communicate(payload, timeout=0.05)
                    break
                except subprocess.TimeoutExpired:
                    payload = None
            budget.check()
            if process.returncode != 0 or len(raw) > 3_000_000:
                raise ProviderFailure("speech_failed")
            with wave.open(io.BytesIO(raw), "rb") as audio:
                if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                    raise ProviderFailure("invalid_speech_audio")
                pcm = audio.readframes(22050 * 30 + 1)
                return SpeechAudio(pcm, audio.getframerate())
        except (OSError, wave.Error) as error:
            raise ProviderFailure("speech_failed") from error
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate()
