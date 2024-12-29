"""Feed real speech fixtures in real time and fence synthesized audio on new speech."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
import wave
import aiohttp
from voice.audio import pcm_rms
from voice.contracts import AudioFrame


def pcm(path):
    with wave.open(str(path), "rb") as source:
        assert (
            source.getframerate(),
            source.getnchannels(),
            source.getsampwidth(),
        ) == (16000, 1, 2)
        data = source.readframes(source.getnframes())
    return data + bytes((-len(data)) % 640)


async def run(url, fixtures):
    first = pcm(fixtures / "greeting.wav")
    second = pcm(fixtures / "interrupt.wav")
    synthesized = asyncio.Event()
    barge_in = asyncio.Event()
    observed = {
        "first_audio_epoch": None,
        "new_speech_epoch": None,
        "old_audio_after_stop": 0,
        "first_chunks": 0,
    }
    onset = None
    stopped = None
    async with aiohttp.ClientSession() as client:
        async with client.post(
            url + "/api/sessions",
            headers={"Authorization": "Bearer " + os.environ["VOICE_WORKSPACE_KEY"]},
        ) as response:
            assert response.status == 201
            identity = await response.json()
        async with client.ws_connect(
            url + "/api/sessions/" + identity["id"] + "/audio"
        ) as ws:
            await ws.send_json({"type": "authenticate", "token": identity["token"]})
            await ws.receive_json()
            await ws.send_json({"type": "start"})
            await ws.receive_json()

            async def receive():
                nonlocal stopped
                while True:
                    event = await ws.receive_json()
                    if event["type"] == "error":
                        raise AssertionError(event["code"])
                    if event["type"] == "audio":
                        if observed["first_audio_epoch"] is None:
                            observed["first_audio_epoch"] = event["epoch"]
                            synthesized.set()
                        if event["epoch"] == observed["first_audio_epoch"]:
                            observed["first_chunks"] += 1
                            if stopped is not None:
                                observed["old_audio_after_stop"] += 1
                    if (
                        event["type"] == "stop_audio"
                        and observed["first_audio_epoch"] is not None
                        and event["epoch"] > observed["first_audio_epoch"]
                    ):
                        stopped = time.monotonic()
                    if (
                        event["type"] == "speech"
                        and observed["first_audio_epoch"] is not None
                        and event["epoch"] > observed["first_audio_epoch"]
                    ):
                        observed["new_speech_epoch"] = event["epoch"]
                        barge_in.set()

            task = asyncio.create_task(receive())
            sequence = 0

            async def send(chunk):
                nonlocal sequence
                await ws.send_bytes(
                    AudioFrame(sequence, sequence * 320, chunk).encode()
                )
                sequence += 1
                await asyncio.sleep(0.02)

            try:
                for offset in range(0, len(first), 640):
                    await send(first[offset : offset + 640])
                deadline = time.monotonic() + 35
                while not synthesized.is_set():
                    if task.done():
                        await task
                    if time.monotonic() > deadline:
                        raise TimeoutError("actual synthesis deadline")
                    await send(bytes(640))
                for offset in range(0, len(second), 640):
                    chunk = second[offset : offset + 640]
                    if onset is None and pcm_rms(chunk) >= 0.018:
                        onset = time.monotonic()
                    await send(chunk)
                    if barge_in.is_set():
                        break
                await asyncio.wait_for(barge_in.wait(), 2)
                await asyncio.sleep(0.25)
                assert observed["old_audio_after_stop"] == 0
                assert onset is not None and stopped is not None
                observed["speech_onset_to_stop_message_ms"] = (stopped - onset) * 1000
                await ws.send_json({"type": "handoff"})
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        async with client.get(
            url + "/api/sessions/" + identity["id"],
            headers={"Authorization": "Bearer " + identity["token"]},
        ) as response:
            detail = await response.json()
        assert detail["turns"][0]["state"] == "cancelled"
        observed.update(
            first_turn_state=detail["turns"][0]["state"],
            model_transcript=detail["turns"][0]["transcript"],
            model_reply=detail["turns"][0]["reply"],
        )
    return dict(
        scope="Actual HTTP/WS and original speech models; real-time project PCM fixtures. This probe does not play audio: it verifies server VAD fencing of actual synthesized output. Browser tests separately verify scheduled-source stopping.",
        results=observed,
    )


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8096")
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new evidence path.")
    result = await run(args.url, args.fixtures)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["results"]))


if __name__ == "__main__":
    asyncio.run(main())
