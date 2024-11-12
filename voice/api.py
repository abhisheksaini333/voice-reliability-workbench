"""Local authenticated voice workspace with bounded WebSocket transport."""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from aiohttp import web, WSMsgType
from loguru import logger
from .contracts import parse_control, ProtocolError
from .engine import SessionEngine, discard
from .ownership import WorkspaceOwner
from .playback import SlowConsumer
from .provider_client import ProviderClient
from .state import SessionState, StateError
from .store import Store
from .tools import ToolError

RUNTIME = web.AppKey("runtime", object)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def public_session(record):
    return {key: value for key, value in record.items() if key != "token_hash"}


class Workspace:
    def __init__(self, database, providers, allow_faults):
        self.owner = WorkspaceOwner(database)
        self.owner.__enter__()
        try:
            self.store = Store(database)
            self.store.recover(self.owner)
        except BaseException:
            self.owner.__exit__()
            raise
        self.providers = providers
        self.allow_faults = allow_faults
        self.engines = {}
        self.sockets = {}
        self.healthy = True

    def engine(self, session_id):
        if session_id not in self.engines:
            record = self.store.session(session_id)
            if record is None:
                raise web.HTTPNotFound()
            self.engines[session_id] = SessionEngine(
                SessionState.restore(record),
                self.store,
                self.providers,
                allow_faults=self.allow_faults,
            )
        return self.engines[session_id]

    async def close(self):
        for socket in list(self.sockets.values()):
            await socket.close(code=1001, message=b"workspace stopping")
        for engine in self.engines.values():
            await engine.disconnect(engine.state.connection)
        try:
            await self.providers.close()
        finally:
            self.store.close()
            self.owner.__exit__()


