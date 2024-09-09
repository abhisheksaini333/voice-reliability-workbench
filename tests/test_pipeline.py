import asyncio
import unittest
from voice.pipeline import TurnFrame, run_turn
from voice.provider_contracts import ProviderFailure, SpeechAudio
from voice.state import TurnIdentity


class Providers:
    def __init__(self):
        self.calls = []

    async def transcribe(self, identity, pcm, **options):
        self.calls.append("stt")
        return {"text": "hello"}

    async def respond(self, identity, text, context, **options):
        self.calls.append("model")
        return {"text": "Hello there."}

    async def synthesize(self, identity, text, **options):
        self.calls.append("tts")
        return SpeechAudio(bytes(22050), 22050)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_pipecat_processors_preserve_order_and_timings(self):
        provider = Providers()
        observed = []

        async def observe(stage, frame):
            observed.append(stage)

        frame = TurnFrame(TurnIdentity("session", 1, 2), bytes(640), [])
        await run_turn(frame, provider, lambda _: True, observe)
        self.assertEqual(provider.calls, ["stt", "model", "tts"])
        self.assertEqual(
            observed, ["stt_start", "stt", "model_start", "model", "tts_start", "tts"]
        )
        self.assertEqual(frame.reply, "Hello there.")
        self.assertEqual(set(frame.timings), {"stt_ms", "model_ms", "tts_ms"})

    async def test_invalidation_after_transcription_prevents_later_stages(self):
        provider = Providers()
        valid = True

        async def observe(stage, frame):
            nonlocal valid
            if stage == "stt":
                valid = False

        frame = TurnFrame(TurnIdentity("session", 1, 2), bytes(640), [])
        with self.assertRaises(asyncio.CancelledError):
            await run_turn(frame, provider, lambda _: valid, observe)
        self.assertEqual(provider.calls, ["stt"])

    async def test_provider_failure_leaves_no_waiting_pipeline_task(self):
        provider = Providers()

        async def broken(*args, **kwargs):
            raise ProviderFailure("provider_timeout")

        provider.respond = broken

        async def observe(stage, frame):
            pass

        frame = TurnFrame(TurnIdentity("session", 1, 2), bytes(640), [])
        with self.assertRaises(ProviderFailure):
            await asyncio.wait_for(
                run_turn(frame, provider, lambda _: True, observe), 0.2
            )
        self.assertEqual(provider.calls, ["stt"])
