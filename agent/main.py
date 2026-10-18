"""Fetch.ai agent: answers waiting-room questions in ASI:One from the local backend (read-only).
Run: uv run --group agent --env-file .env python -m agent.main"""
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from openai import AsyncOpenAI
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, EndSessionContent, TextContent, chat_protocol_spec,
)

from agent.tools import HANDLERS, TOOL_SPECS

SYSTEM = (
    "You assist a triage nurse with an ER waiting room monitored by wearable sensors. "
    "Use the tools to answer from live data only. A patient needs a recheck if they have an open alert "
    "or their latest risk level is warning or danger. Name each patient, say why, and order by urgency. "
    "If nobody needs a recheck, say so. Never invent data. "
    "To add a patient use submit_intake, then check_intake. Ask for age and sex if the nurse did not give them. "
    "When you report a check_intake result, say which typed conditions were real, which limits changed and why, "
    "and cite the sources. Say plainly when a limit came from a drafted rule: it is unreviewed and affects the "
    "warning level only. If a condition was not found or nothing changed, say that. Advice is advisory; the nurse decides."
)

agent = Agent(name="waiting-room-triage", seed=os.getenv("AGENT_SEED", "dev-seed-change-me"), port=8001, mailbox=True,
              handle_messages_concurrently=True, readme_path="agent/README.md",
              description="Waiting-room triage assistant: who needs a recheck, and add a patient with typed conditions.")
chat = Protocol(spec=chat_protocol_spec)


def _llm() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=os.getenv("ASI_BASE_URL", "https://api.asi1.ai/v1"),
                       api_key=os.getenv("FETCHAI_API_KEY", ""))


async def answer(question: str) -> str:
    """Runs the function-calling loop until the model gives a final answer."""
    if not os.getenv("FETCHAI_API_KEY"):
        return "The agent has no ASI:One key configured."
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    client, model = _llm(), os.getenv("ASI_MODEL", "asi1")
    for _ in range(6):
        msg = (await client.chat.completions.create(model=model, messages=messages, tools=TOOL_SPECS)).choices[0].message
        if not msg.tool_calls:
            return msg.content or "No answer."
        messages.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            try:
                result = await HANDLERS[call.function.name](**json.loads(call.function.arguments or "{}"))
            except Exception as e:  # backend down or bad args: let the model say so
                result = {"error": str(e)}
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
    return "I could not finish looking that up."


@chat.on_message(ChatMessage)
async def on_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
    if not text:
        return
    try:
        reply = await answer(text)
    except Exception as e:
        ctx.logger.error(f"answer failed: {e}")
        reply = "Sorry, I could not reach the language model."
    await ctx.send(sender, ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                                       content=[TextContent(type="text", text=reply), EndSessionContent(type="end-session")]))


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
