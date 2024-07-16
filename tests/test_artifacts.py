import hashlib
import tempfile
import unittest
from pathlib import Path
from voice.artifacts import verify_model


class ArtifactTests(unittest.TestCase):
    def test_hash_size_and_direct_file_identity_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "model").write_bytes(b"weights")
            manifest = {
                "files": [
                    {
                        "file": "model",
                        "bytes": 7,
                        "sha256": hashlib.sha256(b"weights").hexdigest(),
                    }
                ]
            }
            self.assertEqual(verify_model(path, manifest), ["model"])
            (path / "model").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                verify_model(path, manifest)
            (path / "model").unlink()
            (path / "other").write_bytes(b"weights")
            (path / "model").symlink_to(path / "other")
            with self.assertRaises(ValueError):
                verify_model(path, manifest)
