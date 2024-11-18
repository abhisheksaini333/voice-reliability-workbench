"""Fetch only original manifest artifacts; preserve all existing destination files."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen
from .artifacts import manifest, verify_model


def download_model(directory, specification, opener=urlopen):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for entry in specification["files"]:
        name = entry["file"]
        if Path(name).name != name:
            raise ValueError("direct artifact filename required")
        target = directory / name
        if target.exists() or target.is_symlink():
            verify_model(directory, {"files": [entry]})
            continue
        request = Request(
            entry["url"], headers={"User-Agent": "voice-reliability-workbench/0.1"}
        )
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".download-", dir=directory, delete=False
            ) as output:
                temporary = Path(output.name)
                checksum = hashlib.sha256()
                size = 0
                with opener(request, timeout=60) as response:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        size += len(block)
                        if size > entry["bytes"]:
                            raise ValueError("oversized artifact")
                        checksum.update(block)
                        output.write(block)
                output.flush()
                os.fsync(output.fileno())
            if size != entry["bytes"] or checksum.hexdigest() != entry["sha256"]:
                raise ValueError("original artifact hash or size differs")
            # A hard link publishes verified bytes atomically without replacement.
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return verify_model(directory, specification)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("models"))
    args = parser.parse_args()
    for name, subdirectory in [
        ("whisper", "whisper-tiny.en"),
        ("qwen", "qwen2-0.5b-instruct"),
    ]:
        files = download_model(args.directory / subdirectory, manifest(name))
        print(name + ": verified " + str(len(files)) + " original files")


if __name__ == "__main__":
    main()
