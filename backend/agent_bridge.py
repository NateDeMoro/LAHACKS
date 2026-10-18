"""Backend side of the agents: a small agent of our own sends requests to the intake agent and waits for the
replies, so IntakeService can run its adjuster and condition steps there. Any failure falls back to the
in-process code, so a dead agent never blocks an intake. uagents is imported only when the bridge starts."""
import asyncio
import logging
import threading
from typing import Callable

from backend import handlers
from backend.config import AgentsConfig, CONFIG
from backend.conditions import service
from backend.contracts import PatientContext

log = logging.getLogger(__name__)


class AgentCallError(Exception):
    """The agent did not answer, failed, or timed out."""


class AgentBridge:
    def __init__(self, cfg: AgentsConfig = CONFIG.agents):
        self._cfg = cfg
        self._ready = threading.Event()
        self._loop = self._ctx = self._caller = None

    def start(self, wait_s: float = 30.0) -> bool:
        threading.Thread(target=self._run, name="agent-bridge", daemon=True).start()
        up = self._ready.wait(wait_s)
        if not up:
            log.warning("agent bridge did not start within %gs; intakes run in-process", wait_s)
        return up

    def _run(self):
        from uagents import Agent
        from agent.rpc import Caller
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        agent = Agent(name="rider-backend", seed=f"{self._cfg.seed}:backend", port=self._cfg.bridge_port,
                      endpoint=[f"http://127.0.0.1:{self._cfg.bridge_port}/submit"], loop=loop,
                      enable_agent_inspector=False, handle_messages_concurrently=True)
        caller = Caller()
        agent.include(caller.protocol)

        @agent.on_event("startup")
        async def up(ctx):
            self._loop, self._ctx, self._caller = loop, ctx, caller
            self._ready.set()

        agent.run()

    def call(self, role: str, kind: str, payload: str, *, done_s: float) -> str:
        from agent.wire import role_address
        if not self._ready.is_set():
            raise AgentCallError("bridge is not running")
        fut = asyncio.run_coroutine_threadsafe(
            self._caller.call(self._ctx, role_address(self._cfg.seed, role), kind, payload,
                              accept_s=self._cfg.accept_s, done_s=done_s), self._loop)
        try:
            return fut.result(timeout=self._cfg.accept_s + done_s + 5)
        except Exception as e:
            fut.cancel()
            raise AgentCallError(str(e) or type(e).__name__) from e


def agent_fns(bridge: AgentBridge, cfg: AgentsConfig = CONFIG.agents, *, call: Callable | None = None,
              fallback_adjust=handlers.adjust, fallback_conditions=None) -> tuple[Callable, Callable]:
    """(adjust_fn, condition_fn) for IntakeService. `call` defaults to the bridge; tests pass a fake."""
    call = call or bridge.call
    if fallback_conditions is None:
        from backend.intake.service import default_condition_fn as fallback_conditions

    def adjust(ctx: PatientContext):
        try:
            return handlers.AdjustReply.model_validate_json(
                call("intake", "adjust", ctx.model_dump_json(exclude_none=True), done_s=cfg.adjust_s))
        except Exception as e:
            log.warning("adjust ran in-process (%s)", e)
            return fallback_adjust(ctx)

    def conditions(ctx: PatientContext):
        try:
            rep = handlers.ConditionsReply.model_validate_json(
                call("intake", "conditions", ctx.model_dump_json(exclude_none=True), done_s=cfg.conditions_s))
        except Exception as e:
            log.warning("conditions ran in-process (%s)", e)
            return fallback_conditions(ctx)
        return service.process(
            ctx, resolve_fn=lambda terms: rep.resolution.items,
            draft_fn=lambda code, name: rep.drafts.get(code) or handlers.EvidenceReply(infra_error="no draft returned"))

    return adjust, conditions
