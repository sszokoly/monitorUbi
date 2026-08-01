"""SQLite migrations and typed snapshot persistence for monitorUbi."""

import json
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Sequence

import aiosqlite
from loguru import logger

from monitorUbi.schemas import DeviceClient, Workspace
from monitorUbi.service import DeviceSnapshot


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
DEFAULT_DATABASE_PATH = Path(__file__).with_name("monitorUbi.db")

def database_size(database_path: str | Path = DEFAULT_DATABASE_PATH) -> str:
    """Return the main SQLite file and WAL sidecars as a display-ready size."""
    path = Path(database_path)
    size_bytes = sum(
        candidate.stat().st_size
        for candidate in (
            path,
            Path(f"{path}-wal"),
            Path(f"{path}-shm"),
        )
        if candidate.exists()
    )

    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:5.1f} GB"
    return f"{size_bytes / 1024**2:5.1f} MB"

async def open_database(database_path: str | Path) -> aiosqlite.Connection:
    """Open a configured SQLite connection and apply pending migrations."""
    connection = await aiosqlite.connect(database_path)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA foreign_keys = ON")
    await connection.execute("PRAGMA journal_mode = WAL")
    await apply_migrations(connection)
    return connection


async def apply_migrations(connection: aiosqlite.Connection) -> None:
    """Apply each numbered SQL migration exactly once."""
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await connection.commit()

    async with connection.execute("SELECT version FROM schema_migrations") as cursor:
        applied_versions = {row["version"] for row in await cursor.fetchall()}

    for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = migration_path.name
        if version in applied_versions:
            continue

        migration_sql = migration_path.read_text(encoding="utf-8")
        escaped_version = version.replace("'", "''")
        try:
            await connection.executescript(
                "BEGIN IMMEDIATE;\n"
                f"{migration_sql}\n"
                "INSERT INTO schema_migrations (version) "
                f"VALUES ('{escaped_version}');\n"
                "COMMIT;"
            )
        except Exception:
            await connection.rollback()
            logger.opt(exception=True).error(
                "Database migration {version} failed",
                version=version,
            )
            raise
        logger.info("Applied database migration {version}", version=version)


@asynccontextmanager
async def database_connection(
    database_path: str | Path,
) ->  AsyncGenerator[aiosqlite.Connection, None]:
    """Yield an initialized database connection and close it afterwards."""
    connection = await open_database(database_path)
    try:
        yield connection
    finally:
        await connection.close()


