"""Create disclosed synthetic speech fixtures; never overwrite an existing corpus."""
import argparse
import hashlib
import json
from pathlib import Path
import threading
import time
import wave
import numpy as np
from scipy.signal import resample_poly
from voice.provider_contracts import WorkBudget
from voice.synthesis import EspeakSynthesizer

REFERENCES = [
    ("greeting", "Hello, can you help me with a service issue?"),
    ("status", "Please tell me the status of the Atlas service."),
    ("handoff", "I would like to speak with a human operator."),
    ("interrupt", "Stop talking. I have another question."),
    ("numbers", "The ticket number is four two seven. Please repeat it."),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--espeak", required=True)
    parser.add_argument("--output", type=Path, default=Path("fixtures"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "manifest.json").exists() or list(args.output.glob("*.wav")):
        raise SystemExit(
            "Choose a new directory; existing audio fixtures are preserved."
        )
    synth = EspeakSynthesizer(args.espeak)
    corpus = []
    for name, reference in REFERENCES:
        audio = synth.synthesize(
            reference, WorkBudget(threading.Event(), time.monotonic() + 3)
        )
        values = np.frombuffer(audio.pcm, dtype="<i2").astype(np.float64) / 32768
        values = resample_poly(values, 320, 441)
        variants = [(name, values, "clean")]
        if name == "status":
            noise = np.random.default_rng(1729).normal(0, 0.008, len(values))
            variants.append(
                (
                    "status-noise",
                    values + noise,
                    "Gaussian noise std0.008, NumPy seed1729",
                )
            )
        for identity, samples, condition in variants:
            samples = np.concatenate((np.zeros(3200), samples, np.zeros(8000)))
            pcm = (np.clip(samples, -1, 0.999969) * 32768).astype("<i2").tobytes()
            path = args.output / (identity + ".wav")
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(pcm)
            corpus.append(
                dict(
                    id=identity,
                    file=path.name,
                    reference=reference,
                    condition=condition,
                    duration_ms=len(pcm) / 32,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
    manifest = dict(
        origin="Project-owned text synthesized with eSpeak NG1.51, en-us, 170 words/minute",
        audio_format="PCM16 little endian, mono, 16000Hz",
        scope="Synthetic fixture reliability and WER only; not human speech accuracy",
        fixtures=corpus,
    )
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"fixtures": len(corpus), "output": str(args.output)}))


if __name__ == "__main__":
    main()