def create_app(
    database, workspace_key, operator_key, *, provider_factory=None, allow_faults=False
):
    if any(
        not isinstance(key, str) or not key.isascii() or len(key) < 32
        for key in (workspace_key, operator_key)
    ):
        raise ValueError(
            "distinct long ASCII workspace and operator credentials required"
        )
    if hmac.compare_digest(workspace_key, operator_key):
        raise ValueError("workspace and operator credentials must differ")

    def authenticated(request, key):
        value = request.headers.get("Authorization", "")
        return value.isascii() and hmac.compare_digest(value, "Bearer " + key)

    def require_operator(request):
        if not authenticated(request, operator_key):
            raise web.HTTPUnauthorized()

    def require_session(request):
        runtime = request.app[RUNTIME]
        record = runtime.store.session(request.match_info["session_id"])
        authorization = request.headers.get("Authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else ""
        if (
            record is None
            or not token
            or len(token) > 128
            or not hmac.compare_digest(record["token_hash"], digest(token))
        ):
            raise web.HTTPUnauthorized()
        return record

    @web.middleware
    async def boundary(request, handler):
        origin = request.headers.get("Origin")
        if origin and origin != f"{request.scheme}://{request.host}":
            return web.json_response({"error": "origin_rejected"}, status=403)
        try:
            response = await handler(request)
        except web.HTTPException as error:
            if request.path.startswith("/api/"):
                response = web.json_response(
                    {
                        "error": {
                            401: "unauthorized",
                            404: "not_found",
                            409: "conflict",
                            413: "request_too_large",
                        }.get(error.status, "invalid_request")
                    },
                    status=error.status,
                )
            else:
                response = error
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            response = web.json_response({"error": "invalid_request"}, status=400)
        except asyncio.CancelledError:
            raise
        except Exception:
            request.app[RUNTIME].healthy = False
            response = web.json_response({"error": "workspace_unavailable"}, status=503)
        if not response.prepared:
            response.headers.update(
                {
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                    "X-Frame-Options": "DENY",
                    "Permissions-Policy": "microphone=(self)",
                    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' ws: wss:; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'",
                }
            )
        return response

    app = web.Application(client_max_size=4096, middlewares=[boundary])

    async def lifecycle(app):
        factory = provider_factory or (
            lambda: ProviderClient(
                os.environ["VOICE_PROVIDER_URL"], os.environ["VOICE_PROVIDER_KEY"]
            )
        )
        app[RUNTIME] = Workspace(database, factory(), allow_faults)
        yield
        await app[RUNTIME].close()

    app.cleanup_ctx.append(lifecycle)

    async def health(request):
        runtime = request.app[RUNTIME]
        healthy = runtime.healthy and all(
            engine.healthy for engine in runtime.engines.values()
        )
        if healthy:
            runtime.store.connection.execute("SELECT 1")
            healthy = await runtime.providers.healthy()
        return web.json_response({"ready": healthy}, status=200 if healthy else 503)

    async def config(request):
        return web.json_response(
            {"diagnostics": allow_faults, "sample_rate": 16000, "frame_samples": 320}
        )

    async def create(request):
        if not authenticated(request, workspace_key):
            raise web.HTTPUnauthorized()
        runtime = request.app[RUNTIME]
        if not runtime.healthy or any(not e.healthy for e in runtime.engines.values()):
            raise web.HTTPServiceUnavailable()
        identity, token = secrets.token_hex(16), secrets.token_urlsafe(32)
        try:
            runtime.store.create(
                identity, digest(token), SessionState(identity).snapshot()
            )
        except ValueError:
            raise web.HTTPConflict()
        return web.json_response({"id": identity, "token": token}, status=201)

    def detail(runtime, identity):
        record = runtime.store.session(identity)
        if record is None:
            raise web.HTTPNotFound()
        return {
            "session": public_session(record),
            "turns": runtime.store.turns(identity),
            "events": runtime.store.events(identity),
        }

    async def session(request):
        require_session(request)
        return web.json_response(
            detail(request.app[RUNTIME], request.match_info["session_id"])
        )

    async def operator_list(request):
        require_operator(request)
        return web.json_response(
            {
                "sessions": [
                    public_session(row) for row in request.app[RUNTIME].store.sessions()
                ]
            }
        )

    async def operator_detail(request):
        require_operator(request)
        return web.json_response(
            detail(request.app[RUNTIME], request.match_info["session_id"])
        )

    async def operator_accept(request):
        require_operator(request)
        value = await request.json()
        if (
            not isinstance(value, dict)
            or set(value) != {"epoch"}
            or type(value["epoch"]) is not int
        ):
            raise web.HTTPBadRequest()
        try:
            await request.app[RUNTIME].engine(
                request.match_info["session_id"]
            ).accept_handoff(value["epoch"])
        except StateError:
            raise web.HTTPConflict()
        return web.json_response(
            detail(request.app[RUNTIME], request.match_info["session_id"])
        )

    async def operator_complete(request):
        require_operator(request)
        engine = request.app[RUNTIME].engine(request.match_info["session_id"])
        if engine.state.phase != "operator":
            raise web.HTTPConflict()
        await engine.close()
        return web.json_response(
            detail(request.app[RUNTIME], request.match_info["session_id"])
        )

    async def websocket(request):
        runtime = request.app[RUNTIME]
        identity = request.match_info["session_id"]
        record = runtime.store.session(identity)
        if record is None:
            raise web.HTTPNotFound()
        if identity not in runtime.sockets and len(runtime.sockets) >= 4:
            raise web.HTTPServiceUnavailable()
        ws = web.WebSocketResponse(max_msg_size=4096, heartbeat=20, receive_timeout=90)
        await ws.prepare(request)
        try:
            message = await asyncio.wait_for(ws.receive(), 3)
            auth = json.loads(message.data) if message.type == WSMsgType.TEXT else None
            if (
                not isinstance(auth, dict)
                or set(auth) != {"type", "token"}
                or auth["type"] != "authenticate"
                or not isinstance(auth["token"], str)
                or len(auth["token"]) > 128
                or not hmac.compare_digest(record["token_hash"], digest(auth["token"]))
            ):
                raise ValueError("invalid authentication")
        except (ValueError, TypeError, asyncio.TimeoutError):
            await ws.close(code=1008, message=b"authentication required")
            return ws
        engine = runtime.engine(identity)
        if not engine.healthy or engine.state.phase == "closed":
            await ws.close(code=1008, message=b"session unavailable")
            return ws
        previous = runtime.sockets.get(identity)
        if previous is not None:
            await previous.close(code=1000, message=b"connection replaced")
        runtime.sockets[identity] = ws
        incoming, outgoing = asyncio.Queue(maxsize=50), asyncio.Queue(maxsize=16)

        async def emit(event):
            if ws.closed:
                raise SlowConsumer("connection is closed")
            try:
                outgoing.put_nowait(event)
            except asyncio.QueueFull:
                await ws.close(code=1013, message=b"output overflow")
                raise SlowConsumer("output overflow")

        # The old handler completes before replacement, and only this generation
        # may mutate live state or disconnect the engine.
        engine.emit = discard
        try:
            connection = await engine.connect(emit)
        except Exception:
            runtime.sockets.pop(identity, None)
            await ws.close(code=1011, message=b"workspace unavailable")
            return ws

        async def send():
            while True:
                event = await outgoing.get()
                if event["type"] == "audio" and event["epoch"] != engine.state.epoch:
                    continue
                await asyncio.wait_for(ws.send_json(event), 3)

        async def consume():
            while True:
                message = await incoming.get()
                if engine.state.connection != connection:
                    return
                if message.type == WSMsgType.BINARY:
                    await engine.receive_audio(message.data)
                    continue
                control = parse_control(message.data)
                kind = control["type"]
                if kind == "ack":
                    await engine.playback.acknowledge(
                        control["epoch"], control["sequence"]
                    )
                elif kind == "playback_started":
                    await engine.playback_started(control["epoch"])
                elif kind == "playback_stopped":
                    await engine.playback_stopped(control["epoch"])
                elif kind == "tool":
                    await engine.request_tool(control["service"])
                elif kind == "fault":
                    engine.set_fault(control["stage"])
                elif kind == "ping":
                    await emit({"type": "pong"})
                else:
                    await getattr(engine, kind)()

        async def receive():
            async for message in ws:
                if message.type not in (WSMsgType.TEXT, WSMsgType.BINARY):
                    break
                try:
                    incoming.put_nowait(message)
                except asyncio.QueueFull:
                    await ws.close(code=1013, message=b"input overflow")
                    return

        tasks = [
            asyncio.create_task(operation()) for operation in (send, consume, receive)
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                error = task.exception()
                if error is not None:
                    if isinstance(
                        error, (ProtocolError, StateError, ToolError, ValueError)
                    ):
                        await ws.close(code=1008, message=b"invalid control or audio")
                    else:
                        await ws.close(code=1011, message=b"connection unavailable")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await engine.disconnect(connection)
            if runtime.sockets.get(identity) is ws:
                runtime.sockets.pop(identity, None)
            await ws.close()
        return ws

    async def static(request):
        root = Path(__file__).parent / "static"
        if not root.exists():
            root = Path(__file__).parent.parent / "frontend" / "dist"
        candidate = (root / request.match_info.get("path", "")).resolve()
        if not candidate.is_relative_to(root.resolve()):
            raise web.HTTPNotFound()
        if not candidate.is_file():
            candidate = root / "index.html"
        if not candidate.is_file():
            return web.Response(
                text="Build the frontend to open the voice workspace.", status=503
            )
        return web.FileResponse(candidate)

    app.router.add_get("/health", health)
    app.router.add_get("/api/config", config)
    app.router.add_post("/api/sessions", create)
    app.router.add_get("/api/operator/sessions", operator_list)
    app.router.add_get("/api/operator/sessions/{session_id}", operator_detail)
    app.router.add_post("/api/operator/sessions/{session_id}/accept", operator_accept)
    app.router.add_post(
        "/api/operator/sessions/{session_id}/complete", operator_complete
    )
    app.router.add_get("/api/sessions/{session_id}", session)
    app.router.add_get("/api/sessions/{session_id}/audio", websocket)
    app.router.add_get("/{path:.*}", static)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8096)
    args = parser.parse_args()
    logger.remove()
    logger.add(lambda message: None, level="WARNING")
    os.umask(0o077)
    database = Path(os.environ.get("VOICE_DATABASE", "voice.sqlite"))
    database.parent.mkdir(parents=True, exist_ok=True)
    app = create_app(
        database,
        os.environ["VOICE_WORKSPACE_KEY"],
        os.environ["VOICE_OPERATOR_KEY"],
        allow_faults=os.environ.get("VOICE_ALLOW_FAULTS") == "1",
    )
    web.run_app(app, host=args.host, port=args.port, access_log=None)


if __name__ == "__main__":
    main()