class SqliteSnapshotStore:
    """Persist the latest typed API state and append historical samples."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self._database_path = Path(database_path)
        self._workspace_count = 0
        self._device_count = 0
        self._online_client_count = 0

    @property
    def workspace_count(self) -> int:
        """Return the cached count of current workspaces."""
        return self._workspace_count

    @property
    def device_count(self) -> int:
        """Return the cached count of current devices."""
        return self._device_count

    @property
    def online_client_count(self) -> int:
        """Return the cached count of current online clients."""
        return self._online_client_count

    async def refresh_current_counts(self) -> None:
        """Load current workspace, device, and online-client counts from SQLite."""
        async with database_connection(self._database_path) as connection:
            counts = await self._query_current_counts(connection)
        self._set_current_counts(*counts)

    async def save_snapshot(
        self,
        workspaces: Sequence[Workspace],
        devices: Sequence[DeviceSnapshot],
        workspaces_observed_at: datetime,
        online_clients_only: bool = True,
    ) -> None:
        """Write one complete poll in a transaction after API collection completes."""
        workspaces_observed_at_text = _timestamp_text(workspaces_observed_at)
        client_count = sum(
            1
            for snapshot in devices
            for client in snapshot.clients
            if _should_store_client(client, online_clients_only)
        )
        started_at = perf_counter()
        logger.debug(
            "Persisting snapshot: {workspaces} workspaces, {devices} devices, "
            "{clients} clients",
            workspaces=len(workspaces),
            devices=len(devices),
            clients=client_count,
        )

        async with database_connection(self._database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                await self._upsert_workspaces(
                    connection, workspaces, workspaces_observed_at_text
                )
                await self._upsert_devices(connection, devices)
                await self._upsert_clients(connection, devices, online_clients_only)
                await self._insert_device_samples(connection, devices)
                await self._insert_client_samples(
                    connection, devices, online_clients_only
                )
                counts = await self._query_current_counts(connection)
                await connection.commit()
                self._set_current_counts(*counts)
                logger.debug(
                    "Snapshot persisted in {elapsed_seconds:.3f}s",
                    elapsed_seconds=perf_counter() - started_at,
                )
            except Exception:
                await connection.rollback()
                logger.opt(exception=True).debug("Snapshot transaction rolled back")
                raise

    async def prune_device_samples(self, retention_days: int) -> int:
        """Delete device samples older than the requested retention period."""
        return await self._prune_samples("device_samples", retention_days)

    async def prune_client_samples(self, retention_days: int) -> int:
        """Delete client samples older than the requested retention period."""
        return await self._prune_samples("client_samples", retention_days)

    async def get_device_dashboard_rows(self) -> list[dict[str, object]]:
        """Return the joined device values required by the dashboard view model."""
        async with database_connection(self._database_path) as connection:
            async with connection.execute(
                """
                SELECT
                    devices.name,
                    workspaces.workspace_name,
                    devices.state,
                    devices.wan_ip,
                    devices.wan_source,
                    devices.lte_signal_level,
                    devices.cellular_data_usage_bytes,
                    devices.client_count,
                    devices.last_seen_at
                FROM devices
                JOIN workspaces
                    ON workspaces.workspace_id = devices.workspace_id
                ORDER BY devices.name COLLATE NOCASE
                """
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def _query_current_counts(
        self, connection: aiosqlite.Connection
    ) -> tuple[int, int, int]:
        async with connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM workspaces),
                (SELECT COUNT(*) FROM devices),
                (
                    SELECT COUNT(*)
                    FROM clients
                    WHERE connection_status = 'ONLINE'
                )
            """
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]), int(row[1]), int(row[2])

    def _set_current_counts(
        self, workspace_count: int, device_count: int, online_client_count: int
    ) -> None:
        self._workspace_count = workspace_count
        self._device_count = device_count
        self._online_client_count = online_client_count

    async def _prune_samples(self, table_name: str, retention_days: int) -> int:
        if retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        if table_name not in {"device_samples", "client_samples"}:
            raise ValueError(f"Unsupported sample table: {table_name}")

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        async with database_connection(self._database_path) as connection:
            cursor = await connection.execute(
                f"DELETE FROM {table_name} WHERE sampled_at < ?",
                (_timestamp_text(cutoff),),
            )
            await connection.commit()

        deleted_rows = cursor.rowcount
        logger.debug(
            "Pruned {deleted_rows} rows from {table_name} older than {retention_days} days",
            deleted_rows=deleted_rows,
            table_name=table_name,
            retention_days=retention_days,
        )
        return deleted_rows

    async def _upsert_workspaces(
        self,
        connection: aiosqlite.Connection,
        workspaces: Sequence[Workspace],
        observed_at: str,
    ) -> None:
        if not workspaces:
            return

        await connection.executemany(
            """
            INSERT INTO workspaces (
                workspace_id, workspace_name, is_owner, status, last_seen_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id) DO UPDATE SET
                workspace_name = excluded.workspace_name,
                is_owner = excluded.is_owner,
                status = excluded.status,
                last_seen_at = excluded.last_seen_at
            """,
            [
                (
                    str(workspace.workspace_id),
                    workspace.workspace_name,
                    int(workspace.is_owner),
                    workspace.status,
                    observed_at,
                )
                for workspace in workspaces
            ],
        )

    async def _upsert_devices(
        self,
        connection: aiosqlite.Connection,
        snapshots: Sequence[DeviceSnapshot],
    ) -> None:
        if not snapshots:
            return

        await connection.executemany(
            """
            INSERT INTO devices (
                id, workspace_id, name, model, state, firmware_version, mac_address,
                wan_source, wan_ip, enabled_wans, isp, lte_signal_level,
                cellular_data_usage_bytes, cellular_data_limit_bytes, memory_usage_percent,
                uptime_seconds, client_count, host_address, poe_passthrough, device_mode,
                wifi_enabled, wifi_ssid, tx_power_level, vpn_profile_name, vpn_status,
                firewall_rule_names, routing_rule_names, ddns_profile_names,
                subscription_plan, subscription_status, latitude, longitude,
                location_last_updated, last_seen_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(id) DO UPDATE SET
                workspace_id = excluded.workspace_id,
                name = excluded.name,
                model = excluded.model,
                state = excluded.state,
                firmware_version = excluded.firmware_version,
                mac_address = excluded.mac_address,
                wan_source = excluded.wan_source,
                wan_ip = excluded.wan_ip,
                enabled_wans = excluded.enabled_wans,
                isp = excluded.isp,
                lte_signal_level = excluded.lte_signal_level,
                cellular_data_usage_bytes = excluded.cellular_data_usage_bytes,
                cellular_data_limit_bytes = excluded.cellular_data_limit_bytes,
                memory_usage_percent = excluded.memory_usage_percent,
                uptime_seconds = excluded.uptime_seconds,
                client_count = excluded.client_count,
                host_address = excluded.host_address,
                poe_passthrough = excluded.poe_passthrough,
                device_mode = excluded.device_mode,
                wifi_enabled = excluded.wifi_enabled,
                wifi_ssid = excluded.wifi_ssid,
                tx_power_level = excluded.tx_power_level,
                vpn_profile_name = excluded.vpn_profile_name,
                vpn_status = excluded.vpn_status,
                firewall_rule_names = excluded.firewall_rule_names,
                routing_rule_names = excluded.routing_rule_names,
                ddns_profile_names = excluded.ddns_profile_names,
                subscription_plan = excluded.subscription_plan,
                subscription_status = excluded.subscription_status,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                location_last_updated = excluded.location_last_updated,
                last_seen_at = excluded.last_seen_at
            """,
            [self._device_row(snapshot) for snapshot in snapshots],
        )

    async def _upsert_clients(
        self,
        connection: aiosqlite.Connection,
        snapshots: Sequence[DeviceSnapshot],
        online_clients_only: bool,
    ) -> None:
        rows = [
            self._client_row(snapshot, client)
            for snapshot in snapshots
            for client in snapshot.clients
            if _should_store_client(client, online_clients_only)
        ]
        if not rows:
            return

        await connection.executemany(
            """
            INSERT INTO clients (
                device_id, mac, name, type, connection_status, ip_address,
                is_blocked, wifi_experience, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, mac) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                connection_status = excluded.connection_status,
                ip_address = excluded.ip_address,
                is_blocked = excluded.is_blocked,
                wifi_experience = excluded.wifi_experience,
                last_seen_at = excluded.last_seen_at
            """,
            rows,
        )

    async def _insert_device_samples(
        self,
        connection: aiosqlite.Connection,
        snapshots: Sequence[DeviceSnapshot],
    ) -> None:
        if not snapshots:
            return

        await connection.executemany(
            """
            INSERT INTO device_samples (
                sampled_at, workspace_id, device_id, state, wan_source, wan_ip,
                lte_signal_level, cellular_data_usage_bytes, memory_usage_percent,
                uptime_seconds, client_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    _timestamp_text(snapshot.device_observed_at),
                    str(snapshot.workspace_id),
                    str(snapshot.device.id),
                    snapshot.device.state,
                    snapshot.device.wan_source,
                    _string_or_none(snapshot.device.wan_ip),
                    snapshot.device.lte_signal_level,
                    snapshot.device.cellular_data_usage_bytes,
                    snapshot.device.memory_usage_percent,
                    snapshot.device.uptime_seconds,
                    snapshot.device.client_count,
                )
                for snapshot in snapshots
            ],
        )

    async def _insert_client_samples(
        self,
        connection: aiosqlite.Connection,
        snapshots: Sequence[DeviceSnapshot],
        online_clients_only: bool,
    ) -> None:
        rows = [
            (
                _timestamp_text(snapshot.clients_observed_at),
                str(snapshot.device.id),
                client.mac,
                client.connection_status,
                _string_or_none(client.ip_address),
                int(client.is_blocked),
                client.wifi_experience,
            )
            for snapshot in snapshots
            for client in snapshot.clients
            if _should_store_client(client, online_clients_only)
        ]
        if not rows:
            return

        await connection.executemany(
            """
            INSERT INTO client_samples (
                sampled_at, device_id, mac, connection_status, ip_address,
                is_blocked, wifi_experience
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    @staticmethod
    def _device_row(snapshot: DeviceSnapshot) -> tuple:
        device = snapshot.device
        location = device.location
        return (
            str(device.id),
            str(snapshot.workspace_id),
            device.name,
            device.model,
            device.state,
            device.firmware_version,
            device.mac_address,
            device.wan_source,
            _string_or_none(device.wan_ip),
            _json_array(device.enabled_wans),
            device.isp,
            device.lte_signal_level,
            device.cellular_data_usage_bytes,
            device.cellular_data_limit_bytes,
            device.memory_usage_percent,
            device.uptime_seconds,
            device.client_count,
            str(device.host_address),
            int(device.poe_passthrough),
            device.device_mode,
            int(device.wifi_enabled),
            device.wifi_ssid,
            device.tx_power_level,
            device.vpn_profile_name,
            device.vpn_status,
            _json_array(device.firewall_rule_names),
            _json_array(device.routing_rule_names),
            _json_array(device.ddns_profile_names),
            device.subscription_plan,
            device.subscription_status,
            location.latitude if location else None,
            location.longitude if location else None,
            location.last_updated if location else None,
            _timestamp_text(snapshot.device_observed_at),
        )

    @staticmethod
    def _client_row(snapshot: DeviceSnapshot, client: DeviceClient) -> tuple:
        return (
            str(snapshot.device.id),
            client.mac,
            client.name,
            client.type,
            client.connection_status,
            _string_or_none(client.ip_address),
            int(client.is_blocked),
            client.wifi_experience,
            _timestamp_text(snapshot.clients_observed_at),
        )


def _json_array(values: Sequence[str]) -> str:
    """Serialize list-valued API fields for SQLite storage."""
    return json.dumps(values, separators=(",", ":"))


def _string_or_none(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _should_store_client(client: DeviceClient, online_clients_only: bool) -> bool:
    return not online_clients_only or client.connection_status == "ONLINE"


def _timestamp_text(value: datetime) -> str:
    """Normalize an observation timestamp for SQLite storage."""
    if value.tzinfo is None:
        raise ValueError("observation timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


if __name__ == "__main__":
    import asyncio
    from monitorUbi.client import MobilityApiClient
    from monitorUbi.logging_setup import configure_logging
    from monitorUbi.service import MonitorService

    async def main() -> None:
        configure_logging("headless")
        test_db_path = Path(__file__).with_name("test.db")
        async with MobilityApiClient() as api:
            service = MonitorService(api, SqliteSnapshotStore(test_db_path))
            summary = await service.sync_once()
        print(f"Sync summary: {summary}")

    asyncio.run(main())
