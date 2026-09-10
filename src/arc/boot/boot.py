import asyncio
import logging

from arc.foundation.constants import ENV_LOADED, make_default_env
from arc.foundation.logger import setup_logging
from arc.pulse.pulse import Pulse


async def main(autofix: bool = False) -> None:
    _ = setup_logging()
    logger = logging.getLogger("boot")

    if not ENV_LOADED:
        logger.warning("ARC '.env' not found. Using default configuration.")
        if autofix:
            _path = make_default_env()
            logger.info(f"Wrote default configuration to: {_path}. Due to autofix.")

    pulse = Pulse(autofix)

    try:
        await pulse.startup()
        logger.info("Boot startup completed!")
        await pulse.supervise()

    except asyncio.CancelledError:
        logger.info("Shutdown requested")

    finally:
        await pulse.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
