import asyncio
import tempfile
import unittest
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer
from voice.api import create_app
from tests.test_pipeline import Providers


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        provider = Providers()

        async def healthy():
            return True

        async def close():
            pass

        provider.healthy = healthy
        provider.close = close
        self.client = TestClient(
            TestServer(
                create_app(
                    Path(self.directory.name) / "voice.sqlite",
                    "w" * 40,
                    "o" * 40,
                    provider_factory=lambda: provider,
                    allow_faults=True,
                )
            )
        )
        await self.client.start_server()
        response = await self.client.post(
            "/api/sessions", headers={"Authorization": "Bearer " + "w" * 40}
        )
        self.session = await response.json()

    async def asyncTearDown(self):
        await self.client.close()
        self.directory.cleanup()

    async def test_credentials_are_scoped_and_transcript_does_not_expose_hash(self):
        self.assertEqual((await self.client.get("/health")).status, 200)
        self.assertEqual((await self.client.post("/api/sessions")).status, 401)
        self.assertEqual(
            (
                await self.client.get(
                    "/api/operator/sessions",
                    headers={"Authorization": "Bearer " + "w" * 40},
                )
            ).status,
            401,
        )
        response = await self.client.get(
            "/api/sessions/" + self.session["id"],
            headers={"Authorization": "Bearer " + self.session["token"]},
        )
        self.assertEqual(response.status, 200)
        self.assertNotIn("token_hash", await response.text())
        response = await self.client.post(
            "/api/sessions",
            headers={
                "Authorization": "Bearer " + "w" * 40,
                "Origin": "https://untrusted.example",
            },
        )
        self.assertEqual(response.status, 403)

    async def test_websocket_requires_first_message_auth_and_handoff_is_observable(
        self,
    ):
        ws = await self.client.ws_connect(
            "/api/sessions/" + self.session["id"] + "/audio"
        )
        await ws.send_json({"type": "authenticate", "token": self.session["token"]})
        self.assertEqual((await ws.receive_json())["type"], "state")
        await ws.send_json({"type": "start"})
        self.assertTrue((await ws.receive_json())["recording"])
        await ws.send_json({"type": "handoff"})
        self.assertEqual((await ws.receive_json())["type"], "stop_audio")
        state = await ws.receive_json()
        self.assertEqual(state["phase"], "handoff_pending")
        response = await self.client.post(
            "/api/operator/sessions/" + self.session["id"] + "/accept",
            json={"epoch": state["epoch"]},
            headers={"Authorization": "Bearer " + "o" * 40},
        )
        self.assertEqual(response.status, 200)
        await ws.close()
        response = await self.client.post(
            "/api/operator/sessions/" + self.session["id"] + "/accept",
            json={"epoch": state["epoch"]},
            headers={"Authorization": "Bearer " + "o" * 40},
        )
        self.assertEqual(response.status, 409)

    async def test_wrong_websocket_token_closes_without_sending_state(self):
        ws = await self.client.ws_connect(
            "/api/sessions/" + self.session["id"] + "/audio"
        )
        await ws.send_json({"type": "authenticate", "token": "invalid"})
        message = await ws.receive()
        self.assertEqual(message.type.name, "CLOSE")
        self.assertEqual(message.data, 1008)

    async def test_connection_replacement_requires_new_consent_and_survives_old_cleanup(
        self,
    ):
        path = "/api/sessions/" + self.session["id"] + "/audio"
        first = await self.client.ws_connect(path)
        auth = {"type": "authenticate", "token": self.session["token"]}
        await first.send_json(auth)
        await first.receive_json()
        await first.send_json({"type": "start"})
        await first.receive_json()
        second = await self.client.ws_connect(path)
        await second.send_json(auth)
        state = await asyncio.wait_for(second.receive_json(), 2)
        self.assertFalse(state["recording"])
        await second.send_json({"type": "ping"})
        self.assertEqual((await second.receive_json())["type"], "pong")
        await second.close()
        await first.close()

    async def test_unpaced_audio_burst_is_closed_at_bounded_input_queue(self):
        from voice.contracts import AudioFrame

        ws = await self.client.ws_connect(
            "/api/sessions/" + self.session["id"] + "/audio"
        )
        await ws.send_json({"type": "authenticate", "token": self.session["token"]})
        await ws.receive_json()
        await ws.send_json({"type": "start"})
        await ws.receive_json()
        for sequence in range(200):
            try:
                await ws.send_bytes(
                    AudioFrame(sequence, sequence * 320, bytes(640)).encode()
                )
            except ConnectionResetError:
                break
        message = await asyncio.wait_for(ws.receive(), 2)
        self.assertEqual(message.type.name, "CLOSE")
        self.assertEqual(message.data, 1013)
