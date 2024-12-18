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

    async def test_pending_authentication_reserves_capacity_and_releases_on_failure(
        self,
    ):
        import aiohttp

        identities = []
        for _ in range(5):
            response = await self.client.post(
                "/api/sessions", headers={"Authorization": "Bearer " + "w" * 40}
            )
            identities.append(await response.json())
        sockets = [
            await self.client.ws_connect("/api/sessions/" + item["id"] + "/audio")
            for item in identities[:4]
        ]
        with self.assertRaises(aiohttp.WSServerHandshakeError) as rejected:
            await self.client.ws_connect(
                "/api/sessions/" + identities[4]["id"] + "/audio"
            )
        self.assertEqual(rejected.exception.status, 503)
        await sockets[0].send_json({"type": "authenticate", "token": "wrong"})
        await sockets[0].receive()
        replacement = await self.client.ws_connect(
            "/api/sessions/" + identities[4]["id"] + "/audio"
        )
        sockets[0] = replacement
        identities[0] = identities[4]
        await asyncio.gather(
            *(
                ws.send_json({"type": "authenticate", "token": item["token"]})
                for ws, item in zip(sockets, identities)
            )
        )
        states = await asyncio.gather(*(ws.receive_json() for ws in sockets))
        self.assertEqual(len(states), 4)
        # Replacing an admitted session keeps its slot and cannot close a newer socket.
        updated = await self.client.ws_connect(
            "/api/sessions/" + identities[0]["id"] + "/audio"
        )
        await updated.send_json(
            {"type": "authenticate", "token": identities[0]["token"]}
        )
        self.assertTrue((await updated.receive_json())["connected"])
        await updated.send_json({"type": "ping"})
        self.assertEqual((await updated.receive_json())["type"], "pong")
        await updated.close()
        for ws in sockets:
            await ws.close()

    async def test_deep_authentication_json_is_rejected_without_poisoning_health(self):
        ws = await self.client.ws_connect(
            "/api/sessions/" + self.session["id"] + "/audio"
        )
        await ws.send_str("[" * 1100 + "]" * 1100)
        message = await ws.receive()
        self.assertEqual(message.type.name, "CLOSE")
        self.assertEqual(message.data, 1008)
        self.assertEqual((await self.client.get("/health")).status, 200)
