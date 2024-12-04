# Operating the local workbench

Start the provider first and wait for `/health`200, then start the workbench. The provider verifies every original model file before loading. A healthy API endpoint alone does not prove recognition quality or completed audio playback; use the browser journey and fixture report for those checks.

## First conversation

Create a session with the workspace key, choose Start microphone, ask one short question and pause. The inspector shows STT/model/TTS stages. A completed turn requires the browser to acknowledge the last played chunk. Keep the tab foregrounded during latency measurements: background-tab scheduling and suspended audio contexts change the result. Use headphones when speaking near real speakers to reduce echo; the browser requests echo cancellation, but the deterministic energy detector is not a neural VAD.

The original small models trade quality for a bounded CPU demonstration. Do not treat an answer as a service action or verified status. Use the explicit read-only Atlas/Beacon lookup to inspect demo tool behavior. It is a fixed local demonstration dataset. The model cannot invoke a tool or claim a successful receipt by emitting matching text.

## Failure exercises

With diagnostics enabled, open Reliability scenarios and choose a delayed stage before recording. This inserts a 1 second delay into the real provider execution path with a 150 ms stage budget. The turn must fail with `provider_timeout`, retain the recognized transcript if STT finished, and produce no late audio. Restore Normal operation before the next turn.

Choose Tool lookup timeout and click Look up. The receipt must become `timed_out`; duplicate or late completion is rejected by the same receipt state machine. The receipt's allowlisted result and terminal state appear in the event timeline. There is no externally exposed callback that accepts arbitrary tool results.

Interrupt while response audio is playing. Scheduled sources stop immediately, the server advances epoch, and the trace records the browser's stop acknowledgement. Reconnect during a turn: the old connection loses ownership, playback stops and the new connection requires a fresh Start microphone action. A reconnect is a new transport generation; it does not replay the old response.

If the provider disappears, the client reports `provider_unavailable`. Restart the same provider against the original models and reconnect the browser. No automatic replay occurs. If the provider is busy, its single worker returns `provider_busy`; wait for existing work/cleanup to finish. Expanding concurrency would require model-memory and scheduling measurements beyond this profile.

## Persistence and restore

Keep `.env`/`.env.json` private and preserve them separately from backups. Session tokens are stored only as hashes; operator credentials permit reviewing historical sessions. Configuration setup never replaces existing keys.

```sh
python -m voice.backup "$VOICE_DATABASE" /absolute/path/voice-backup.sqlite
```

This uses SQLite's online backup API, includes committed WAL state, checks integrity and refuses an existing destination. For restore, stop the workbench, preserve its existing database/WAL/SHM files, point `VOICE_DATABASE` at a **new copy** of the verified snapshot, and restart. Do not copy over a running database. Startup acquires an exclusive owner lock, abandons unfinished turns, increments epochs and disables recording. Containers keep the named data volume when stopped; see [container operations](container.md).

`PYTHONPATH=. python scripts/check_recovery.py --output /tmp/voice-recovery.json` creates an isolated database and API, kills only its own child process during live VAD capture, restarts it and checks preserved history, fresh consent and an online backup. It does not kill the main workbench or use model inference.

The local workspace limits 100 sessions,100 turns per session,100tool receipts per live session and 1000 events per session. Export needed traces and archive a verified database before choosing a new workspace path. No automatic history deletion or date manipulation is performed. Transcript exports contain conversation text and should be handled according to the operator's own data policy.

## Troubleshooting

- **Providers unavailable:** inspect provider logs for model hash mismatch, missing eSpeak or memory pressure. Keep only the needed model services running. On Linux ARM the configured reference CPU backend is intentional.
- **Microphone access failed:** use localhost or a secure origin, allow the microphone in browser settings and ensure an audio input exists. Browser tests deliberately use a disclosed fixture device.
- **Input overflow / invalid audio:** send 20 ms frames in real time. Do not upload an entire recording as a burst through the live microphone channel.
- **Slow listener:** keep the tab active and permit audio playback. The browser must send ordered acknowledgements after actual scheduled chunks finish.
- **Workspace unavailable:** preserve the database, check filesystem space/permissions, stop the process and run SQLite integrity checks before restarting. Admission fails closed after storage failure.

CI verifies composition, bounded behavior and isolated recovery. Actual model, browser and container evidence is separately recorded; a workflow file is not a claim that hosted CI has run.
