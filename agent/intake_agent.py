"""Intake agent: applies the table rules to a new intake (adjust) and looks up typed conditions (conditions),
asking the evidence agent to draft a rule for each real condition. The backend's bridge is the usual caller.
Run: uv run --group agent --env-file .env python -m agent.intake_agent"""
import os

from uagents import Agent, Protocol

from agent import dispatch
from agent.rpc import Caller, serve
from agent.wire import role_address, role_seed

SEED = os.getenv("AGENT_SEED", "dev-seed-change-me")
EVIDENCE = role_address(SEED, "evidence")

agent = Agent(name="rider-intake", seed=role_seed(SEED, "intake"), port=8002, mailbox=True,
              handle_messages_concurrently=True, readme_path="agent/README_intake.md",
              description="Applies context rules to a new waiting-room intake and looks up typed conditions.")
caller, proto = Caller(), Protocol("rider-intake", "0.1")


async def handle(ctx, kind: str, payload: str) -> str:
    async def ask_evidence(k: str, p: str) -> str:
        return await caller.call(ctx, EVIDENCE, k, p, accept_s=20, done_s=240)
    return await dispatch.intake(kind, payload, ask_evidence)


serve(proto, handle)
agent.include(proto)
agent.include(caller.protocol)

if __name__ == "__main__":
    agent.run()
