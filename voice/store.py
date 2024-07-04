"""Transactional voice transcripts with epoch fencing and bounded session history."""
from contextlib import contextmanager
import json
import math
import re
import sqlite3
import threading
import time


def redact(text):
    if not isinstance(text, str) or len(text) > 4000:
        raise ValueError("bounded transcript text required")
    text = re.sub(r"(?i)\b(bearer\s+)[A-Za-z0-9._~-]{8,}", r"\1[REDACTED]", text)
    text = re.sub(
        r"(?i)\b(token|api[_ -]?key|password)\s*[=:]\s*[^\s,;]{8,}",
        r"\1=[REDACTED]",
        text,
    )
    return re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", text)


class Store:
    def __init__(self, path):
        self.connection = sqlite3.connect(
            path, timeout=5, check_same_thread=False, isolation_level=None
        )
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL, phase TEXT NOT NULL, epoch INTEGER NOT NULL,
                connection INTEGER NOT NULL, connected INTEGER NOT NULL, recording INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turns (
                session_id TEXT NOT NULL REFERENCES sessions(id), epoch INTEGER NOT NULL,
                connection INTEGER NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL, transcript TEXT NOT NULL DEFAULT '', reply TEXT NOT NULL DEFAULT '',
                timings TEXT NOT NULL DEFAULT '{}', error_code TEXT,
                PRIMARY KEY(session_id, epoch)
            );
        """
        )

    @contextmanager
    def transaction(self):
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def create(self, session_id, token_hash, state):
        with self.transaction() as connection:
            if connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] >= 100:
                raise ValueError(
                    "local session capacity reached; archive before starting a new workspace"
                )
            now = time.time()
            connection.execute(
                """
                INSERT INTO sessions(id, token_hash, created, updated, phase, epoch, connection, connected, recording)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    session_id,
                    token_hash,
                    now,
                    now,
                    state["phase"],
                    state["epoch"],
                    state["connection"],
                    int(state["connected"]),
                    int(state["recording"]),
                ),
            )

    def session(self, session_id):
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            return dict(row) if row else None

    def sessions(self):
        with self.lock:
            return [
                dict(row)
                for row in self.connection.execute(
                    "SELECT * FROM sessions ORDER BY created DESC LIMIT 100"
                )
            ]

    def save_state(self, state):
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE sessions SET updated = ?, phase = ?, epoch = ?, connection = ?, connected = ?, recording = ?
                WHERE id = ? AND epoch <= ? AND connection <= ?
            """,
                (
                    time.time(),
                    state["phase"],
                    state["epoch"],
                    state["connection"],
                    int(state["connected"]),
                    int(state["recording"]),
                    state["session_id"],
                    state["epoch"],
                    state["connection"],
                ),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                """
                UPDATE turns SET state = 'cancelled', error_code = 'superseded', updated = ?
                WHERE session_id = ? AND state = 'running' AND (epoch != ? OR connection != ?)
            """,
                (time.time(), state["session_id"], state["epoch"], state["connection"]),
            )
            return True

    @staticmethod
    def _current(connection, identity):
        return (
            connection.execute(
                """
            SELECT 1 FROM sessions WHERE id = ? AND epoch = ? AND connection = ?
            AND connected = 1 AND phase NOT IN ('handoff_pending', 'operator', 'closed')
        """,
                (identity.session_id, identity.epoch, identity.connection),
            ).fetchone()
            is not None
        )

    def begin_turn(self, identity):
        with self.transaction() as connection:
            if not self._current(connection, identity):
                raise ValueError("stale turn cannot start")
            count = connection.execute(
                "SELECT COUNT(*) FROM turns WHERE session_id = ?",
                (identity.session_id,),
            ).fetchone()[0]
            if count >= 100:
                raise ValueError("session turn limit reached")
            now = time.time()
            connection.execute(
                """
                INSERT INTO turns(session_id, epoch, connection, state, created, updated)
                VALUES (?, ?, ?, 'running', ?, ?)
            """,
                (identity.session_id, identity.epoch, identity.connection, now, now),
            )

    def transcribe(self, identity, text):
        text = redact(text)
        with self.transaction() as connection:
            if not self._current(connection, identity):
                return False
            cursor = connection.execute(
                """
                UPDATE turns SET transcript = ?, updated = ?
                WHERE session_id = ? AND epoch = ? AND connection = ? AND state = 'running'
            """,
                (
                    text,
                    time.time(),
                    identity.session_id,
                    identity.epoch,
                    identity.connection,
                ),
            )
            return cursor.rowcount == 1

    def complete(self, identity, reply, timings, *, error_code=None):
        reply = redact(reply)
        allowed = {
            "stt_ms",
            "model_ms",
            "tts_ms",
            "first_audio_ms",
            "interruption_ms",
            "total_ms",
        }
        if set(timings) - allowed or any(
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
            for value in timings.values()
        ):
            raise ValueError("bounded stage timings required")
        if error_code is not None and not re.fullmatch(r"[a-z_]{1,40}", error_code):
            raise ValueError("safe error code required")
        with self.transaction() as connection:
            if not self._current(connection, identity):
                return False
            cursor = connection.execute(
                """
                UPDATE turns SET reply = ?, timings = ?, state = ?, updated = ?, error_code = ?
                WHERE session_id = ? AND epoch = ? AND connection = ? AND state = 'running'
            """,
                (
                    reply,
                    json.dumps(timings),
                    "failed" if error_code else "completed",
                    time.time(),
                    error_code,
                    identity.session_id,
                    identity.epoch,
                    identity.connection,
                ),
            )
            return cursor.rowcount == 1

    def turns(self, session_id):
        with self.lock:
            records = [
                dict(row)
                for row in self.connection.execute(
                    """
                SELECT * FROM turns WHERE session_id = ? ORDER BY epoch LIMIT 100
            """,
                    (session_id,),
                )
            ]
        for record in records:
            record["timings"] = json.loads(record["timings"])
        return records

    def close(self):
        with self.lock:
            self.connection.close()
