"""Request/reply matching: a fast "accepted" fails a dead peer quickly, and errors and stalls surface as such."""
import asyncio

import pytest

from agent.rpc import AgentFailed, AgentUnreachable, Caller
from agent.wire import AgentReply, AgentRequest


class Peer:
    """Fake ctx: answers each request with the given stages, in order, after a short delay."""

    def __init__(self, caller: Caller, stages: list[tuple[str, str, str | None]]):
        self.caller, self.stages, self.sent = caller, stages, []

    async def send(self, dest, msg):
        assert isinstance(msg, AgentRequest)
        self.sent.append((dest, msg))
        for stage, payload, error in self.stages:
            asyncio.get_running_loop().call_later(
                0.01, lambda s=stage, p=payload, e=error: asyncio.ensure_future(
                    self.caller._on_reply(None, "peer", AgentReply(request_id=msg.request_id, stage=s, payload=p, error=e))))


def call(stages, **kw):
    async def go():
        c = Caller()
        peer = Peer(c, stages)
        out = await c.call(peer, "agent1x", "adjust", "{}", accept_s=kw.get("accept_s", 0.3), done_s=kw.get("done_s", 0.3))
        return out, peer, c
    return asyncio.run(go())


def test_returns_the_done_payload_and_cleans_up():
    out, peer, c = call([("accepted", "", None), ("done", '{"ok":1}', None)])
    assert out == '{"ok":1}' and peer.sent[0][0] == "agent1x" and not c._accepted and not c._done


def test_no_accept_means_unreachable():
    with pytest.raises(AgentUnreachable):
        call([])


def test_error_stage_raises_failed_with_the_reason():
    with pytest.raises(AgentFailed, match="gate"):
        call([("accepted", "", None), ("error", "", "gate blew up")])


def test_accepted_but_never_done_raises_failed():
    with pytest.raises(AgentFailed, match="not finished"):
        call([("accepted", "", None)])
