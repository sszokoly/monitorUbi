"""Headless composition and lifecycle for monitorUbi."""

import asyncio

from loguru import logger

from monitorUbi.client import MobilityApiClient
from monitorUbi.db import SqliteSnapshotStore
from monitorUbi.logging_setup import configure_logging
from monitorUbi.service import MonitorService


async def run_daemon(service: MonitorService, stop_event: asyncio.Event) -> None:
    """Run an already-configured service until the caller requests shutdown."""
    service.start()
    logger.info("Monitor runner is active")

    try:
        await stop_event.wait()
    finally:
        await service.stop()
        logger.info("Monitor runner stopped")


async def main() -> None:
    """Compose production dependencies and run the headless monitor."""
    configure_logging("headless")

    store = SqliteSnapshotStore()
    stop_event = asyncio.Event()

    async with MobilityApiClient() as api:
        service = MonitorService(api, store)
        await run_daemon(service, stop_event)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
