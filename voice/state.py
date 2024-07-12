"""Explicit connection and turn epochs fence every asynchronous completion."""
from dataclasses import dataclass


class StateError(ValueError):
    pass


@dataclass(frozen=True)
class TurnIdentity:
    session_id: str
    connection: int
    epoch: int


class SessionState:
    def __init__(self, session_id):
        self.session_id = session_id
        self.connection = 0
        self.epoch = 0
        self.phase = "idle"
        self.connected = False
        self.recording = False

    @classmethod
    def restore(cls, record):
        state = cls(record["id"])
        state.connection = record["connection"]
        state.epoch = record["epoch"]
        state.phase = record["phase"]
        return state

    def _invalidate(self):
        self.epoch += 1

    def connect(self):
        if self.phase == "closed":
            raise StateError("session is closed")
        self.connection += 1
        self._invalidate()
        self.connected = True
        self.recording = False
        if self.phase not in {"handoff_pending", "operator"}:
            self.phase = "idle"
        return self.connection

    def start(self):
        if not self.connected or self.phase in {
            "handoff_pending",
            "operator",
            "closed",
        }:
            raise StateError("assistant recording is unavailable")
        self.recording = True
        if self.phase == "idle":
            self.phase = "listening"

    def begin_turn(self):
        if not self.connected or not self.recording:
            raise StateError("explicit recording consent is required")
        self._invalidate()
        self.phase = "listening"
        return TurnIdentity(self.session_id, self.connection, self.epoch)

    def current(self, identity):
        return (
            self.connected
            and self.phase not in {"handoff_pending", "operator", "closed"}
            and identity == TurnIdentity(self.session_id, self.connection, self.epoch)
        )

    def advance(self, identity, phase):
        if phase not in {"thinking", "speaking", "listening", "idle"}:
            raise StateError("invalid assistant phase")
        if not self.current(identity):
            return False
        self.phase = phase
        return True

    def interrupt(self):
        self._invalidate()
        if self.phase not in {"handoff_pending", "operator", "closed"}:
            self.phase = "listening" if self.recording else "idle"
        return self.epoch

    def stop(self):
        self.recording = False
        return self.interrupt()

    def disconnect(self):
        self.connected = False
        self.recording = False
        self._invalidate()
        if self.phase not in {"handoff_pending", "operator", "closed"}:
            self.phase = "disconnected"

    def request_handoff(self):
        if self.phase in {"handoff_pending", "operator", "closed"}:
            raise StateError("handoff is unavailable in the current phase")
        self._invalidate()
        self.recording = False
        self.phase = "handoff_pending"
        return self.epoch

    def accept_handoff(self, expected_epoch):
        if self.phase != "handoff_pending" or self.epoch != expected_epoch:
            raise StateError("handoff changed or was already accepted")
        self.phase = "operator"

    def close(self):
        self._invalidate()
        self.recording = False
        self.connected = False
        self.phase = "closed"

    def snapshot(self):
        return dict(
            session_id=self.session_id,
            connection=self.connection,
            epoch=self.epoch,
            phase=self.phase,
            connected=self.connected,
            recording=self.recording,
        )
