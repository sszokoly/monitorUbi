"""Polling orchestration for typed Mobility API data."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, TypeVar
from uuid import UUID

from loguru import logger

from monitorUbi.schemas import Device, DeviceClient, DeviceSummary, Workspace


DEFAULT_POLL_INTERVAL_SECONDS = 120.0
DEFAULT_REQUESTS_PER_MINUTE = 120
DEFAULT_MAX_CONCURRENT_REQUESTS = 4

T = TypeVar("T")


class MobilityApi(Protocol):
    """Typed API operations required by the monitoring service."""

    async def list_workspaces(self) -> list[Workspace]: ...

    async def list_devices(self, workspace_id: UUID) -> list[DeviceSummary]: ...

    async def get_device(self, workspace_id: UUID, device_id: UUID) -> Device: ...

    async def list_device_clients(
        self, workspace_id: UUID, device_id: UUID
    ) -> list[DeviceClient]: ...


@dataclass(frozen=True)
class DeviceSnapshot:
    """Detailed device data together with the IDs required for persistence."""

    workspace_id: UUID
    device: Device
    clients: tuple[DeviceClient, ...]
    device_observed_at: datetime
    clients_observed_at: datetime


class SnapshotStore(Protocol):
    """Persistence operation required by the monitoring service."""

    async def save_snapshot(
        self,
        workspaces: Sequence[Workspace],
        devices: Sequence[DeviceSnapshot],
        workspaces_observed_at: datetime,
    ) -> None: ...


@dataclass(frozen=True)
class SyncSummary:
    """Concise result of one completed monitoring cycle."""

    workspace_count: int
    device_count: int
    client_count: int
    sampled_at: datetime


RefreshCallback = Callable[[SyncSummary], Awaitable[None] | None]


class _RequestPacer:
    """Space API request starts to remain below the documented rate limit."""

    def __init__(self, requests_per_minute: int) -> None:
        if requests_per_minute < 1:
            raise ValueError("requests_per_minute must be at least 1")
        self._interval = 60 / requests_per_minute
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def wait_for_turn(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            scheduled_at = max(now, self._next_request_at)
            self._next_request_at = scheduled_at + self._interval
        await asyncio.sleep(max(0.0, scheduled_at - loop.time()))


class MonitorService:
    """Collect API snapshots, persist them, and notify the caller after each poll."""

    def __init__(
        self,
        api: MobilityApi,
        store: SnapshotStore,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
        max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
        on_refresh: RefreshCallback | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than 0")
        if max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be at least 1")

        self._api = api
        self._store = store
        self._poll_interval_seconds = poll_interval_seconds
        self._on_refresh = on_refresh
        self._request_pacer = _RequestPacer(requests_per_minute)
        self._request_semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._poll_task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        """Whether a background polling task is active."""
        return self._poll_task is not None and not self._poll_task.done()

    def start(self) -> None:
        """Start polling from the current event loop if it is not already active."""
        if self.is_running:
            return
        self._poll_task = asyncio.create_task(
            self._run_loop(),
            name="monitorubi-polling",
        )
        logger.info("Monitor service started")

    async def stop(self) -> None:
        """Cancel the active poll cycle or wait period and wait for shutdown."""
        if self._poll_task is None:
            return

        poll_task = self._poll_task
        self._poll_task = None
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
        logger.info("Monitor service stopped")

    async def sync_once(self) -> SyncSummary:
        """Fetch one complete typed snapshot and hand it to the persistence layer."""
        sampled_at = datetime.now(timezone.utc)
        workspaces = await self._call_api(self._api.list_workspaces)
        workspaces_observed_at = datetime.now(timezone.utc)
        workspace_snapshots = await asyncio.gather(
            *(self._collect_workspace_snapshots(workspace) for workspace in workspaces)
        )
        devices = [
            device_snapshot
            for snapshots in workspace_snapshots
            for device_snapshot in snapshots
        ]

        await self._store.save_snapshot(workspaces, devices, workspaces_observed_at)
        return SyncSummary(
            workspace_count=len(workspaces),
            device_count=len(devices),
            client_count=sum(len(device.clients) for device in devices),
            sampled_at=sampled_at,
        )

    async def _collect_workspace_snapshots(
        self, workspace: Workspace
    ) -> list[DeviceSnapshot]:
        summaries = await self._call_api(
            lambda: self._api.list_devices(workspace.workspace_id)
        )
        return list(
            await asyncio.gather(
                *(
                    self._collect_device_snapshot(workspace.workspace_id, summary)
                    for summary in summaries
                )
            )
        )

    async def _collect_device_snapshot(
        self, workspace_id: UUID, summary: DeviceSummary
    ) -> DeviceSnapshot:
        (device, device_observed_at), (clients, clients_observed_at) = (
            await asyncio.gather(
                self._observe_api(
                    lambda: self._api.get_device(workspace_id, summary.id)
                ),
                self._observe_api(
                    lambda: self._api.list_device_clients(workspace_id, summary.id)
                ),
            )
        )
        return DeviceSnapshot(
            workspace_id=workspace_id,
            device=device,
            clients=tuple(clients),
            device_observed_at=device_observed_at,
            clients_observed_at=clients_observed_at,
        )

    async def _call_api(self, operation: Callable[[], Awaitable[T]]) -> T:
        await self._request_pacer.wait_for_turn()
        async with self._request_semaphore:
            return await operation()

    async def _observe_api(
        self, operation: Callable[[], Awaitable[T]]
    ) -> tuple[T, datetime]:
        value = await self._call_api(operation)
        return value, datetime.now(timezone.utc)

    async def _run_loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_poll_at = loop.time()

        while True:
            try:
                summary = await self.sync_once()
                logger.info(
                    "Sync completed: {workspaces} workspaces, {devices} devices, "
                    "{clients} clients",
                    workspaces=summary.workspace_count,
                    devices=summary.device_count,
                    clients=summary.client_count,
                )
                await self._notify_refresh(summary)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Monitor sync failed")

            next_poll_at += self._poll_interval_seconds
            now = loop.time()
            if now > next_poll_at:
                skipped_polls = int(
                    (now - next_poll_at) // self._poll_interval_seconds
                ) + 1
                next_poll_at += skipped_polls * self._poll_interval_seconds
                logger.warning(
                    "Poll exceeded its interval; skipped {skipped_polls} scheduled starts",
                    skipped_polls=skipped_polls,
                )

            await asyncio.sleep(max(0.0, next_poll_at - loop.time()))

    async def _notify_refresh(self, summary: SyncSummary) -> None:
        if self._on_refresh is None:
            return
        result = self._on_refresh(summary)
        if inspect.isawaitable(result):
            await result


if __name__ == "__main__":
    from monitorUbi.client import MobilityApiClient
    from monitorUbi.logging_setup import configure_logging

    class ConsoleSnapshotStore:
        """Example store that reports the typed snapshot instead of persisting it."""

        async def save_snapshot(
            self,
            workspaces: Sequence[Workspace],
            devices: Sequence[DeviceSnapshot],
            workspaces_observed_at: datetime,
        ) -> None:
            client_count = sum(len(device.clients) for device in devices)
            print(
                f"Snapshot at {workspaces_observed_at.isoformat()}: "
                f"{len(workspaces)} workspaces, {len(devices)} devices, "
                f"{client_count} clients"
            )

    async def main() -> None:
        configure_logging("headless")
        async with MobilityApiClient() as api:
            service = MonitorService(api, ConsoleSnapshotStore())
            summary = await service.sync_once()
        print(f"Sync summary: {summary}")

    asyncio.run(main())
