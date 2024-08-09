import asyncio
import threading
import time
import unittest
from voice.worker import NativeWorker
from voice.provider_contracts import ProviderFailure


class NativeWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_does_not_release_capacity_before_native_thread_returns(
        self,
    ):
        worker = NativeWorker()
        entered = threading.Event()
        release = threading.Event()

        def operation(budget):
            entered.set()
            release.wait(2)
            budget.check()
            return {"text": "done"}

        task = asyncio.create_task(worker.run("first", "model", operation, 1))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0.01)
        self.assertIsNotNone(worker.active)
        self.assertTrue(worker.active.stop.is_set())
        with self.assertRaises(ProviderFailure) as caught:
            await worker.run("second", "model", operation, 1)
        self.assertEqual(caught.exception.code, "provider_busy")
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(worker.active)

    async def test_timeout_waits_for_native_cleanup_and_duplicate_identity_is_rejected(
        self,
    ):
        worker = NativeWorker()

        def operation(budget):
            time.sleep(0.08)
            return {"text": "late"}

        task = asyncio.create_task(worker.run("slow", "model", operation, 0.02))
        await asyncio.sleep(0.04)
        self.assertIsNotNone(worker.active)
        with self.assertRaises(ProviderFailure) as caught:
            await task
        self.assertEqual(caught.exception.code, "provider_timeout")
        self.assertIsNone(worker.active)
        with self.assertRaises(ProviderFailure) as caught:
            await worker.run("slow", "model", operation, 1)
        self.assertEqual(caught.exception.code, "duplicate_job")

    async def test_unexpected_native_errors_do_not_expose_private_details(self):
        worker = NativeWorker()

        def operation(budget):
            raise RuntimeError("private key and path")

        with self.assertRaises(ProviderFailure) as caught:
            await worker.run("broken", "stt", operation, 1)
        self.assertEqual(caught.exception.code, "provider_failed")
        self.assertNotIn("private", str(caught.exception))
        self.assertIsNone(worker.active)
