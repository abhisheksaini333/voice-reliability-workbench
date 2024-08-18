"""Bounded provider responses and cancellation propagation over authenticated HTTP."""
import asyncio
import base64
import json
import math
from urllib.parse import urlparse
import aiohttp
from .provider_contracts import ProviderFailure, SpeechAudio


class ProviderClient:
    def __init__(self, base_url, key):
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("explicit HTTP provider endpoint required")
        self.base_url = base_url.rstrip("/")
        self._key = key
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=8),
            headers={"Authorization": "Bearer " + key},
        )

    async def cancel(self, identity):
        try:
            async with self.session.post(
                self.base_url + "/jobs/" + identity + "/cancel",
                timeout=aiohttp.ClientTimeout(total=1),
            ) as response:
                await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass

    async def _call(self, stage, identity, fields, timeout_ms, delay_ms):
        completed = False
        try:
            async with self.session.post(
                self.base_url + "/" + stage,
                json=dict(
                    id=identity, timeout_ms=timeout_ms, delay_ms=delay_ms, **fields
                ),
                timeout=aiohttp.ClientTimeout(total=timeout_ms / 1000 + 2),
            ) as response:
                chunks = []
                size = 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > 2_000_000:
                        raise ProviderFailure("invalid_provider_response")
                    chunks.append(chunk)
                payload = json.loads(b"".join(chunks))
                if not isinstance(payload, dict):
                    raise ProviderFailure("invalid_provider_response")
                if response.status != 200:
                    allowed = {
                        "provider_timeout",
                        "provider_busy",
                        "provider_draining",
                        "cancelled",
                        "duplicate_job",
                        "context_limit",
                        "invalid_audio",
                        "invalid_context",
                        "invalid_transcript",
                        "invalid_model_response",
                    }
                    code = payload.get("error")
                    raise ProviderFailure(
                        code
                        if isinstance(code, str) and code in allowed
                        else "provider_failed"
                    )
                completed = True
                return payload
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            raise ProviderFailure("provider_unavailable") from error
        except (ValueError, TypeError) as error:
            raise ProviderFailure("invalid_provider_response") from error
        finally:
            if not completed:
                await self.cancel(identity)

    @staticmethod
    def _text(result, limit):
        text = result.get("text")
        if not isinstance(text, str) or len(text) > limit:
            raise ProviderFailure("invalid_provider_response")
        return result

    async def transcribe(self, identity, pcm, *, timeout_ms=15000, delay_ms=0):
        result = await self._call(
            "transcribe",
            identity,
            {"pcm": base64.b64encode(pcm).decode()},
            timeout_ms,
            delay_ms,
        )
        return self._text(result, 2000)

    async def respond(self, identity, text, context, *, timeout_ms=20000, delay_ms=0):
        result = await self._call(
            "respond", identity, dict(text=text, context=context), timeout_ms, delay_ms
        )
        return self._text(result, 500)

    async def synthesize(self, identity, text, *, timeout_ms=3000, delay_ms=0):
        result = await self._call(
            "synthesize", identity, {"text": text}, timeout_ms, delay_ms
        )
        try:
            audio = SpeechAudio(
                base64.b64decode(result["pcm"], validate=True), result["sample_rate"]
            )
            if not math.isclose(audio.duration_ms, result["duration_ms"], abs_tol=0.1):
                raise ValueError("duration mismatch")
            return audio
        except (ValueError, TypeError, KeyError) as error:
            raise ProviderFailure("invalid_provider_response") from error

    async def healthy(self):
        try:
            async with self.session.get(
                self.base_url + "/health", timeout=aiohttp.ClientTimeout(total=2)
            ) as response:
                return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def close(self):
        await self.session.close()
