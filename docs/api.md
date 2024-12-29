# HTTP and audio contracts

The API listens on loopback8096; the provider listens on loopback8097. Compose exposes only the workbench. No endpoint accepts model-selected executable tools.

| Route | Credential / purpose |
| --- | --- |
| `GET /health` | Public minimal readiness; requires usable provider and healthy workspace |
| `GET /api/config` | Public audio format and whether diagnostic controls are enabled |
| `POST /api/sessions` | `Authorization: Bearer <workspace key>`; returns a new id and opaque session token |
| `GET /api/sessions/{id}` | Session token; redacted session, turns and bounded events, never the token hash |
| `GET /api/sessions/{id}/audio` | WebSocket; first text frame must be `{"type":"authenticate","token":"..."}` within 3 seconds |
| `GET /api/operator/sessions` | Operator key; list persisted sessions |
| `GET /api/operator/sessions/{id}` | Operator key; review full context |
| `POST /api/operator/sessions/{id}/accept` | Operator key; body `{"epoch":N}`;409 if handoff changed/already accepted |
| `POST /api/operator/sessions/{id}/complete` | Operator key; closes an accepted operator conversation |

Controls are exact JSON objects. `start`, `stop`, `interrupt`, `handoff`, `close` and `ping` require only `type`. `ack` requires `epoch` and `sequence`. `playback_started` and `playback_stopped` require `epoch`. `tool` requires `service` (`atlas` or `beacon`). Diagnostic `fault` requires `stage` (`none`, `stt`, `model`, `tts`, `tool`) and is available only when enabled in private configuration.

Each binary microphone frame is 648 bytes: unsigned big-endian32-bit sequence, unsigned big-endian32-bit sample offset, then320little-endian signed16-bit mono samples. Sequence starts at 0 on explicit recording start, and offsets advance320samples per packet. Samples represent 16 kHz audio. Unknown fields, oversized controls, gaps and malformed frames close the connection. The input queue holds at most 50 frames; unpaced overflow closes with1013. Four logical session identities across pending and authenticated WebSockets, and 100 persisted sessions, are permitted. Each identity permits one pending authentication. A replacement connection reuses its session's slot and may briefly overlap the old socket until successful authentication; failed replacements preserve the old socket. Excess admission returns HTTP 503 before upgrade. Authentication failure, timeout and disconnection release the reservation.

Events include `state`, `speech`, `transcript`, `reply`, `stage`, `audio`, `stop_audio`, `completed`, `error`, `tool` and `pong`. Audio packets contain epoch, ordered sequence, sample_rate 22050 and base 64 PCM16. Clients must flush scheduled audio on `stop_audio`, acknowledge only after each chunk finishes, and reject stale epochs. At most four 250 ms packets are outstanding. Missing acknowledgement for 3 seconds produces a durable `slow_listener` failure. `completed` is emitted only after playback acknowledgement and durable completion. Draft reply text may precede playback completion and is retained for handoff even if interrupted.

Provider requests use a separate Bearer key. `POST /transcribe`, `/respond`, `/synthesize` require a unique `id` and `timeout_ms` (50–30000). Stage fields are respectively `pcm`; `text` and `context`; or `text`. A diagnostic `delay_ms`0–5000 is permitted only in the configured fault profile. `POST /jobs/{id}/cancel` requests cooperative stopping. `GET /status` reports bounded worker state; its job history rejects the256most recent duplicate identities. The pipeline derives each stage id from session, connection, epoch and stage and does not automatically retry a completed job.

Common safe errors: `provider_busy`, `provider_timeout`, `provider_unavailable`, `invalid_provider_response`, `slow_listener`, `workspace_unavailable`. Internal exceptions and credentials are not returned. A provider may finish cleanup after the caller's deadline; query provider status before expecting new admission.
