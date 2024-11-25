"""Kill an isolated live API during captured speech and verify SQLite recovery."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import time
import aiohttp
from voice.backup import backup_database
from voice.contracts import AudioFrame
from voice.store import Store


async def run(directory):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    workspace, operator, provider = (secrets.token_urlsafe(32) for _ in range(3))
    environment = dict(
        os.environ,
        VOICE_WORKSPACE_KEY=workspace,
        VOICE_OPERATOR_KEY=operator,
        VOICE_PROVIDER_KEY=provider,
        VOICE_PROVIDER_URL="http://127.0.0.1:9",
        VOICE_DATABASE=str(directory / "voice.sqlite"),
    )
    processes = []

    async def start(client):
        process = subprocess.Popen(
            [sys.executable, "-m", "voice.api", "--port", str(port)],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        processes.append(process)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("isolated API failed to start")
            try:
                async with client.get(url + "/api/config") as response:
                    if response.status == 200:
                        return process
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(0.05)
        raise TimeoutError("isolated API startup deadline")

    try:
        async with aiohttp.ClientSession() as client:
            first = await start(client)
            async with client.post(
                url + "/api/sessions", headers={"Authorization": "Bearer " + workspace}
            ) as response:
                identity = await response.json()
            ws = await client.ws_connect(
                url + "/api/sessions/" + identity["id"] + "/audio"
            )
            await ws.send_json({"type": "authenticate", "token": identity["token"]})
            await ws.receive_json()
            await ws.send_json({"type": "start"})
            await ws.receive_json()
            for sequence in range(3):
                pcm = struct.pack("<320h", *([6000, -6000] * 160))
                await ws.send_bytes(AudioFrame(sequence, sequence * 320, pcm).encode())
            for _ in range(10):
                event = await asyncio.wait_for(ws.receive_json(), 2)
                if event["type"] == "speech":
                    break
            else:
                raise AssertionError("VAD did not start a durable turn")
            old_epoch = event["epoch"]
            first.kill()
            first.wait(timeout=5)
            await ws.close()
            await start(client)
            async with client.get(
                url + "/api/sessions/" + identity["id"],
                headers={"Authorization": "Bearer " + identity["token"]},
            ) as response:
                restored = await response.json()
            assert restored["turns"][0]["state"] == "abandoned"
            assert restored["turns"][0]["error_code"] == "process_restart"
            assert restored["session"]["recording"] == 0
            assert restored["session"]["epoch"] > old_epoch
            ws = await client.ws_connect(
                url + "/api/sessions/" + identity["id"] + "/audio"
            )
            await ws.send_json({"type": "authenticate", "token": identity["token"]})
            connected = await ws.receive_json()
            assert connected["recording"] is False
            await ws.close()
            backup_database(directory / "voice.sqlite", directory / "snapshot.sqlite")
            copy = Store(directory / "snapshot.sqlite")
            assert len(copy.turns(identity["id"])) == 1
            copy.close()
            return dict(
                kill_during="live VAD capture before utterance end",
                recovered_state="abandoned",
                error_code="process_restart",
                requires_fresh_consent=True,
                duplicate_turns=0,
                verified_online_backup=True,
                provider_inference=False,
            )
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stderr:
                process.stderr.close()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new evidence file.")
    with tempfile.TemporaryDirectory() as temporary:
        result = await run(Path(temporary))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
