"""Consistent live SQLite snapshots; restore by opening a new database path."""
import argparse
import os
from pathlib import Path
import sqlite3


def backup_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination)
    if not source.is_file():
        raise ValueError("existing source database required")
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    reader = writer = None
    try:
        reader = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        writer = sqlite3.connect(destination)
        reader.backup(writer)
        if writer.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("backup integrity check failed")
        writer.commit()
    except BaseException:
        if writer:
            writer.close()
            writer = None
        destination.unlink()
        raise
    finally:
        if reader:
            reader.close()
        if writer:
            writer.close()
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(backup_database(args.source, args.destination))


if __name__ == "__main__":
    main()
