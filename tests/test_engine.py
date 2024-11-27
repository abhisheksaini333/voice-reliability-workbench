import asyncio
import tempfile
import unittest
from pathlib import Path
from voice.engine import SessionEngine
from voice.state import SessionState
from voice.store import Store
from tests.test_pipeline import Providers


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "voice.sqlite")
        state = SessionState("session")
        self.store.create("session", "hash", state.snapshot())
        self.engine = SessionEngine(state, self.store, Providers())
        self.events = []

        async def emit(event):
            self.events.append(event)
            if event["type"] == "audio":
                await self.engine.playback_started(event["epoch"])
                await self.engine.playback.acknowledge(
                    event["epoch"], event["sequence"]
                )

        await self.engine.connect(emit)
        await self.engine.start()

    async def asyncTearDown(self):
        await self.engine.disconnect(self.engine.state.connection)
        self.store.close()
        self.directory.cleanup()

    async def test_durable_success_follows_actual_pipecat_and_playback_acknowledgements(
        self,
    ):
        await self.engine.begin_speech()
        task = self.engine.utterance(bytes(640))
        await task
        record = self.store.turns("session")[0]
        self.assertEqual(record["state"], "completed")
        self.assertEqual(record["transcript"], "hello")
        self.assertIn("first_audio_ms", record["timings"])
        self.assertEqual([e["type"] for e in self.events].count("completed"), 1)

    async def test_interruption_cancels_provider_and_never_emits_stale_audio(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def slow(*args, **kwargs):
            started.set()
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()

        self.engine.providers.respond = slow
        await self.engine.begin_speech()
        old = self.engine.utterance(bytes(640))
        await started.wait()
        await self.engine.interrupt()
        self.assertTrue(cancelled.is_set())
        self.assertTrue(old.done())
        self.assertFalse(any(e["type"] == "audio" for e in self.events))
        self.assertEqual(self.store.turns("session")[0]["state"], "cancelled")

    async def test_ledger_failure_emits_no_success_and_fails_closed(self):
        def unavailable(*args, **kwargs):
            raise OSError("private disk path")

        self.store.complete = unavailable
        await self.engine.begin_speech()
        await self.engine.utterance(bytes(640))
        self.assertFalse(self.engine.healthy)
        self.assertFalse(any(e["type"] == "completed" for e in self.events))
        self.assertNotIn("private disk path", str(self.events))
        with self.assertRaises(ValueError):
            await self.engine.start()

    async def test_reconnection_fences_old_disconnect_and_handoff_accepts_once(self):
        old = self.engine.state.connection
        await self.engine.connect(self.engine.emit)
        await self.engine.disconnect(old)
        self.assertTrue(self.engine.state.connected)
        self.assertFalse(self.engine.state.recording)
        await self.engine.handoff()
        epoch = self.engine.state.epoch
        await self.engine.accept_handoff(epoch)
        self.assertEqual(self.engine.state.phase, "operator")
        with self.assertRaises(ValueError):
            await self.engine.accept_handoff(epoch)

    async def test_closed_listener_does_not_poison_workspace_storage_health(self):
        from voice.playback import SlowConsumer

        async def closed(event):
            raise SlowConsumer("listener is gone")

        await self.engine.begin_speech()
        self.engine.emit = closed
        await self.engine.utterance(bytes(640))
        self.assertTrue(self.engine.healthy)
        self.assertEqual(self.store.turns("session")[0]["state"], "failed")

    async def test_slow_listener_receives_at_most_four_chunks_before_failure(self):
        from voice.provider_contracts import SpeechAudio

        async def long_speech(*args, **kwargs):
            return SpeechAudio(bytes(22050 * 2 * 2), 22050)

        self.engine.providers.synthesize = long_speech
        self.engine.playback.timeout = 0.03

        async def no_ack(event):
            self.events.append(event)

        self.engine.emit = no_ack
        await self.engine.begin_speech()
        await self.engine.utterance(bytes(640))
        self.assertEqual(len([e for e in self.events if e["type"] == "audio"]), 4)
        self.assertEqual(self.store.turns("session")[0]["error_code"], "slow_listener")
        self.assertTrue(self.engine.healthy)

    async def test_concurrent_reconnects_receive_distinct_connection_generations(self):
        started = asyncio.Event()

        async def slow(*args, **kwargs):
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.03)
                raise

        self.engine.providers.respond = slow
        await self.engine.begin_speech()
        self.engine.utterance(bytes(640))
        await started.wait()

        async def emit(event):
            pass

        first, second = await asyncio.gather(
            self.engine.connect(emit), self.engine.connect(emit)
        )
        self.assertNotEqual(first, second)
        await self.engine.disconnect(min(first, second))
        self.assertTrue(self.engine.state.connected)
