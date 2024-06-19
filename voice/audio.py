"""Deterministic energy VAD with hysteresis and bounded utterance storage."""
from collections import deque
from dataclasses import dataclass
import math
import struct
from .contracts import FRAME_SAMPLES


def pcm_rms(pcm):
    if not pcm or len(pcm) % 2:
        raise ValueError("nonempty PCM16 samples required")
    energy = sum(sample[0] ** 2 for sample in struct.iter_unpack("<h", pcm))
    return math.sqrt(energy / (len(pcm) // 2)) / 32768


@dataclass(frozen=True)
class SpeechEvent:
    kind: str
    start_sample: int
    detected_sample: int
    pcm: bytes = b""
    truncated: bool = False


class VoiceDetector:
    def __init__(
        self,
        threshold=0.018,
        attack_frames=3,
        silence_frames=20,
        preroll_frames=10,
        max_frames=600,
    ):
        if (
            not 0 < threshold < 1
            or min(attack_frames, silence_frames, preroll_frames) < 1
        ):
            raise ValueError("positive VAD bounds required")
        if not attack_frames <= preroll_frames <= max_frames <= 1500:
            raise ValueError("invalid VAD buffering bounds")
        self.threshold = threshold
        self.attack_frames = attack_frames
        self.silence_frames = silence_frames
        self.max_frames = max_frames
        self.preroll = deque(maxlen=preroll_frames)
        self.captured = []
        self.active = False
        self.voiced = self.quiet = 0

    @property
    def buffered_frames(self):
        return len(self.captured) + len(self.preroll)

    def feed(self, frame):
        voiced = pcm_rms(frame.pcm) >= self.threshold
        if not self.active:
            self.preroll.append(frame)
            self.voiced = self.voiced + 1 if voiced else 0
            if self.voiced < self.attack_frames:
                return []
            self.active = True
            self.captured = list(self.preroll)
            self.preroll.clear()
            self.quiet = 0
            return [
                SpeechEvent(
                    "speech_start", self.captured[0].sample_offset, frame.sample_offset
                )
            ]
        self.captured.append(frame)
        self.quiet = 0 if voiced else self.quiet + 1
        if len(self.captured) >= self.max_frames:
            return [self.flush(truncated=True)]
        if self.quiet >= self.silence_frames:
            return [self.flush()]
        return []

    def flush(self, truncated=False):
        if not self.active:
            self.preroll.clear()
            self.voiced = 0
            return None
        event = SpeechEvent(
            "utterance",
            self.captured[0].sample_offset,
            self.captured[-1].sample_offset + FRAME_SAMPLES,
            b"".join(frame.pcm for frame in self.captured),
            truncated,
        )
        self.captured.clear()
        self.preroll.clear()
        self.active = False
        self.voiced = self.quiet = 0
        return event
