# Voice Reliability Workbench

A browser voice assistant with a visible, interruptible speech pipeline and an operator handoff workspace. Microphone audio passes through energy VAD, **actual Pipecat processors, Whisper tiny.en, Qwen2-0.5B-Instruct and eSpeak NG**. Session history, stage timings and failure outcomes remain inspectable in SQLite.

The workbench handles explicit microphone consent, interruption, reconnect, bounded playback, provider deadlines, read-only demo tools and human takeover. It runs on local CPU with separately downloaded, verified model artifacts.

## Run from source

The verified source profile is macOS ARM64 with Python3.10, Node20.10 and eSpeakNG1.51. The [Linux ARM container profile](docs/container.md) provides a reproducible eSpeak build and a hash-pinned CPU dependency lock. Budget roughly1.2 GB for original model files, several GB of runtime memory, and disk space for Python/Node environments. One provider job runs at a time.

```sh
python3.10 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
pip check
python -m voice.download --directory models
```

Install eSpeakNG1.51 or build the original release using `scripts/build-espeak.sh /absolute/install/prefix` on Linux with the build prerequisites from the Dockerfile. Create private configuration after the model download:

```sh
python -m voice.configuration --models models --espeak /absolute/path/to/espeak-ng --diagnostics
npm --prefix frontend ci --ignore-scripts --no-audit --no-fund
npm --prefix frontend run build
set -a
. ./.env
set +a
python -m voice.provider_api
```

In another shell, activate the same Python environment, load `.env` with `set -a`, and run:

```sh
python -m voice.api
```

Open **http://127.0.0.1:8096**. Enter the private `VOICE_WORKSPACE_KEY` from `.env`, create a conversation, then choose **Start microphone**. The browser asks for permission. Pause after a sentence to end a turn. **Interrupt response** immediately stops scheduled audio; speaking again also starts a new turn. **Reconnect** requires microphone consent again.

Choose **Request an operator**, open **Operator review**, enter the separate `VOICE_OPERATOR_KEY`, select the conversation and accept the handoff. The transcript, interrupted drafts, timings and event timeline remain available. **Complete conversation** closes the session.

Configuration creation refuses to overwrite existing keys. `.env` and `.env.json` are private mode 0600 files and ignored by Git. The browser keeps session credentials in memory; reloading the page requires a new call session, while the operator can still review persisted history. Diagnostics are opt-in; omit `--diagnostics` for normal operation.

## What the reliability controls do

| Control | Behavior |
| --- | --- |
| Microphone transport | 20 ms PCM16/16 kHz frames with contiguous sequence and sample clocks; a50-frame input queue |
| VAD | Energy threshold,60 ms attack,200 ms pre-roll,400 ms silence cutoff; utterances capped at 12 seconds |
| Playback |250 ms chunks, four credits, ordered completion acknowledgements; at most one second queued ahead |
| Interrupt / reconnect | Monotonic turn and connection epochs reject old model, tool and audio results; the browser stops every scheduled source |
| Provider deadline | Cooperative cancellation reaches the native worker; capacity remains occupied until native work finishes |
| Demo tool | Explicit allowlisted Atlas/Beacon status lookup with bounded deadline and single-use result receipt |
| Handoff | Pending→accepted→closed workflow; assistant audio and recording stop before takeover |
| Restart | Exclusive workspace ownership; unfinished turns become abandoned, history remains, recording does not resume |

## Verify and measure

```sh
python -m unittest discover -s tests -q
npm --prefix frontend test
npm --prefix frontend run build
PYTHONPATH=. python scripts/check_recovery.py --output /tmp/voice-recovery.json
PYTHONPATH=. python scripts/measure.py --output /tmp/voice-fixtures.json
```

The fixture measurement command requires the actual provider service and loaded `.env`. It processes six original synthetic audio fixtures without substituting their references for recognized speech. Optional actual-model unit checks use `VOICE_WHISPER_PATH`, `VOICE_QWEN_PATH` and `VOICE_ESPEAK_BINARY`; otherwise those three checks report skipped.

For the real browser journey, keep both services running with diagnostics enabled:

```sh
cd frontend
VOICE_E2E_CONFIG="$PWD/../.env.json" npm run test:e2e
```

Install the pinned Playwright browser with `npx playwright install chromium`, or set `CHROME_PATH` to an installed Chrome executable. Tests use Chromium's disclosed WAV-backed fake microphone device through the real `getUserMedia`/AudioWorklet path. They do not require a person's microphone. Browser traces are disabled to avoid recording credential-bearing traffic.

See [measured results and evidence limits](docs/verification.md), [architecture](docs/architecture.md), [API contracts](docs/api.md), [operations and recovery](docs/runbook.md), [containers](docs/container.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

This is a local reliability workbench. Model responses may be incorrect; the small Whisper checkpoint makes errors on names and numbers. It has no telephone carrier, SIP/PSTN connection, human speech accuracy benchmark, production deployment claim or GPU performance claim.
