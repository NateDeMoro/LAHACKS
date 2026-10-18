"""Bluetooth link to the heart-rate strap: scan, connect, stream frames, reconnect on loss."""
import asyncio
import logging
import time
from collections.abc import Callable

from backend.config import ReceiverConfig

log = logging.getLogger(__name__)

# tstamp_ns, avg_hr, rr_ms, sensor_contact (None when the strap has no contact flag)
FrameCallback = Callable[[int, int, list[int], bool | None], None]


async def _find_device(prefix, timeout):
    from bleak import BleakScanner

    return await BleakScanner.find_device_by_filter(
        lambda dev, adv: (dev.name or "").startswith(prefix), timeout=timeout
    )


def _make_client(device, disconnected_callback):
    from bleak import BleakClient

    return BleakClient(device, disconnected_callback=disconnected_callback)


def _make_heartrate(client, callback):
    from bleakheart import HeartRate

    return HeartRate(client, callback=callback, unpack=False)


class StrapLink:
    def __init__(self, cfg: ReceiverConfig, on_frame: FrameCallback, *, find_device=None,
                 client_factory=None, heartrate_factory=None, sleep=asyncio.sleep, clock=time.monotonic):
        self.cfg = cfg
        self.on_frame = on_frame
        self._find_device = find_device or _find_device
        self._client_factory = client_factory or _make_client
        self._heartrate_factory = heartrate_factory or _make_heartrate
        self._sleep = sleep
        self._clock = clock
        self.connected = False
        self._got_frame = False
        self._last_frame = 0.0

    async def run(self) -> None:
        first, longest = self.cfg.reconnect_backoff_s
        backoff = first
        while True:
            self._got_frame = False
            try:
                await self._session()
            except Exception as e:
                log.warning("strap link failed: %r", e)
            if self._got_frame:
                backoff = first
            await self._sleep(backoff)
            backoff = min(backoff * 2, longest)

    async def _session(self) -> None:
        device = await self._find_device(self.cfg.strap_name_prefix, self.cfg.scan_timeout_s)
        if device is None:
            log.info("no strap named %r found", self.cfg.strap_name_prefix)
            return

        loop = asyncio.get_running_loop()
        down = asyncio.Event()
        # bleak may call this from another thread
        client = self._client_factory(device, lambda _client: loop.call_soon_threadsafe(down.set))
        hr = None
        notifying = False
        self._last_frame = self._clock()

        def on_hr(frame):
            _, tstamp_ns, (avg_hr, rr_ms), _ = frame
            contact = hr.good_contact.is_set() if hr.contact_detection else None
            self._got_frame = True
            self._last_frame = self._clock()
            self.on_frame(tstamp_ns, avg_hr, rr_ms, contact)

        try:
            await client.connect()
            hr = self._heartrate_factory(client, on_hr)
            await hr.start_notify()
            notifying = True
            self.connected = True
            log.info("strap connected", extra={"wearable_id": self.cfg.wearable_id})
            await self._wait_until_down(down)
        finally:
            self.connected = False
            await self._teardown(client, hr if notifying else None)

    async def _wait_until_down(self, down: asyncio.Event) -> None:
        while True:
            remaining = self.cfg.stall_timeout_s - (self._clock() - self._last_frame)
            if remaining <= 0:
                log.warning("no frames for %.0fs, reconnecting", self.cfg.stall_timeout_s)
                return
            try:
                await asyncio.wait_for(down.wait(), remaining)
                log.warning("strap disconnected")
                return
            except TimeoutError:
                pass

    async def _teardown(self, client, hr) -> None:
        if hr is not None:
            try:
                await hr.stop_notify()
            except Exception as e:
                log.debug("stop_notify failed: %r", e)
        try:
            await client.disconnect()
        except Exception as e:
            log.debug("disconnect failed: %r", e)
