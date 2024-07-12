import tempfile
import unittest
from pathlib import Path
from voice.ownership import WorkspaceOwner
from voice.state import SessionState
from voice.store import Store


class RecoveryTests(unittest.TestCase):
    def test_restart_abandons_incomplete_turn_only_under_exclusive_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice.sqlite"
            store = Store(path)
            state = SessionState("one")
            state.connect()
            state.start()
            identity = state.begin_turn()
            store.create("one", "hash", state.snapshot())
            store.begin_turn(identity)
            store.transcribe(identity, "Please help with Atlas.")
            owner = WorkspaceOwner(path)
            with self.assertRaises(RuntimeError):
                store.recover(owner)
            with owner:
                with self.assertRaises(RuntimeError):
                    with WorkspaceOwner(path):
                        pass
                self.assertEqual(store.recover(owner), 1)
            restored = SessionState.restore(store.session("one"))
            self.assertFalse(restored.connected)
            self.assertFalse(restored.recording)
            self.assertGreater(restored.epoch, identity.epoch)
            self.assertEqual(store.turns("one")[0]["state"], "abandoned")
            self.assertEqual(
                store.turns("one")[0]["transcript"], "Please help with Atlas."
            )
            self.assertFalse(store.complete(identity, "late work", {}))
            with WorkspaceOwner(path):
                pass
            store.close()
