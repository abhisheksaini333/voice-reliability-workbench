"""Bounded transport contracts: fixed PCM16 frames and explicit controls."""
from dataclasses import dataclass
import json
import struct

SAMPLE_RATE = 16000
FRAME_SAMPLES = 320
FRAME_BYTES = FRAME_SAMPLES * 2
MAX_SESSION_FRAMES = 180000  # One hour; clients must create a new session afterward.


class ProtocolError(ValueError):
    pass


def bounded_integer(value, name, maximum=2**31 - 1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ProtocolError(name + " must be a bounded nonnegative integer")
    return value


@dataclass(frozen=True)
class AudioFrame:
    sequence: int
    sample_offset: int
    pcm: bytes

    def __post_init__(self):
        bounded_integer(self.sequence, "sequence", MAX_SESSION_FRAMES - 1)
        bounded_integer(self.sample_offset, "sample_offset")
        if not isinstance(self.pcm, bytes) or len(self.pcm) != FRAME_BYTES:
            raise ProtocolError("audio must contain exactly 320 mono PCM16 samples")

    @property
    def capture_ms(self):
        return self.sample_offset * 1000 / SAMPLE_RATE

    def encode(self):
        return struct.pack("!II", self.sequence, self.sample_offset) + self.pcm

    @classmethod
    def decode(cls, raw):
        if not isinstance(raw, bytes) or len(raw) != FRAME_BYTES + 8:
            raise ProtocolError("invalid audio frame size")
        sequence, sample_offset = struct.unpack("!II", raw[:8])
        return cls(sequence, sample_offset, raw[8:])


class AudioSequence:
    def __init__(self):
        self.frames = 0

    def accept(self, frame):
        if (
            frame.sequence != self.frames
            or frame.sample_offset != self.frames * FRAME_SAMPLES
        ):
            raise ProtocolError("audio sequence or sample clock is discontinuous")
        self.frames += 1


def parse_control(raw):
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ProtocolError("control message is too large")
    try:
        message = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise ProtocolError("invalid control JSON") from error
    if not isinstance(message, dict):
        raise ProtocolError("control must be an object")
    kind = message.get("type")
    fields = {
        "start": set(),
        "stop": set(),
        "interrupt": set(),
        "handoff": set(),
        "close": set(),
        "ping": set(),
        "ack": {"epoch", "sequence"},
        "tool": {"service"},
    }
    if kind not in fields or set(message) != {"type"} | fields[kind]:
        raise ProtocolError("unknown control or unexpected fields")
    if kind == "ack":
        bounded_integer(message["epoch"], "epoch")
        bounded_integer(message["sequence"], "sequence")
    if kind == "tool" and message["service"] not in {"atlas", "beacon"}:
        raise ProtocolError("unknown demonstration service")
    return message
