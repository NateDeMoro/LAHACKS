"""Evidence agent: for one real condition, searches PubMed and drafts a cited warning-tier rule from the preset
limit menu, or abstains. Run: uv run --group agent --env-file .env python -m agent.evidence_agent"""
import os

from uagents import Agent, Protocol

from agent import dispatch
from agent.rpc import serve
from agent.wire import role_seed

SEED = os.getenv("AGENT_SEED", "dev-seed-change-me")

agent = Agent(name="rider-evidence", seed=role_seed(SEED, "evidence"), port=8003, mailbox=True,
              handle_messages_concurrently=True, readme_path="agent/README_evidence.md",
              description="Drafts a cited, warning-only limit for a medical condition from PubMed abstracts.")
proto = Protocol("rider-evidence", "0.1")


async def handle(_ctx, kind: str, payload: str) -> str:
    return await dispatch.evidence(kind, payload)


serve(proto, handle)
agent.include(proto)

if __name__ == "__main__":
    agent.run()
