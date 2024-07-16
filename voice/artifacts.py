"""Original model bytes are verified before any checkpoint is loaded."""
import hashlib
import json
from pathlib import Path


def manifest(name):
    if name not in {"whisper", "qwen"}:
        raise ValueError("unknown model manifest")
    return json.loads((Path(__file__).parent / "data" / (name + ".json")).read_text())


def verify_model(directory, specification):
    directory = Path(directory).resolve()
    verified = []
    for entry in specification["files"]:
        name = entry["file"]
        path = directory / name
        if (
            Path(name).name != name
            or path.is_symlink()
            or path.resolve().parent != directory
        ):
            raise ValueError("model artifacts must be direct regular files")
        if not path.is_file() or path.stat().st_size != entry["bytes"]:
            raise ValueError("model artifact is missing or has the wrong size: " + name)
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != entry["sha256"]:
            raise ValueError("model artifact hash differs: " + name)
        verified.append(name)
    if not verified:
        raise ValueError("empty model manifest")
    return verified
