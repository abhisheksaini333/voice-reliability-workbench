import tempfile
import threading
import unittest
from pathlib import Path
from voice.state import SessionState
from voice.store import Store


class DurableSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "voice.sqlite"
        self.store = Store(self.path)
        self.state = SessionState("session")
        self.store.create("session", "hash-only", self.state.snapshot())
        self.state.connect()
        self.state.start()
        self.identity = self.state.begin_turn()
        self.store.save_state(self.state.snapshot())
        self.store.begin_turn(self.identity)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_stale_completion_cannot_overwrite_interrupted_transcript(self):
        self.assertTrue(
            self.store.transcribe(
                self.identity, "My token=privatecredential123 is missing"
            )
        )
        self.state.interrupt()
        self.store.save_state(self.state.snapshot())
        self.assertFalse(self.store.complete(self.identity, "late response", {}))
        turns = self.store.turns("session")
        self.assertNotIn("privatecredential123", str(turns))
        self.assertEqual(turns[0]["state"], "cancelled")
        self.assertEqual(turns[0]["reply"], "")

    def test_two_connections_accept_only_one_terminal_result(self):
        other = Store(self.path)
        barrier = threading.Barrier(2)
        accepted = []

        def finish(store):
            barrier.wait()
            accepted.append(
                store.complete(self.identity, "one answer", {"model_ms": 10})
            )

        threads = [
            threading.Thread(target=finish, args=(store,))
            for store in (self.store, other)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(accepted), [False, True])
        self.assertEqual(len(self.store.turns("session")), 1)
        other.close()

    def test_handoff_snapshot_contains_context_and_rejects_old_state(self):
        self.store.transcribe(self.identity, "Please ask an operator about Atlas.")
        self.store.complete(self.identity, "I can hand this to an operator.", {})
        old = self.state.snapshot()
        self.state.request_handoff()
        self.assertTrue(self.store.save_state(self.state.snapshot()))
        self.assertFalse(self.store.save_state(old))
        snapshot = self.store.session("session")
        self.assertEqual(snapshot["phase"], "handoff_pending")
        self.assertEqual(
            self.store.turns("session")[0]["transcript"],
            "Please ask an operator about Atlas.",
        )
