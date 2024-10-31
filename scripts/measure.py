"""Measure original fixtures through the actual authenticated HTTP provider service."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import time
from uuid import uuid4
import wave
from voice.evaluation import word_error_rate
from voice.provider_client import ProviderClient


async def measure(directory, provider, output):
    manifest = json.loads((directory / "manifest.json").read_text())
    rows = []
    for fixture in manifest["fixtures"]:
        path = directory / fixture["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != fixture["sha256"]:
            raise ValueError("fixture hash mismatch")
        with wave.open(str(path), "rb") as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (
                16000,
                1,
                2,
            ):
                raise ValueError("16kHz mono PCM16 fixture required")
            pcm = audio.readframes(audio.getnframes())
        identity = uuid4().hex
        started = time.monotonic()
        transcript = await provider.transcribe(identity + "-stt", pcm)
        response = await provider.respond(identity + "-model", transcript["text"], [])
        speech = await provider.synthesize(identity + "-tts", response["text"])
        rows.append(
            dict(
                fixture=fixture["id"],
                reference=fixture["reference"],
                observed=transcript["text"],
                word_error=word_error_rate(fixture["reference"], transcript["text"]),
                response=response["text"],
                stt_ms=transcript["latency_ms"],
                model_ms=response["latency_ms"],
                generated_tokens=response["output_tokens"],
                synthesized_audio_ms=speech.duration_ms,
                total_ms=(time.monotonic() - started) * 1000,
                fixture_sha256=fixture["sha256"],
            )
        )
    result = dict(
        scope="Actual authenticated CPU provider HTTP; disclosed synthetic eSpeak fixtures; no browser or carrier measurement in this report.",
        models=dict(
            stt="Whisper tiny.en 87c7102498dcde7456f24cfd30239ca606ed9063",
            model="Qwen2-0.5B-Instruct c291d6fce4804a1d39305f388dd32897d1f7acc4",
            tts="eSpeak NG1.51",
        ),
        hardware=dict(
            platform=platform.platform(),
            machine=platform.machine(),
            logical_cpus=os.cpu_count(),
            torch_threads=2,
        ),
        fixtures=rows,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output file to retain earlier measurements.")
    provider = ProviderClient(
        os.environ.get("VOICE_PROVIDER_URL", "http://127.0.0.1:8097"),
        os.environ["VOICE_PROVIDER_KEY"],
    )
    try:
        result = await measure(args.fixtures, provider, args.output)
        print(
            json.dumps(
                {"fixtures": len(result["fixtures"]), "output": str(args.output)}
            )
        )
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
