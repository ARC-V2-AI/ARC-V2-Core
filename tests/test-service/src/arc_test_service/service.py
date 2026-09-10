from __future__ import annotations

import asyncio

from arc_service.service import Service


class TestService(Service):
    def __init__(self) -> None:
        super().__init__(
            name="test",
            version="0.1.0",
            description="Minimal ARC test service",
        )

        self._stop_event = asyncio.Event()
        self._ready = False
        self._ticks = 0

    async def run(self) -> None:
        assert self.ctx is not None

        self.ctx.logger.info("Test service starting")

        await asyncio.sleep(2)

        self._ready = True

        self.ctx.logger.info("Test service ready")

        try:
            while not self._stop_event.is_set():
                self._ticks += 1

                self.ctx.logger.info(
                    "Tick %d",
                    self._ticks,
                )

                await asyncio.sleep(5)

        except asyncio.CancelledError:
            raise

        finally:
            self.ctx.logger.info("Test service stopped")

    async def ready(
        self,
    ) -> tuple[bool, str | None]:
        if self._ready:
            return True, None

        return False, "still starting"

    async def healthy(
        self,
    ) -> tuple[bool, str | None]:
        if self._stop_event.is_set():
            return False, "service is stopping"

        return True, None

    async def stop(self) -> None:
        assert self.ctx is not None

        self.ctx.logger.info("Stopping test service")

        self._stop_event.set()
