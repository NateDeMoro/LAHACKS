"""Messages the agents exchange. Payloads are JSON strings of our own contracts (backend/contracts.py,
backend/handlers.py), validated by the receiver, so uagents never sees our models."""
from typing import Literal

from uagents import Model
from uagents_core.identity import Identity

ROLES = ("intake", "evidence")


class AgentRequest(Model):
    request_id: str
    kind: str  # adjust | conditions (intake agent), draft (evidence agent)
    payload: str


class AgentReply(Model):
    request_id: str
    stage: Literal["accepted", "done", "error"]  # accepted comes at once, done or error when the work ends
    payload: str = ""
    error: str | None = None


def role_seed(seed: str, role: str) -> str:
    """The coordinator keeps AGENT_SEED itself; each specialist derives its own so addresses stay stable."""
    return f"{seed}:{role}"


def role_address(seed: str, role: str) -> str:
    return Identity.from_seed(role_seed(seed, role), 0).address
