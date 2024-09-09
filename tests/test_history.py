import tempfile
import unittest
from pathlib import Path
from voice.state import SessionState
from voice.store import Store


class HistoryTests(unittest.TestCase):
    def test_draft_reply_survives_handoff_and_old_accept_snapshot_is_fenced(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "voice.sqlite")
            state = SessionState("session")
            store.create("session", "hash", state.snapshot())
            state.connect()
            state.start()
            turn = state.begin_turn()
            store.save_state(state.snapshot())
            store.begin_turn(turn)
            self.assertTrue(
                store.draft_reply(turn, "Please provide the ticket number.")
            )
            state.request_handoff()
            pending = state.snapshot()
            store.save_state(pending)
            state.accept_handoff(state.epoch)
            store.save_state(state.snapshot())
            self.assertFalse(store.save_state(pending))
            self.assertEqual(
                store.turns("session")[0]["reply"], "Please provide the ticket number."
            )
            self.assertFalse(store.draft_reply(turn, "stale"))
            store.close()

    def test_timeline_is_bounded_redacted_and_rejects_old_epochs(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "voice.sqlite")
            state = SessionState("session")
            store.create("session", "hash", state.snapshot())
            for index in range(1005):
                self.assertTrue(
                    store.event(
                        "session",
                        0,
                        "tool",
                        {"text": "token=secretvalue123", "index": index},
                    )
                )
            events = store.events("session")
            self.assertEqual(len(events), 1000)
            self.assertEqual(events[0]["detail"]["index"], 5)
            self.assertNotIn("secretvalue123", str(events))
            state.connect()
            store.save_state(state.snapshot())
            self.assertFalse(store.event("session", 0, "late", {}))
            store.close()
