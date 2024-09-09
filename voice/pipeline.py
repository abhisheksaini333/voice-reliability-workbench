"""One bounded utterance traverses actual Pipecat processors without an input backlog."""
import asyncio
from dataclasses import dataclass, field
import hashlib
import time
from pipecat.frames.frames import Frame, StartFrame, EndFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from .provider_contracts import SpeechAudio
from .state import TurnIdentity


@dataclass
class TurnFrame(Frame):
    identity: TurnIdentity
    pcm: bytes
    context: list
    transcript: str = ""
    reply: str = ""
    audio: SpeechAudio | None = None
    timings: dict = field(default_factory=dict)

    def job_id(self, stage):
        value = f"{self.identity.session_id}:{self.identity.connection}:{self.identity.epoch}:{stage}"
        return hashlib.sha256(value.encode()).hexdigest()


class VoiceStage(FrameProcessor):
    def __init__(self, stage, providers, current, observe, fault):
        super().__init__()
        self.stage = stage
        self.providers = providers
        self.current = current
        self.observe = observe
        self.fault = fault

    async def process_frame(self, frame, direction):
        if isinstance(frame, TurnFrame):
            if not self.current(frame.identity):
                raise asyncio.CancelledError
            await self.observe(self.stage + "_start", frame)
            started = time.monotonic()
            options = {}
            if self.fault == self.stage:
                options = dict(timeout_ms=150, delay_ms=1000)
            identity = frame.job_id(self.stage)
            if self.stage == "stt":
                result = await self.providers.transcribe(identity, frame.pcm, **options)
                frame.transcript = result["text"]
            elif self.stage == "model":
                result = await self.providers.respond(
                    identity, frame.transcript, frame.context, **options
                )
                frame.reply = result["text"]
            else:
                frame.audio = await self.providers.synthesize(
                    identity, frame.reply, **options
                )
            if not self.current(frame.identity):
                raise asyncio.CancelledError
            frame.timings[self.stage + "_ms"] = (time.monotonic() - started) * 1000
            await self.observe(self.stage, frame)
        await self.push_frame(frame, direction)


async def run_turn(frame, providers, current, observe, fault=None):
    if fault not in (None, "stt", "model", "tts"):
        raise ValueError("unknown provider fault")
    pipeline = Pipeline(
        [
            VoiceStage(stage, providers, current, observe, fault)
            for stage in ("stt", "model", "tts")
        ]
    )
    try:
        # Direct flow gives one in-flight utterance and preserves Pipecat's frame
        # lifecycle without its unbounded task input queue.
        await pipeline.process_frame(StartFrame(), FrameDirection.DOWNSTREAM)
        await pipeline.process_frame(frame, FrameDirection.DOWNSTREAM)
        await pipeline.process_frame(EndFrame(), FrameDirection.DOWNSTREAM)
    finally:
        await pipeline.cleanup()
    return frame
