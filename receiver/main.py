"""Strap receiver entry point. Run: uv run --env-file .env python -m receiver.main"""
import asyncio
import logging
import time

from backend.config import CONFIG
from receiver.frames import FrameProcessor
from receiver.sender import IngestSender
from receiver.strap import StrapLink


async def run() -> None:
    cfg = CONFIG.receiver
    sender = IngestSender(cfg)
    frames = FrameProcessor(cfg)
    strap = StrapLink(cfg, lambda *frame: sender.send(frames.on_frame(*frame)))

    async def report_no_strap() -> None:
        # Frames carry the heartbeat while the strap is up; this keeps contact=false flowing while it's down.
        while True:
            await asyncio.sleep(1)
            if not strap.connected:
                sender.send(frames.no_strap(time.time_ns()))

    async with asyncio.TaskGroup() as tg:
        tg.create_task(sender.run())
        tg.create_task(strap.run())
        tg.create_task(report_no_strap())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
