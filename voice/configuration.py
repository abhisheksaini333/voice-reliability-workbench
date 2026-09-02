"""Generate private local configuration without replacing existing credentials."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
from .artifacts import manifest, verify_model


def write_configuration(output, models, espeak, database, diagnostics):
    output = Path(output)
    json_path = output.with_name(output.name + ".json")
    if (
        output.exists()
        or output.is_symlink()
        or json_path.exists()
        or json_path.is_symlink()
    ):
        raise FileExistsError("existing credentials are preserved")
    models, espeak, database = (
        Path(path).resolve() for path in (models, espeak, database)
    )
    config = {
        "VOICE_PROVIDER_KEY": secrets.token_urlsafe(32),
        "VOICE_WORKSPACE_KEY": secrets.token_urlsafe(32),
        "VOICE_OPERATOR_KEY": secrets.token_urlsafe(32),
        "VOICE_PROVIDER_URL": "http://127.0.0.1:8097",
        "VOICE_DATABASE": str(database),
        "VOICE_WHISPER_PATH": str(models / "whisper-tiny.en"),
        "VOICE_QWEN_PATH": str(models / "qwen2-0.5b-instruct"),
        "VOICE_ESPEAK_BINARY": str(espeak),
        "WHISPER_MODEL_DIRECTORY": str(models / "whisper-tiny.en"),
        "QWEN_MODEL_DIRECTORY": str(models / "qwen2-0.5b-instruct"),
        "VOICE_ALLOW_FAULTS": "1" if diagnostics else "0",
        "TOKENIZERS_PARALLELISM": "false",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path, content in (
            (
                output,
                "".join(
                    key + "=" + shlex.quote(value) + "\n"
                    for key, value in config.items()
                ),
            ),
            (json_path, json.dumps(config, indent=2) + "\n"),
        ):
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            created.append(path)
            with os.fdopen(fd, "w") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        for path in created:
            path.unlink()
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--espeak", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("var/voice.sqlite"))
    parser.add_argument("--output", type=Path, default=Path(".env"))
    parser.add_argument("--diagnostics", action="store_true")
    args = parser.parse_args()
    verify_model(args.models / "whisper-tiny.en", manifest("whisper"))
    verify_model(args.models / "qwen2-0.5b-instruct", manifest("qwen"))
    if not args.espeak.is_file() or not os.access(args.espeak, os.X_OK):
        parser.error("an executable eSpeakNG1.51 path is required")
    args.database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = write_configuration(
        args.output, args.models, args.espeak, args.database, args.diagnostics
    )
    print(
        "Private configuration written to " + str(path) + " and " + str(path) + ".json"
    )


if __name__ == "__main__":
    main()
