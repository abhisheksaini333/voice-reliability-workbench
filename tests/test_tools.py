import asyncio
import unittest
from voice.state import SessionState
from voice.tools import ToolManager, ToolError


class ToolReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = SessionState("one")
        self.state.connect()
        self.state.start()
        self.identity = self.state.begin_turn()
        self.manager = ToolManager(self.state.current)

    async def test_timeout_rejects_late_duplicate_results(self):
        receipt = self.manager.issue(self.identity, "atlas", timeout=0.02)

        async def slow_lookup(service):
            await asyncio.sleep(0.1)
            return {"service": service, "status": "operational"}

        result = await self.manager.execute(receipt, slow_lookup)
        self.assertEqual(result["state"], "timed_out")
        self.assertFalse(
            self.manager.finish(
                receipt.id, self.identity, {"service": "atlas", "status": "operational"}
            )
        )

    async def test_completion_is_bound_to_current_turn_and_accepted_once(self):
        receipt = self.manager.issue(self.identity, "beacon")
        result = {"service": "beacon", "status": "degraded"}
        self.assertTrue(self.manager.finish(receipt.id, self.identity, result))
        self.assertFalse(self.manager.finish(receipt.id, self.identity, result))
        later = self.manager.issue(self.identity, "atlas")
        self.state.interrupt()
        self.assertFalse(
            self.manager.finish(
                later.id, self.identity, {"service": "atlas", "status": "operational"}
            )
        )
        self.assertEqual(later.state, "cancelled")

    async def test_untrusted_tool_names_or_results_cannot_expand_the_allowlist(self):
        with self.assertRaises(ToolError):
            self.manager.issue(self.identity, "run_shell")
        receipt = self.manager.issue(self.identity, "atlas")
        with self.assertRaises(ToolError):
            self.manager.finish(
                receipt.id,
                self.identity,
                {"service": "atlas", "status": "operational", "command": "delete"},
            )
        result = await self.manager.execute(receipt)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["result"]["service"], "atlas")
