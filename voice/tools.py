"""Read-only demonstration tools with deadline and identity-bound receipts."""
import asyncio
from dataclasses import asdict, dataclass
import time
from uuid import uuid4
from .state import TurnIdentity


class ToolError(ValueError):
    pass


@dataclass
class Receipt:
    id: str
    identity: TurnIdentity
    service: str
    deadline: float
    state: str = "pending"
    result: dict | None = None

    def snapshot(self):
        return asdict(self)


async def service_status(service):
    return {
        "service": service,
        "status": {"atlas": "operational", "beacon": "degraded"}[service],
    }


class ToolManager:
    def __init__(self, is_current, *, clock=time.monotonic):
        self.is_current = is_current
        self.clock = clock
        self.receipts = {}

    def issue(self, identity, service, timeout=2):
        if not isinstance(service, str) or service not in {"atlas", "beacon"}:
            raise ToolError("tool is outside the read-only allowlist")
        if not 0 < timeout <= 10 or not self.is_current(identity):
            raise ToolError("current turn and bounded tool deadline required")
        if len(self.receipts) >= 100:
            raise ToolError("session tool receipt limit reached")
        receipt = Receipt(uuid4().hex, identity, service, self.clock() + timeout)
        self.receipts[receipt.id] = receipt
        return receipt

    def finish(self, receipt_id, identity, result):
        receipt = self.receipts.get(receipt_id)
        if (
            receipt is None
            or receipt.identity != identity
            or receipt.state != "pending"
        ):
            return False
        if not self.is_current(identity):
            receipt.state = "cancelled"
            return False
        if self.clock() >= receipt.deadline:
            receipt.state = "timed_out"
            return False
        if not isinstance(result, dict) or set(result) != {"service", "status"}:
            raise ToolError("invalid tool result contract")
        if result["service"] != receipt.service or result["status"] not in (
            "operational",
            "degraded",
        ):
            raise ToolError("tool result does not match the issued receipt")
        receipt.result = dict(result)
        receipt.state = "completed"
        return True

    async def execute(self, receipt, operation=service_status):
        if self.receipts.get(receipt.id) is not receipt or receipt.state != "pending":
            raise ToolError("unissued or already completed receipt")
        try:
            result = await asyncio.wait_for(
                operation(receipt.service), max(0, receipt.deadline - self.clock())
            )
            self.finish(receipt.id, receipt.identity, result)
        except asyncio.TimeoutError:
            receipt.state = "timed_out"
        except asyncio.CancelledError:
            receipt.state = "cancelled"
            raise
        except Exception:
            receipt.state = "failed"
        return receipt.snapshot()

    def cancel_stale(self):
        for receipt in self.receipts.values():
            if receipt.state == "pending" and not self.is_current(receipt.identity):
                receipt.state = "cancelled"
