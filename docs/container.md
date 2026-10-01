# Linux ARM containers

The container profile uses CPU inference on Linux ARM64. The workbench and its provider process use separate services. Only the browser/API service binds a loopback host port; the provider is on an internal network. Original model directories are mounted read-only and verified against the application's artifact manifests at startup.

## Configuration and launch

Create the private `.env` using the main setup instructions. It must contain distinct `VOICE_WORKSPACE_KEY` and `VOICE_OPERATOR_KEY` credentials, a `VOICE_PROVIDER_KEY` of at least 32 ASCII characters, and absolute host paths `WHISPER_MODEL_DIRECTORY` and `QWEN_MODEL_DIRECTORY` to the verified original models. Set `VOICE_ALLOW_FAULTS=1` only when intentionally exercising the fault controls. Never commit this file.

```sh
docker compose --env-file "${VOICE_ENV_FILE:-.env}" up -d --build
docker compose --env-file "${VOICE_ENV_FILE:-.env}" ps
```

Open `http://localhost:8096`. `VOICE_HOST_PORT` selects a different loopback port. For an external configuration file, export `VOICE_ENV_FILE=/absolute/path/private.env` before invoking the commands: Compose then uses that file for both interpolation and service environment. Container paths override any native paths in the private configuration. The persistent `workspace` volume holds SQLite state at `/data/voice.sqlite`; stopping or replacing containers preserves this volume.

The default platform is `linux/arm64`. The pinned ARM Torch wheel is a CPU build; these images do not install CUDA packages. This profile is not an AMD64 or GPU build. On Linux ARM the application selects PyTorch's reference CPU backend and limits inference threads to two; the checkpoint files remain unchanged. Reserve memory for the provider's two CPU model objects as well as the browser and host services. Provider readiness waits for artifact verification and model loading, rather than merely opening the HTTP socket. Native and container latency measurements belong to their recorded execution environments.

## Image targets

`docker build --platform linux/arm64 --target provider -t voice-reliability-provider:local .` builds the provider independently of the frontend. The final `workbench` target builds the audited frontend lock and copies its output into `voice/static`. Both targets run as UID/GID 65532. Compose drops capabilities, disallows privilege escalation, applies CPU/memory/process limits and makes the root filesystems read-only; only the named data volume and bounded temporary filesystems are writable.

## Exact inputs and speech source

Python 3.10.11 and Node 16.16.0 base images use immutable manifest digests. The CPU profile pins all 41 Python distributions and the exact Linux ARM wheels with SHA-256 hashes in `requirements-linux-arm64.lock`. Installation disables dependency resolution and runs `pip check`. The selected distributions match the source runtime's `requirements.lock`.

The speech builder uses a frozen Debian repository snapshot and `scripts/build-espeak.sh`. The script fetches the [original eSpeak NG 1.51 release](https://github.com/espeak-ng/espeak-ng/releases/tag/1.51) and its exact same-tag source archive, verifies both SHA-256 digests, and supplements files absent from the official release archive without replacing release files. It builds static eSpeak libraries, disabling direct audio-device output and optional external synthesizers; the product consumes generated WAV audio through a subprocess.

The installed binary is `/opt/espeak/bin/espeak-ng`. Both original source archives are retained under `/opt/espeak/share/source`, together with the builder's exact Debian package list. GPL and accompanying upstream license notices remain under `/opt/espeak/share/licenses`. Preserve these sources and notices when distributing the image. Model licenses and immutable model revisions remain in the application's artifact notices and manifests. See the [PyTorch 2.3.0 release files](https://pypi.org/project/torch/2.3.0/#files) for the upstream CPU artifact.

## Operations

Use the project runbook for coordinated backup/restore and failure exercises. The provider exposes no host port in Compose; inspect readiness with `docker compose ps` and provider logs. An intentional fault delay consumes the same bounded provider worker as a normal request. Cancellation must finish the native task before another task takes its slot.

```sh
docker compose --env-file "${VOICE_ENV_FILE:-.env}" logs --tail=100 providers workbench
docker compose --env-file "${VOICE_ENV_FILE:-.env}" stop
```

`stop` preserves containers and persistent state. Do not remove the volume when preserving session history. Hosted CI is a separate validation step; local container tests do not imply a hosted run or production deployment.

The frontend build and frontend test container use the Docker builder's native platform. The frontend stage explicitly selects `BUILDPLATFORM`, including when the final workbench image targets Linux ARM64; only generated HTML, CSS and JavaScript cross into the workbench stage. Python, Pipecat and eSpeak retain the audited Linux ARM64 profile. This avoids running Node/Vitest under QEMU while retaining all consent and playback tests.
