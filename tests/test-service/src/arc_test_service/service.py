from __future__ import annotations

import asyncio
import os

from arc_service.service import Service


class TestService(Service):
    def __init__(self) -> None:
        super().__init__(
            name="test",
            version="0.1.0",
            description="Service used to test ARC Pulse lifecycle and failure handling",
        )

        self._stop_event = asyncio.Event()
        self._ready = False
        self._ticks = 0

        self._startup_failure = self._env_bool("ARC_TEST_STARTUP_FAILURE")
        self._crash_after = self._env_int("ARC_TEST_CRASH_AFTER")
        self._unhealthy_after = self._env_int("ARC_TEST_UNHEALTHY_AFTER")
        self._exit_after = self._env_int("ARC_TEST_EXIT_AFTER")

        self._unhealthy = False

    @staticmethod
    def _env_bool(key: str) -> bool:
        return os.getenv(
            key,
            "0",
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _env_int(key: str) -> int | None:
        value = os.getenv(key)

        if value is None or value.strip() == "":
            return None

        return int(value)

    async def run(self) -> None:
        assert self.ctx is not None

        self.ctx.logger.info("Test service starting")

        # ---------------------------------------------------------
        # Failure mode: startup failure
        # ---------------------------------------------------------
        if self._startup_failure:
            self.ctx.logger.error("Intentional startup failure")
            raise RuntimeError("Intentional ARC test startup failure")

        # Simulate initialization.
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

                # -------------------------------------------------
                # Failure mode: unhealthy
                # -------------------------------------------------
                if (
                    self._unhealthy_after is not None
                    and self._ticks >= self._unhealthy_after
                    and not self._unhealthy
                ):
                    self._unhealthy = True

                    self.ctx.logger.warning("Entering intentional unhealthy state")

                # -------------------------------------------------
                # Failure mode: normal exit
                # -------------------------------------------------
                if self._exit_after is not None and self._ticks >= self._exit_after:
                    self.ctx.logger.warning("Intentionally exiting with code 0")
                    return

                # -------------------------------------------------
                # Failure mode: crash
                # -------------------------------------------------
                if self._crash_after is not None and self._ticks >= self._crash_after:
                    self.ctx.logger.error("Intentionally crashing service")
                    raise RuntimeError("Intentional ARC test crash")

                await asyncio.sleep(5)

        except asyncio.CancelledError:
            self.ctx.logger.info("Test service task cancelled")
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
        if self._unhealthy:
            return False, "intentional test unhealthy state"

        if self._stop_event.is_set():
            return False, "service is stopping"

        return True, None

    async def stop(self) -> None:
        assert self.ctx is not None

        self.ctx.logger.info("Stopping test service")

        self._stop_event.set()
