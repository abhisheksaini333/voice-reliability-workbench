"""Shared provider deadlines and bounded raw audio results."""
from dataclasses import dataclass
import threading
import time


class ProviderFailure(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WorkBudget:
    stop: threading.Event
    deadline: float

    def expired(self):
        return self.stop.is_set() or time.monotonic() >= self.deadline

    def check(self):
        if self.stop.is_set():
            raise ProviderFailure("cancelled")
        if time.monotonic() >= self.deadline:
            raise ProviderFailure("provider_timeout")


@dataclass(frozen=True)
class SpeechAudio:
    pcm: bytes
    sample_rate: int

    def __post_init__(self):
        if (
            self.sample_rate != 22050
            or not self.pcm
            or len(self.pcm) % 2
            or len(self.pcm) > self.sample_rate * 2 * 30
        ):
            raise ProviderFailure("invalid_speech_audio")

    @property
    def duration_ms(self):
        return len(self.pcm) * 1000 / (2 * self.sample_rate)
