"""SQLite migrations and typed snapshot persistence for monitorUbi."""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Sequence

import aiosqlite

from monitorUbi.schemas import DeviceClient, Workspace
from monitorUbi.service import DeviceSnapshot


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
DEFAULT_DATABASE_PATH = Path(__file__).with_name("monitorUbi.db")


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
            raise


@asynccontextmanager
async def database_connection(
    database_path: str | Path,
) -> AsyncIterator[aiosqlite.Connection]:
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

    async def save_snapshot(
        self,
        workspaces: Sequence[Workspace],
        devices: Sequence[DeviceSnapshot],
        sampled_at: datetime,
    ) -> None:
        """Write one complete poll in a transaction after API collection completes."""
        if sampled_at.tzinfo is None:
            raise ValueError("sampled_at must be timezone-aware")
        sampled_at_text = sampled_at.astimezone(timezone.utc).isoformat()

        async with database_connection(self._database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                await self._upsert_workspaces(connection, workspaces, sampled_at_text)
                await self._upsert_devices(connection, devices, sampled_at_text)
                await self._upsert_clients(connection, devices, sampled_at_text)
                await self._insert_device_samples(connection, devices, sampled_at_text)
                await self._insert_client_samples(connection, devices, sampled_at_text)
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise

    async def _upsert_workspaces(
        self,
        connection: aiosqlite.Connection,
        workspaces: Sequence[Workspace],
        sampled_at: str,
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
                    sampled_at,
                )
                for workspace in workspaces
            ],
        )

    async def _upsert_devices(
        self,
        connection: aiosqlite.Connection,
        snapshots: Sequence[DeviceSnapshot],
        sampled_at: str,
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
            [self._device_row(snapshot, sampled_at) for snapshot in snapshots],
        )

    async def _upsert_clients(
        self,
        connection: aiosqlite.Connection,
        snapshots: Sequence[DeviceSnapshot],
        sampled_at: str,
    ) -> None:
        rows = [
            self._client_row(snapshot.device.id, client, sampled_at)
            for snapshot in snapshots
            for client in snapshot.clients
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
        sampled_at: str,
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
                    sampled_at,
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
        sampled_at: str,
    ) -> None:
        rows = [
            (
                sampled_at,
                str(snapshot.device.id),
                client.mac,
                client.connection_status,
                _string_or_none(client.ip_address),
                int(client.is_blocked),
                client.wifi_experience,
            )
            for snapshot in snapshots
            for client in snapshot.clients
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
    def _device_row(snapshot: DeviceSnapshot, sampled_at: str) -> tuple:
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
            sampled_at,
        )

    @staticmethod
    def _client_row(
        device_id: object, client: DeviceClient, sampled_at: str
    ) -> tuple:
        return (
            str(device_id),
            client.mac,
            client.name,
            client.type,
            client.connection_status,
            _string_or_none(client.ip_address),
            int(client.is_blocked),
            client.wifi_experience,
            sampled_at,
        )


def _json_array(values: Sequence[str]) -> str:
    """Serialize list-valued API fields for SQLite storage."""
    return json.dumps(values, separators=(",", ":"))


def _string_or_none(value: object | None) -> str | None:
    return str(value) if value is not None else None
