import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from voice.download import download_model


class ModelDownloadTests(unittest.TestCase):
    def test_bad_artifact_never_becomes_loadable_or_overwrites_existing_bytes(self):
        data = b"original artifact"
        spec = {
            "files": [
                {
                    "file": "weights.bin",
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "url": "https://huggingface.co/example/resolve/revision/weights.bin",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                download_model(root, spec, lambda *a, **k: io.BytesIO(b"bad artifact"))
            self.assertEqual(list(root.iterdir()), [])
            download_model(root, spec, lambda *a, **k: io.BytesIO(data))
            self.assertEqual((root / "weights.bin").read_bytes(), data)
            (root / "weights.bin").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                download_model(root, spec, lambda *a, **k: io.BytesIO(data))
            self.assertEqual((root / "weights.bin").read_bytes(), b"changed")
