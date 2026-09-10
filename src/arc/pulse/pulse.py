from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from arc_service.types import ProcessOutcome, ServiceStatus

from arc.forge.runtime import RuntimeBootstrap, VirtualEnvManager
from arc.foundation.constants import (
    MAX_UNHEALTHY_SERVICE_CHECKS,
    WAIT_ON_DEPENDENCIES,
)
from arc.foundation.service import ServiceState
from arc.pulse.configLoader import ConfigLoader
from arc.pulse.manager import ServiceManager
from arc.pulse.registry import ServiceRegistry

logger = logging.getLogger(__name__)

RESTART_ALWAYS = "always"
RESTART_ON_FAILURE = "on-failure"
RESTART_NEVER = "never"

HEALTH_ACTION_IGNORE = "ignore"
HEALTH_ACTION_RESTART = "restart"
HEALTH_ACTION_STOP = "stop"


class Pulse:
    def __init__(self, autofix: bool) -> None:
        self._autofix = autofix

        self._service_registry = ServiceRegistry()

        self._runtime = VirtualEnvManager()

        self._service_manager = ServiceManager(
            self._service_registry,
            runtime_python=self._runtime.python,
        )

        self._service_health_counter: defaultdict[
            int,
            int,
        ] = defaultdict(int)

    async def startup(
        self,
        wait_on_deps: bool = WAIT_ON_DEPENDENCIES,
    ) -> None:
        RuntimeBootstrap(self._runtime).ensure()

        tree = ConfigLoader(self._autofix).run()

        self._service_registry.register_tree(tree)

        await self._service_manager.start_all(wait_on_deps)

    async def supervise(
        self,
        poll_interval: float = 2.0,
    ) -> None:
        while True:
            for service in self._service_registry.iter_startup_order():
                if service.state not in (
                    ServiceState.RUNNING,
                    ServiceState.FAILED,
                ):
                    continue

                # First detect process exit.
                outcome = self._service_manager.check(service)

                if outcome is not None:
                    logger.info(
                        "Service '%s' exited: %s",
                        service.config.name,
                        outcome.value,
                    )

                    if service.pid is not None:
                        self._service_health_counter.pop(
                            service.pid,
                            None,
                        )

                    if self._should_restart(
                        service.config.restart,
                        outcome,
                    ):
                        await self._service_manager.restart(service)

                    continue

                process = service.process

                if process is None or service.pid is None:
                    continue

                status: ServiceStatus | None = await process.status()

                if status is None:
                    logger.warning(
                        "Could not determine health for service '%s'",
                        service.config.name,
                    )
                    continue

                pid = service.pid

                if status.healthy:
                    self._service_health_counter[pid] = 0
                    continue

                self._service_health_counter[pid] += 1

                checks = MAX_UNHEALTHY_SERVICE_CHECKS

                if self._service_health_counter[pid] < checks:
                    continue

                self._service_health_counter[pid] = 0

                logger.warning(
                    "Service '%s' reports unhealthy: %s",
                    service.config.name,
                    status.healthy_reason,
                )

                policy = service.config.health

                if policy == HEALTH_ACTION_RESTART:
                    await self._service_manager.restart(service)

                elif policy == HEALTH_ACTION_STOP:
                    await self._service_manager.stop(service)

            await asyncio.sleep(poll_interval)

    @staticmethod
    def _should_restart(
        policy: str,
        outcome: ProcessOutcome,
    ) -> bool:
        if policy == RESTART_ALWAYS:
            return True

        if policy == RESTART_ON_FAILURE:
            return outcome is ProcessOutcome.CRASHED

        return False

    async def shutdown(self) -> None:
        await self._service_manager.stop_all()
