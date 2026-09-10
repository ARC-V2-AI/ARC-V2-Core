from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from arc.foundation.constants import STRICT_ERRORS
from arc.foundation.service import ServiceInstance, ServiceState
from arc.foundation.service_process import (
    ProcessOutcome,
    ServiceProcess,
)
from arc.pulse.registry import ServiceRegistry

logger = logging.getLogger(__name__)


class ServiceManager:
    def __init__(
        self,
        registry: ServiceRegistry,
        runtime_python: Path,
    ) -> None:
        self._registry = registry
        self._runtime_python = runtime_python

    def _clear_process(
        self,
        service: ServiceInstance,
    ) -> None:
        if service.process is not None:
            service.process.close()

        service.process = None
        service.pid = None

    async def start_all(
        self,
        wait_on_deps: bool = True,
    ) -> None:
        for level in self._registry.iter_levels():
            results = await asyncio.gather(
                *(self.start(service) for service in level),
                return_exceptions=True,
            )

            for service, result in zip(level, results):
                if isinstance(result, Exception):
                    logger.exception(
                        "Failed to start service '%s': %s",
                        service.config.name,
                        result,
                    )

                    if STRICT_ERRORS:
                        raise result

            if wait_on_deps:
                results = await asyncio.gather(
                    *(self.wait_ready(service) for service in level),
                    return_exceptions=True,
                )

                for service, result in zip(level, results):
                    if isinstance(result, Exception):
                        logger.exception(
                            "Readiness check failed for '%s': %s",
                            service.config.name,
                            result,
                        )

                        if STRICT_ERRORS:
                            raise result

    async def start(
        self,
        service: ServiceInstance,
    ) -> None:
        service.state = ServiceState.STARTING

        try:
            process = ServiceProcess(
                name=service.config.name,
                module=service.config.module,
                runtime_python=str(self._runtime_python),
            )

            process.start()

            service.process = process
            service.pid = process.pid
            service.started_at = datetime.now()
            service.state = ServiceState.RUNNING

        except Exception as exc:
            service.state = ServiceState.FAILED
            service.last_error = str(exc)

            logger.exception(
                "Failed to start service '%s'",
                service.config.name,
            )

            if STRICT_ERRORS:
                raise

    async def wait_ready(
        self,
        service: ServiceInstance,
        timeout: float = 30.0,
        poll_interval: float = 0.2,
    ) -> None:
        process = service.process

        if process is None:
            raise RuntimeError(f"Service '{service.config.name}' has no process")

        deadline = asyncio.get_running_loop().time() + timeout

        while True:
            if not process.is_alive():
                result = process.poll_result()

                service.state = ServiceState.FAILED

                if result is not None:
                    service.last_error = result.traceback or result.error

                if STRICT_ERRORS:
                    raise RuntimeError(
                        f"Service '{service.config.name}' failed before becoming ready"
                    )

                return

            status = await process.status(
                timeout=0.5,
            )

            if status is not None and status.ready:
                service.state = ServiceState.READY
                return

            if asyncio.get_running_loop().time() >= deadline:
                message = (
                    f"Service '{service.config.name}' "
                    f"did not become ready within {timeout}s"
                )

                service.state = ServiceState.FAILED
                service.last_error = message

                if STRICT_ERRORS:
                    raise TimeoutError(message)

                return

            await asyncio.sleep(poll_interval)

    async def stop(
        self,
        service: ServiceInstance,
        timeout: float = 10.0,
    ) -> None:
        process = service.process

        if process is None:
            return

        if not process.is_alive():
            self._clear_process(service)
            service.state = ServiceState.STOPPED
            return

        service.state = ServiceState.STOPPING

        await asyncio.to_thread(
            process.terminate,
            timeout,
        )

        self._clear_process(service)
        service.state = ServiceState.STOPPED

    async def restart(
        self,
        service: ServiceInstance,
    ) -> None:
        await self.stop(service)

        service.restart_count += 1

        await self.start(service)

    def check(
        self,
        service: ServiceInstance,
    ) -> ProcessOutcome | None:
        process = service.process

        if process is None:
            return None

        result = process.poll_result()

        if result is None:
            return None

        if result.outcome is ProcessOutcome.CRASHED:
            service.state = ServiceState.FAILED

            service.last_error = result.traceback or result.error

        return result.outcome

    @staticmethod
    def is_running(
        service: ServiceInstance,
    ) -> bool:
        return service.process is not None and service.process.is_alive()

    async def stop_all(self) -> None:
        for level in reversed(list(self._registry.iter_levels())):
            results = await asyncio.gather(
                *(self.stop(service) for service in level),
                return_exceptions=True,
            )

            for service, result in zip(level, results):
                if isinstance(result, Exception):
                    logger.exception(
                        "Failed to stop service '%s': %s",
                        service.config.name,
                        result,
                    )

                    if STRICT_ERRORS:
                        raise result
