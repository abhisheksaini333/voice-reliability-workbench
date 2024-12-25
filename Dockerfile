FROM python:3.10.11-slim-bullseye@sha256:fd86924ba14682eb11a3c244f60a35b5dfe3267cbf26d883fb5c14813ce926f1 AS speech-build
ARG TARGETARCH
RUN test "$TARGETARCH" = arm64
# Frozen Debian repository contents keep the compiler/support packages reproducible.
RUN printf '%s\n' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20240606T000000Z bullseye main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20240606T000000Z bullseye-security main' \
      > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config curl autoconf automake libtool \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/build-espeak.sh /usr/local/bin/build-espeak
RUN build-espeak /opt/espeak \
    && cp /usr/local/bin/build-espeak /opt/espeak/share/source/build-espeak.sh \
    && dpkg-query -W > /opt/espeak/share/source/build-packages.tsv

FROM python:3.10.11-slim-bullseye@sha256:fd86924ba14682eb11a3c244f60a35b5dfe3267cbf26d883fb5c14813ce926f1 AS runtime
ARG TARGETARCH
RUN test "$TARGETARCH" = arm64
WORKDIR /app
COPY requirements-linux-arm64.lock ./
RUN pip install --no-cache-dir --no-deps --require-hashes -r requirements-linux-arm64.lock && pip check
COPY --from=speech-build /opt/espeak/ /opt/espeak/
COPY voice/ voice/
COPY LICENSE THIRD_PARTY_NOTICES.md ./
RUN mkdir -p /data && chown 65532:65532 /data
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false \
    HF_HUB_OFFLINE=1 HF_HOME=/tmp/huggingface OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    VOICE_ESPEAK_BINARY=/opt/espeak/bin/espeak-ng
USER 65532:65532

FROM runtime AS provider
EXPOSE 8097
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8097/health', timeout=3)"
CMD ["python", "-m", "voice.provider_api", "--host", "0.0.0.0", "--port", "8097"]

FROM node:16.16.0-bullseye-slim@sha256:cda7229eb72b7534396e7b58ba5b9f2454aee188317e058cbbf22686e5d07e2f AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM runtime AS workbench
COPY --from=frontend /frontend/dist/ /app/voice/static/
EXPOSE 8096
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8096/health', timeout=3)"
CMD ["python", "-m", "voice.api", "--host", "0.0.0.0", "--port", "8096"]
