"""Request/reply over agent messages. A caller sends an AgentRequest and waits for the matching AgentReply:
an immediate "accepted" (so a dead peer fails fast) and then "done" or "error"."""
import asyncio
import uuid

from uagents import Context, Protocol

from agent.wire import AgentReply, AgentRequest


class AgentUnreachable(Exception):
    """No "accepted" came back in time: the peer is down or cannot be resolved."""


class AgentFailed(Exception):
    """The peer accepted the work but reported an error, or never finished it."""


class Caller:
    def __init__(self):
        self._accepted: dict[str, asyncio.Future] = {}
        self._done: dict[str, asyncio.Future] = {}
        self.protocol = Protocol("rider-replies", "0.1")
        self.protocol.on_message(AgentReply)(self._on_reply)

    async def _on_reply(self, _ctx: Context, _sender: str, msg: AgentReply):
        acc, done = self._accepted.get(msg.request_id), self._done.get(msg.request_id)
        if msg.stage == "accepted" and acc and not acc.done():
            acc.set_result(True)
        elif msg.stage == "done" and done and not done.done():
            done.set_result(msg.payload)
        elif msg.stage == "error" and done and not done.done():
            done.set_exception(AgentFailed(msg.error or "unknown error"))

    async def call(self, ctx: Context, dest: str, kind: str, payload: str, *, accept_s: float, done_s: float) -> str:
        rid = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        self._accepted[rid], self._done[rid] = loop.create_future(), loop.create_future()
        try:
            await ctx.send(dest, AgentRequest(request_id=rid, kind=kind, payload=payload))
            try:
                await asyncio.wait_for(asyncio.shield(self._accepted[rid]), accept_s)
            except asyncio.TimeoutError:
                raise AgentUnreachable(f"{kind}: no answer from {dest[:16]}... in {accept_s:g}s") from None
            try:
                return await asyncio.wait_for(self._done[rid], done_s)
            except asyncio.TimeoutError:
                raise AgentFailed(f"{kind}: not finished in {done_s:g}s") from None
        finally:
            self._accepted.pop(rid, None)
            self._done.pop(rid, None)


def serve(protocol: Protocol, handler):
    """Register handler(ctx, kind, payload) -> JSON string on protocol. The reply goes out in two parts."""
    @protocol.on_message(AgentRequest, replies={AgentReply})
    async def on_request(ctx: Context, sender: str, msg: AgentRequest):
        ctx.logger.info(f"{msg.kind} request {msg.request_id[:8]} from {sender[:14]}...")
        await ctx.send(sender, AgentReply(request_id=msg.request_id, stage="accepted"))
        try:
            out = await handler(ctx, msg.kind, msg.payload)
            reply = AgentReply(request_id=msg.request_id, stage="done", payload=out)
            ctx.logger.info(f"{msg.kind} request {msg.request_id[:8]} done")
        except Exception as e:  # the caller falls back; say why in the log
            ctx.logger.error(f"{msg.kind} failed: {e!r}")
            reply = AgentReply(request_id=msg.request_id, stage="error", error=str(e)[:300])
        await ctx.send(sender, reply)
