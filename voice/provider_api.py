"""Authenticated local HTTP boundary around the real CPU voice providers."""
import argparse
import asyncio
import base64
import binascii
import hmac
import os
import time
from aiohttp import web
from .generation import QwenResponder
from .provider_contracts import ProviderFailure
from .synthesis import EspeakSynthesizer
from .transcription import WhisperRecognizer
from .worker import NativeWorker

WORKER = web.AppKey("native_worker", NativeWorker)


def create_provider_app(recognizer, responder, synthesizer, key, *, allow_faults=False):
    if not isinstance(key, str) or len(key) < 32 or not key.isascii():
        raise ValueError(
            "provider credential must contain at least 32 ASCII characters"
        )
    worker = NativeWorker()

    @web.middleware
    async def boundary(request, handler):
        if request.path != "/health":
            supplied = request.headers.get("Authorization", "")
            if not supplied.isascii() or not hmac.compare_digest(
                supplied, "Bearer " + key
            ):
                return web.json_response({"error": "unauthorized"}, status=401)
        try:
            return await handler(request)
        except ProviderFailure as error:
            status = {
                "provider_timeout": 504,
                "cancelled": 499,
                "duplicate_job": 409,
                "invalid_job": 400,
                "invalid_audio": 400,
                "invalid_context": 400,
                "invalid_transcript": 400,
                "invalid_speech_text": 400,
                "context_limit": 422,
            }.get(error.code, 503)
            return web.json_response(
                {"error": error.code},
                status=status,
                headers={"Cache-Control": "no-store"},
            )
        except (ValueError, TypeError, KeyError, binascii.Error):
            return web.json_response({"error": "invalid_request"}, status=400)
        except web.HTTPException:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            return web.json_response({"error": "provider_failed"}, status=503)

    app = web.Application(client_max_size=600_000, middlewares=[boundary])
    app[WORKER] = worker

    async def health(request):
        return web.json_response(
            {"ready": not worker.closing}, status=503 if worker.closing else 200
        )

    async def status(request):
        return web.json_response(
            worker.snapshot(), headers={"Cache-Control": "no-store"}
        )

    async def cancel(request):
        return web.json_response(
            {"cancellation_requested": worker.cancel(request.match_info["identity"])}
        )

    async def watch_disconnect(request, identity, task):
        while not task.done():
            if request.transport is None or request.transport.is_closing():
                worker.cancel(identity)
                return
            await asyncio.sleep(0.02)

    async def invoke(request):
        stage = {"/transcribe": "stt", "/respond": "model", "/synthesize": "tts"}[
            request.path
        ]
        fields = {"stt": {"pcm"}, "model": {"text", "context"}, "tts": {"text"}}[stage]
        body = await request.json()
        required = {"id", "timeout_ms"} | fields
        if (
            not isinstance(body, dict)
            or not required <= set(body)
            or set(body) - required - {"delay_ms"}
        ):
            raise ValueError("invalid provider fields")
        timeout = body["timeout_ms"]
        delay = body.get("delay_ms", 0)
        if (
            type(timeout) is not int
            or not 50 <= timeout <= 30000
            or type(delay) is not int
            or not 0 <= delay <= 5000
        ):
            raise ValueError("invalid deadline or fault delay")
        if delay and not allow_faults:
            raise ValueError("fault injection is disabled")
        if stage == "stt":
            if not isinstance(body["pcm"], str) or len(body["pcm"]) > 512000:
                raise ValueError("invalid audio")
            pcm = base64.b64decode(body["pcm"], validate=True)
            if len(pcm) % 2 or not 640 <= len(pcm) <= 384000:
                raise ValueError("invalid audio")

        def operation(budget):
            delayed_until = time.monotonic() + delay / 1000
            while time.monotonic() < delayed_until:
                budget.check()
                budget.stop.wait(0.01)
            budget.check()
            if stage == "stt":
                return recognizer.transcribe(pcm, budget)
            if stage == "model":
                return responder.reply(body["text"], body["context"], budget)
            audio = synthesizer.synthesize(body["text"], budget)
            return {
                "pcm": base64.b64encode(audio.pcm).decode(),
                "sample_rate": audio.sample_rate,
                "duration_ms": audio.duration_ms,
            }

        task = asyncio.create_task(
            worker.run(body["id"], stage, operation, timeout / 1000)
        )
        watcher = asyncio.create_task(watch_disconnect(request, body["id"], task))
        try:
            result = await asyncio.shield(task)
            return web.json_response(result, headers={"Cache-Control": "no-store"})
        except asyncio.CancelledError:
            worker.cancel(body["id"])
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))
            raise
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    async def cleanup(app):
        await worker.close()

    app.add_routes(
        [
            web.get("/health", health),
            web.get("/status", status),
            web.post("/jobs/{identity}/cancel", cancel),
            web.post("/transcribe", invoke),
            web.post("/respond", invoke),
            web.post("/synthesize", invoke),
        ]
    )
    app.on_cleanup.append(cleanup)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8097)
    args = parser.parse_args()
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    recognizer = WhisperRecognizer.load(os.environ["VOICE_WHISPER_PATH"])
    responder = QwenResponder.load(os.environ["VOICE_QWEN_PATH"])
    synthesizer = EspeakSynthesizer(os.environ["VOICE_ESPEAK_BINARY"])
    app = create_provider_app(
        recognizer,
        responder,
        synthesizer,
        os.environ["VOICE_PROVIDER_KEY"],
        allow_faults=os.environ.get("VOICE_ALLOW_FAULTS") == "1",
    )
    web.run_app(app, host=args.host, port=args.port, access_log=None)


if __name__ == "__main__":
    main()
