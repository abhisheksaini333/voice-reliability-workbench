"""Application-level playback credits bound audio queued ahead of the listener."""
import asyncio
import time


class StaleAudio(ValueError):
    pass


class SlowConsumer(TimeoutError):
    pass


class PlaybackWindow:
    def __init__(self, capacity=4, timeout=3):
        if type(capacity) is not int or not 1 <= capacity <= 8 or not 0 < timeout <= 10:
            raise ValueError("bounded playback window required")
        self.capacity = capacity
        self.timeout = timeout
        self.epoch = 0
        self.next_sequence = 0
        self.pending = []
        self.condition = asyncio.Condition()

    def _current(self, epoch):
        if epoch != self.epoch:
            raise StaleAudio("audio belongs to an invalidated turn")

    async def reset(self, epoch):
        async with self.condition:
            if epoch < self.epoch:
                raise StaleAudio("cannot restore an old audio epoch")
            self.epoch = epoch
            self.pending.clear()
            self.next_sequence = 0
            self.condition.notify_all()

    async def _wait(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SlowConsumer("playback acknowledgement deadline expired")
        try:
            await asyncio.wait_for(self.condition.wait(), remaining)
        except asyncio.TimeoutError as error:
            raise SlowConsumer("playback acknowledgement deadline expired") from error

    async def reserve(self, epoch):
        deadline = time.monotonic() + self.timeout
        async with self.condition:
            self._current(epoch)
            while len(self.pending) >= self.capacity:
                await self._wait(deadline)
                self._current(epoch)
            sequence = self.next_sequence
            self.next_sequence += 1
            self.pending.append(sequence)
            return sequence

    async def acknowledge(self, epoch, sequence):
        async with self.condition:
            if epoch != self.epoch or not self.pending or self.pending[0] != sequence:
                return False
            self.pending.pop(0)
            self.condition.notify_all()
            return True

    async def drain(self, epoch):
        deadline = time.monotonic() + self.timeout
        async with self.condition:
            self._current(epoch)
            while self.pending:
                await self._wait(deadline)
                self._current(epoch)
