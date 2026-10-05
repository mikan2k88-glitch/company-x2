"""Pure transaction rules. No network calls or simulated revenue."""
from dataclasses import dataclass, replace
from enum import Enum

class State(str, Enum):
    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    AGREED = "agreed"
    AUTHORIZED = "authorized"
    PRODUCED = "produced"
    VERIFIED = "verified"
    DELIVERED = "delivered"
    PAID = "paid"
    CANCELLED = "cancelled"

@dataclass(frozen=True)
class Job:
    job_id: str
    state: State = State.DISCOVERED
    price_jpy: int = 0
    cost_limit_jpy: int = 0

def advance(job: Job, target: State, *, evidence: dict) -> Job:
    """Caller must persist atomically and verify evidence against providers."""
    if target == State.CANCELLED:
        if job.state in (State.PAID, State.CANCELLED):
            raise ValueError("terminal state; paid jobs need a separate refund flow")
        if evidence.get("payment_released") is not True:
            raise ValueError("confirmed release or absence of authorization required")
        return replace(job, state=target)
    transitions = {
        State.DISCOVERED: (State.QUALIFIED, "real_opportunity"),
        State.QUALIFIED: (State.AGREED, "customer_agreement"),
        State.AGREED: (State.AUTHORIZED, "authorization_confirmed"),
        State.AUTHORIZED: (State.PRODUCED, "artifact_saved"),
        State.PRODUCED: (State.VERIFIED, "quality_passed"),
        State.VERIFIED: (State.DELIVERED, "delivery_confirmed"),
        State.DELIVERED: (State.PAID, "capture_confirmed"),
    }
    expected = transitions.get(job.state)
    if expected is None or expected[0] != target:
        raise ValueError("invalid transition")
    if evidence.get(expected[1]) is not True or evidence.get("mode") != "live":
        raise ValueError("verified live evidence required")
    if target == State.QUALIFIED:
        if not 0 <= job.cost_limit_jpy < job.price_jpy:
            raise ValueError("positive contribution margin required")
        if evidence.get("supported_service") is not True:
            raise ValueError("unsupported service")
    return replace(job, state=target)

