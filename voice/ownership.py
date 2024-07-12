"""One process owns session recovery and live turn state for a workspace."""
import fcntl
import os
from pathlib import Path


class WorkspaceOwner:
    def __init__(self, database):
        self.database = Path(database).resolve()
        self.descriptor = None

    @property
    def held(self):
        return self.descriptor is not None

    def __enter__(self):
        if self.held:
            raise RuntimeError("workspace ownership is already held")
        descriptor = os.open(
            str(self.database) + ".owner", os.O_CREAT | os.O_RDWR, 0o600
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(descriptor)
            raise RuntimeError("another voice process owns this workspace") from error
        self.descriptor = descriptor
        return self

    def __exit__(self, *args):
        if self.descriptor is not None:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = None
