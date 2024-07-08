import asyncio
import unittest
from voice.playback import PlaybackWindow, StaleAudio, SlowConsumer


class PlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_credit_window_blocks_until_oldest_chunk_is_acknowledged(self):
        window = PlaybackWindow(2, timeout=0.5)
        await window.reset(3)
        self.assertEqual(await window.reserve(3), 0)
        self.assertEqual(await window.reserve(3), 1)
        waiting = asyncio.create_task(window.reserve(3))
        await asyncio.sleep(0.01)
        self.assertFalse(waiting.done())
        self.assertFalse(await window.acknowledge(3, 1))
        self.assertTrue(await window.acknowledge(3, 0))
        self.assertEqual(await waiting, 2)
        self.assertFalse(await window.acknowledge(3, 0))

    async def test_interrupt_flushes_audio_and_fences_waiting_sender(self):
        window = PlaybackWindow(1, timeout=0.5)
        await window.reset(1)
        await window.reserve(1)
        waiting = asyncio.create_task(window.reserve(1))
        await asyncio.sleep(0.01)
        await window.reset(2)
        with self.assertRaises(StaleAudio):
            await waiting
        self.assertFalse(await window.acknowledge(1, 0))
        self.assertEqual(await window.reserve(2), 0)

    async def test_missing_playback_ack_has_a_bounded_deadline(self):
        window = PlaybackWindow(1, timeout=0.02)
        await window.reset(1)
        await window.reserve(1)
        with self.assertRaises(SlowConsumer):
            await window.drain(1)
        with self.assertRaises(SlowConsumer):
            await window.reserve(1)
