"""Session orchestration: durable epochs fence providers, tools and playback."""
import asyncio
import base64
import time
from .audio import VoiceDetector
from .contracts import AudioFrame, AudioSequence
from .pipeline import TurnFrame, run_turn
from .playback import PlaybackWindow, SlowConsumer, StaleAudio
from .provider_contracts import ProviderFailure
from .state import TurnIdentity
from .store import redact
from .tools import ToolManager, service_status


async def discard(event):
    pass


class SessionEngine:
    def __init__(self, state, store, providers, *, allow_faults=False):
        self.state = state
        self.store = store
        self.providers = providers
        self.allow_faults = allow_faults
        self.fault = None
        self.healthy = True
        self.emit = discard
        self.detector = VoiceDetector()
        self.sequence = AudioSequence()
        self.playback = PlaybackWindow()
        self.tools = ToolManager(state.current)
        self.turn_task = None
        self.tool_task = None
        self.identity = None
        self.frame = None
        self.utterance_ended = None
        self.interrupted_at = None

    def persist(self):
        if not self.healthy:
            raise ValueError("workspace storage is unavailable")
        try:
            if not self.store.save_state(self.state.snapshot()):
                raise ValueError("session state is stale")
        except Exception:
            self.healthy = False
            raise

    async def publish(self, event):
        try:
            await self.emit(event)
            return True
        except SlowConsumer:
            return False

    async def snapshot(self):
        await self.publish(dict(type="state", **self.state.snapshot()))

    def event(self, kind, **detail):
        self.store.event(self.state.session_id, self.state.epoch, kind, detail)

    async def _cancel_work(self):
        self.tools.cancel_stale()
        tasks = [
            task
            for task in (self.turn_task, self.tool_task)
            if task and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.turn_task = self.tool_task = None

    async def _flush(self):
        self.persist()
        await self.playback.reset(self.state.epoch)
        self.interrupted_at = time.monotonic()
        await self.publish(dict(type="stop_audio", epoch=self.state.epoch))
        await self.snapshot()
        await self._cancel_work()

    async def connect(self, emit):
        # Invalidate first, tell any old browser to stop, then replace the sender.
        self.state.connect()
        await self._flush()
        self.emit = emit
        self.detector = VoiceDetector()
        self.sequence = AudioSequence()
        self.event("connected", connection=self.state.connection)
        await self.snapshot()
        return self.state.connection

    async def start(self):
        if not self.healthy:
            raise ValueError("workspace storage is unavailable")
        if self.state.recording:
            return
        self.state.start()
        self.detector = VoiceDetector()
        self.sequence = AudioSequence()
        self.persist()
        self.event("recording_started")
        await self.snapshot()

    async def begin_speech(self):
        self.identity = self.state.begin_turn()
        await self._flush()
        self.store.begin_turn(self.identity)
        self.event("speech_started")
        await self.emit(dict(type="speech", epoch=self.state.epoch))

    async def receive_audio(self, raw):
        if not self.state.recording or not self.healthy:
            return
        frame = AudioFrame.decode(raw)
        self.sequence.accept(frame)
        for event in self.detector.feed(frame):
            if event.kind == "speech_start":
                await self.begin_speech()
            elif self.identity and self.state.current(self.identity):
                self.event(
                    "utterance",
                    capture_start_ms=event.start_sample / 16,
                    capture_end_ms=event.detected_sample / 16,
                    truncated=event.truncated,
                )
                self.utterance(event.pcm)

    def context(self):
        messages = []
        for turn in self.store.turns(self.state.session_id)[-3:]:
            if turn["state"] == "completed":
                if turn["transcript"]:
                    messages.append(
                        dict(role="user", content=turn["transcript"][:1000])
                    )
                if turn["reply"]:
                    messages.append(
                        dict(role="assistant", content=turn["reply"][:1000])
                    )
        return messages[-6:]

    def utterance(self, pcm):
        if not self.identity or not self.state.current(self.identity):
            raise ValueError("current speech turn required")
        if self.turn_task and not self.turn_task.done():
            raise ValueError("one utterance is allowed per turn")
        self.frame = TurnFrame(self.identity, pcm, self.context())
        self.utterance_ended = time.monotonic()
        self.turn_task = asyncio.create_task(self._run(self.frame))
        return self.turn_task

    async def observe(self, stage, frame):
        if not self.state.current(frame.identity):
            raise asyncio.CancelledError
        if stage.endswith("_start"):
            self.state.advance(frame.identity, "thinking")
            self.persist()
            await self.snapshot()
        elif stage == "stt":
            if not self.store.transcribe(frame.identity, frame.transcript):
                raise asyncio.CancelledError
            await self.emit(
                dict(
                    type="transcript",
                    epoch=frame.identity.epoch,
                    text=redact(frame.transcript),
                )
            )
        elif stage == "model":
            if not self.store.draft_reply(frame.identity, frame.reply):
                raise asyncio.CancelledError
            await self.emit(
                dict(type="reply", epoch=frame.identity.epoch, text=redact(frame.reply))
            )
        self.event("stage", stage=stage)
        await self.emit(dict(type="stage", epoch=frame.identity.epoch, stage=stage))

    async def playback_started(self, epoch):
        if (
            self.frame
            and self.state.current(self.frame.identity)
            and epoch == self.frame.identity.epoch
            and self.utterance_ended is not None
            and "first_audio_ms" not in self.frame.timings
        ):
            self.frame.timings["first_audio_ms"] = (
                time.monotonic() - self.utterance_ended
            ) * 1000
            self.event(
                "playback_started", first_audio_ms=self.frame.timings["first_audio_ms"]
            )

    async def playback_stopped(self, epoch):
        if epoch == self.state.epoch and self.interrupted_at is not None:
            self.event(
                "playback_stopped",
                interruption_ms=(time.monotonic() - self.interrupted_at) * 1000,
            )
            self.interrupted_at = None

    async def _play(self, frame):
        self.state.advance(frame.identity, "speaking")
        self.persist()
        await self.snapshot()
        # 250ms per chunk; at most four unacknowledged chunks = one second.
        chunk_bytes = (frame.audio.sample_rate // 4) * 2
        for offset in range(0, len(frame.audio.pcm), chunk_bytes):
            sequence = await self.playback.reserve(frame.identity.epoch)
            if not self.state.current(frame.identity):
                raise asyncio.CancelledError
            await self.emit(
                dict(
                    type="audio",
                    epoch=frame.identity.epoch,
                    sequence=sequence,
                    sample_rate=frame.audio.sample_rate,
                    pcm=base64.b64encode(
                        frame.audio.pcm[offset : offset + chunk_bytes]
                    ).decode(),
                )
            )
        await self.playback.drain(frame.identity.epoch)

    async def _run(self, frame):
        try:
            await run_turn(
                frame,
                self.providers,
                self.state.current,
                self.observe,
                self.fault if self.fault != "tool" else None,
            )
            await self._play(frame)
            frame.timings["total_ms"] = (time.monotonic() - self.utterance_ended) * 1000
            if not self.store.complete(frame.identity, frame.reply, frame.timings):
                raise asyncio.CancelledError
            self.state.advance(
                frame.identity, "listening" if self.state.recording else "idle"
            )
            self.persist()
            await self.emit(
                dict(
                    type="completed", epoch=frame.identity.epoch, timings=frame.timings
                )
            )
            await self.snapshot()
        except (asyncio.CancelledError, StaleAudio):
            # Epoch advancement has already durably invalidated this turn.
            pass
        except (ProviderFailure, SlowConsumer) as error:
            code = error.code if isinstance(error, ProviderFailure) else "slow_listener"
            await self._fail(frame, code)
        except Exception:
            # Storage failures are fail-closed; raw exception strings never enter traces.
            self.healthy = False
            self.state.stop()
            await self.playback.reset(self.state.epoch)
            await self.publish(dict(type="stop_audio", epoch=self.state.epoch))
            await self.publish(dict(type="error", code="workspace_unavailable"))

    async def _fail(self, frame, code):
        if not self.state.current(frame.identity):
            return
        try:
            self.store.complete(
                frame.identity, frame.reply, frame.timings, error_code=code
            )
            self.state.interrupt()
            self.persist()
            self.event("failed", code=code)
        except Exception:
            self.healthy = False
            self.state.stop()
            code = "workspace_unavailable"
        finally:
            await self.playback.reset(self.state.epoch)
        await self.publish(dict(type="stop_audio", epoch=self.state.epoch))
        await self.publish(dict(type="error", code=code))
        await self.snapshot()

    async def interrupt(self):
        self.state.interrupt()
        self.detector = VoiceDetector()
        await self._flush()
        self.event("interrupted")

    async def stop(self):
        self.state.stop()
        self.detector = VoiceDetector()
        await self._flush()
        self.event("recording_stopped")

    async def handoff(self):
        self.state.request_handoff()
        await self._flush()
        self.event("handoff_requested")

    async def accept_handoff(self, epoch):
        self.state.accept_handoff(epoch)
        await self._flush()
        self.event("handoff_accepted")

    async def close(self):
        self.state.close()
        await self._flush()
        self.event("closed")

    async def disconnect(self, connection):
        if connection != self.state.connection:
            return
        self.emit = discard
        self.state.disconnect()
        try:
            if self.healthy:
                self.persist()
                self.event("disconnected")
        finally:
            await self.playback.reset(self.state.epoch)
            await self._cancel_work()

    def set_fault(self, stage):
        if not self.allow_faults or stage not in (
            "none",
            "stt",
            "model",
            "tts",
            "tool",
        ):
            raise ValueError("diagnostic faults are unavailable")
        self.fault = None if stage == "none" else stage
        self.event("fault_selected", stage=stage)

    async def request_tool(self, service):
        if self.tool_task and not self.tool_task.done():
            raise ValueError("a tool is already running")
        identity = TurnIdentity(
            self.state.session_id, self.state.connection, self.state.epoch
        )
        receipt = self.tools.issue(
            identity, service, timeout=0.15 if self.fault == "tool" else 2
        )

        async def operation(name):
            if self.fault == "tool":
                await asyncio.sleep(1)
            return await service_status(name)

        async def execute():
            result = await self.tools.execute(receipt, operation)
            if self.state.current(identity):
                self.event(
                    "tool",
                    receipt_id=receipt.id,
                    service=service,
                    state=receipt.state,
                    status=receipt.result["status"] if receipt.result else None,
                )
                await self.emit(dict(type="tool", **result))

        self.tool_task = asyncio.create_task(execute())
        return receipt.id
