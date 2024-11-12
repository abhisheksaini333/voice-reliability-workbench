import json
import os
from pathlib import Path
import tempfile
import unittest
from voice.configuration import write_configuration
from voice.backup import backup_database
from voice.store import Store
from voice.state import SessionState


class InstallationTests(unittest.TestCase):
    def test_private_distinct_credentials_and_existing_configuration_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / ".env"
            write_configuration(
                output, root / "models", root / "espeak", root / "voice.sqlite", False
            )
            config = json.loads((root / ".env.json").read_text())
            keys = [
                config[name]
                for name in (
                    "VOICE_PROVIDER_KEY",
                    "VOICE_WORKSPACE_KEY",
                    "VOICE_OPERATOR_KEY",
                )
            ]
            self.assertEqual(len(set(keys)), 3)
            self.assertTrue(all(len(key) >= 32 for key in keys))
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                write_configuration(
                    output,
                    root / "models",
                    root / "espeak",
                    root / "voice.sqlite",
                    False,
                )
            self.assertEqual(before, output.read_bytes())

    def test_live_wal_backup_preserves_trace_without_overwriting_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "source.sqlite")
            state = SessionState("session")
            store.create("session", "hash", state.snapshot())
            store.event("session", 0, "created", {"text": "kept"})
            backup_database(store.path, root / "backup.sqlite")
            restored = Store(root / "backup.sqlite")
            self.assertEqual(restored.events("session")[0]["detail"]["text"], "kept")
            with self.assertRaises(FileExistsError):
                backup_database(store.path, root / "backup.sqlite")
            restored.close()
            store.close()
