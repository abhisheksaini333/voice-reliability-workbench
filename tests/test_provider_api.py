import base64
import unittest
from aiohttp.test_utils import TestClient, TestServer
from voice.provider_api import create_provider_app
from voice.provider_contracts import SpeechAudio

KEY = "provider-test-credential-which-is-long-enough"


class ControlledRecognizer:
    def transcribe(self, pcm, budget):
        return {"text": "recognized", "latency_ms": 1, "generated_tokens": 1}


class ControlledResponder:
    def reply(self, text, context, budget):
        return {
            "text": "response",
            "input_tokens": 1,
            "output_tokens": 1,
            "latency_ms": 1,
        }


class ControlledSynthesizer:
    def synthesize(self, text, budget):
        return SpeechAudio(b"\x00\x00" * 2205, 22050)


class ProviderApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(
            TestServer(
                create_provider_app(
                    ControlledRecognizer(),
                    ControlledResponder(),
                    ControlledSynthesizer(),
                    KEY,
                    allow_faults=True,
                )
            )
        )
        await self.client.start_server()
        self.headers = {"Authorization": "Bearer " + KEY}

    async def asyncTearDown(self):
        await self.client.close()

    async def test_authorization_contract_and_duplicate_job(self):
        self.assertEqual((await self.client.get("/status")).status, 401)
        body = {
            "id": "one",
            "timeout_ms": 1000,
            "pcm": base64.b64encode(b"\x00\x00" * 320).decode(),
        }
        response = await self.client.post(
            "/transcribe", json=body, headers=self.headers
        )
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["text"], "recognized")
        duplicate = await self.client.post(
            "/transcribe", json=body, headers=self.headers
        )
        self.assertEqual(duplicate.status, 409)
        body["id"] = "two"
        body["extra"] = "not allowed"
        self.assertEqual(
            (
                await self.client.post("/transcribe", json=body, headers=self.headers)
            ).status,
            400,
        )

    async def test_injected_delay_reaches_bounded_timeout_and_releases_real_thread(
        self,
    ):
        body = {
            "id": "slow",
            "timeout_ms": 50,
            "text": "hello",
            "context": [],
            "delay_ms": 200,
        }
        response = await self.client.post("/respond", json=body, headers=self.headers)
        self.assertEqual(response.status, 504)
        self.assertEqual((await response.json())["error"], "provider_timeout")
        status = await self.client.get("/status", headers=self.headers)
        self.assertEqual((await status.json())["active"], 0)
