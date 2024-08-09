"""One native job at a time; cancellation never frees a running thread's slot."""
import asyncio
from collections import deque
from dataclasses import dataclass
import re
import threading
import time
from .provider_contracts import ProviderFailure, WorkBudget


@dataclass
class ActiveJob:
    id: str
    stage: str
    stop: threading.Event
    started: float
    task: asyncio.Task | None = None


class NativeWorker:
    def __init__(self):
        self.active = None
        self.completed = deque(maxlen=256)
        self.closing = False

    async def run(self, identity, stage, operation, timeout):
        if not isinstance(identity, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,100}", identity
        ):
            raise ProviderFailure("invalid_job")
        if stage not in ("stt", "model", "tts") or not 0 < timeout <= 30:
            raise ProviderFailure("invalid_job")
        if self.closing:
            raise ProviderFailure("provider_draining")
        if identity in self.completed or (self.active and self.active.id == identity):
            raise ProviderFailure("duplicate_job")
        if self.active is not None:
            raise ProviderFailure("provider_busy")
        job = ActiveJob(identity, stage, threading.Event(), time.monotonic())
        self.active = job
        budget = WorkBudget(job.stop, job.started + timeout)
        native = asyncio.create_task(asyncio.to_thread(operation, budget))
        job.task = native
        try:
            result = await asyncio.wait_for(asyncio.shield(native), timeout)
            budget.check()
            return result
        except asyncio.TimeoutError:
            job.stop.set()
            await asyncio.shield(asyncio.gather(native, return_exceptions=True))
            raise ProviderFailure("provider_timeout") from None
        except asyncio.CancelledError:
            job.stop.set()
            await asyncio.shield(asyncio.gather(native, return_exceptions=True))
            raise
        except ProviderFailure:
            raise
        except Exception:
            raise ProviderFailure("provider_failed") from None
        finally:
            # Native work is joined in every cancellation/deadline path above.
            self.completed.append(identity)
            self.active = None

    def cancel(self, identity):
        if self.active is None or self.active.id != identity:
            return False
        self.active.stop.set()
        return True

    def snapshot(self):
        job = self.active
        return dict(
            active=1 if job else 0,
            stage=job.stage if job else None,
            cancellation_pending=bool(job and job.stop.is_set()),
            closing=self.closing,
        )

    async def close(self):
        self.closing = True
        if self.active is not None:
            self.active.stop.set()
            await asyncio.shield(
                asyncio.gather(self.active.task, return_exceptions=True)
            )
