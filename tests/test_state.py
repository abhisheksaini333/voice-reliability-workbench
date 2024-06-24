import unittest
from voice.state import SessionState, StateError


class SessionStateTests(unittest.TestCase):
    def test_barge_in_fences_every_result_from_the_previous_turn(self):
        state = SessionState("session")
        state.connect()
        state.start()
        first = state.begin_turn()
        self.assertTrue(state.advance(first, "speaking"))
        second = state.begin_turn()
        self.assertFalse(state.current(first))
        self.assertFalse(state.advance(first, "speaking"))
        self.assertTrue(state.advance(second, "thinking"))
        self.assertEqual(state.phase, "thinking")

    def test_reconnect_cancels_old_connection_and_requires_recording_consent_again(
        self,
    ):
        state = SessionState("session")
        state.connect()
        state.start()
        first = state.begin_turn()
        state.disconnect()
        self.assertFalse(state.current(first))
        state.connect()
        self.assertFalse(state.recording)
        with self.assertRaises(StateError):
            state.begin_turn()
        state.start()
        second = state.begin_turn()
        self.assertGreater(second.connection, first.connection)
        self.assertGreater(second.epoch, first.epoch)
        self.assertFalse(state.current(first))

    def test_handoff_is_terminal_for_assistant_audio_and_acceptance_is_single_use(self):
        state = SessionState("session")
        state.connect()
        state.start()
        old = state.begin_turn()
        epoch = state.request_handoff()
        self.assertFalse(state.current(old))
        self.assertFalse(state.recording)
        with self.assertRaises(StateError):
            state.start()
        with self.assertRaises(StateError):
            state.accept_handoff(epoch - 1)
        state.accept_handoff(epoch)
        self.assertEqual(state.phase, "operator")
        with self.assertRaises(StateError):
            state.accept_handoff(epoch)
        state.close()
        with self.assertRaises(StateError):
            state.connect()
