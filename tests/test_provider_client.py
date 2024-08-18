import unittest
from aiohttp.test_utils import TestClient, TestServer
from voice.provider_api import create_provider_app
from voice.provider_client import ProviderClient
from voice.provider_contracts import ProviderFailure
from test_provider_api import (
    KEY,
    ControlledRecognizer,
    ControlledResponder,
    ControlledSynthesizer,
)


class ProviderClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = TestServer(
            create_provider_app(
                ControlledRecognizer(),
                ControlledResponder(),
                ControlledSynthesizer(),
                KEY,
                allow_faults=True,
            )
        )
        await self.server.start_server()
        self.client = ProviderClient(str(self.server.make_url("")).rstrip("/"), KEY)

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_real_http_client_validates_all_stage_results(self):
        transcript = await self.client.transcribe("audio", b"\x00\x00" * 320)
        self.assertEqual(transcript["text"], "recognized")
        response = await self.client.respond("model", "hello", [])
        self.assertEqual(response["text"], "response")
        audio = await self.client.synthesize("speech", "hello")
        self.assertEqual(audio.sample_rate, 22050)
        self.assertEqual(len(audio.pcm), 4410)

    async def test_slow_provider_fails_with_a_safe_explicit_code(self):
        with self.assertRaises(ProviderFailure) as caught:
            await self.client.transcribe(
                "slow", b"\x00\x00" * 320, timeout_ms=50, delay_ms=200
            )
        self.assertEqual(caught.exception.code, "provider_timeout")
