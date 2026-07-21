"""SQLite setup and migration helpers for monitorUbi."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from datetime import datetime

import aiosqlite
from schemas import Workspace

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
DB_PATH = Path("monitorUbi.db")

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
async def database_connection(database_path: str | Path) -> AsyncIterator[aiosqlite.Connection]:
    """Yield an initialized database connection and close it afterwards."""
    connection = await open_database(database_path)
    try:
        yield connection
    finally:
        await connection.close()


async def upsert_workspaces(workspaces: list[Workspace]):
    async with database_connection(DB_PATH) as conn:
        now_iso = datetime.now().isoformat()
        
        payloads = [
            {**ws.model_dump(mode="json"), "last_seen_at": now_iso} 
            for ws in workspaces
        ]
        
        # 2. Use named placeholders (:key) to match dictionary keys
        query = """
            INSERT INTO workspaces (workspace_id, workspace_name, is_owner, status, last_seen_at)
            VALUES (:workspace_id, :workspace_name, :is_owner, :status, :last_seen_at)
            ON CONFLICT(workspace_id) DO UPDATE SET
                workspace_name = excluded.workspace_name,
                is_owner = excluded.is_owner,
                status = excluded.status,
                last_seen_at = excluded.last_seen_at;
        """
        
        # 3. Use executemany to run all upserts efficiently in a single batch
        await conn.executemany(query, payloads)
        await conn.commit()


async def upsert_device_metrics(connection: aiosqlite.Connection, payload: dict) -> None:
    """
    Parses a single device REST payload and performs an atomic relational upsert.
    Saves state to primary lookup tables and logs structural metric snapshots.
    """
    # Use an explicit transaction to ensure all tables succeed or fail together
    await connection.execute("BEGIN IMMEDIATE")
    try:
        now_iso = datetime.utcnow().isoformat()
        
        # 1. Upsert Workspace (Required first due to Foreign Key constraints)
        await connection.execute(
            """
            INSERT INTO workspaces (workspace_id, workspace_name, is_owner, status, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id) DO UPDATE SET
                workspace_name = excluded.workspace_name,
                is_owner = excluded.is_owner,
                status = excluded.status,
                last_seen_at = excluded.last_seen_at
            """,
            (
                payload["workspace_id"],
                payload.get("workspace_name", "Unknown"),
                int(payload.get("is_owner", False)),
                payload.get("workspace_status", "active"),
                now_iso
            )
        )

        # 2. Upsert Device Entry
        await connection.execute(
            """
            INSERT INTO devices (
                id, workspace_id, name, model, state, firmware_version, mac_address,
                wan_source, wan_ip, enabled_wans, isp, lte_signal_level,
                cellular_data_usage_bytes, cellular_data_limit_bytes, memory_usage_percent,
                uptime_seconds, client_count, host_address, poe_passthrough, device_mode,
                wifi_enabled, wifi_ssid, tx_power_level, vpn_profile_name, vpn_status,
                firewall_rule_names, routing_rule_names, ddns_profile_names, subscription_plan,
                subscription_status, latitude, longitude, location_last_updated, last_seen_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(id) DO UPDATE SET
                state = excluded.state,
                firmware_version = excluded.firmware_version,
                wan_source = excluded.wan_source,
                wan_ip = excluded.wan_ip,
                isp = excluded.isp,
                lte_signal_level = excluded.lte_signal_level,
                cellular_data_usage_bytes = excluded.cellular_data_usage_bytes,
                memory_usage_percent = excluded.memory_usage_percent,
                uptime_seconds = excluded.uptime_seconds,
                client_count = excluded.client_count,
                last_seen_at = excluded.last_seen_at
            """,
            (
                payload["device_id"], payload["workspace_id"], payload["name"], payload["model"],
                payload["state"], payload["firmware_version"], payload.get("mac_address", ""),
                payload.get("wan_source"), payload.get("wan_ip"), payload.get("enabled_wans"),
                payload.get("isp"), payload.get("lte_signal_level"), payload.get("cellular_data_usage_bytes"),
                payload.get("cellular_data_limit_bytes"), payload.get("memory_usage_percent"),
                payload.get("uptime_seconds"), len(payload.get("clients", [])), payload.get("host_address"),
                int(payload.get("poe_passthrough", False)), payload.get("device_mode"),
                int(payload.get("wifi_enabled", False)), payload.get("wifi_ssid"), payload.get("tx_power_level"),
                payload.get("vpn_profile_name"), payload.get("vpn_status"), payload.get("firewall_rule_names"),
                payload.get("routing_rule_names"), payload.get("ddns_profile_names"), payload.get("subscription_plan"),
                payload.get("subscription_status"), payload.get("latitude"), payload.get("longitude"),
                payload.get("location_last_updated"), now_iso
            )
        )

        # 3. Append historical telemetry snapshot to device_samples
        await connection.execute(
            """
            INSERT INTO device_samples (
                sampled_at, workspace_id, device_id, state, wan_source, 
                wan_ip, lte_signal_level, cellular_data_usage_bytes, 
                memory_usage_percent, uptime_seconds, client_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso, payload["workspace_id"], payload["device_id"], payload["state"],
                payload.get("wan_source"), payload.get("wan_ip"), payload.get("lte_signal_level"),
                payload.get("cellular_data_usage_bytes"), payload.get("memory_usage_percent"),
                payload.get("uptime_seconds"), len(payload.get("clients", []))
            )
        )

        # 4. Process connected clients via executemany block processing
        clients = payload.get("clients", [])
        if clients:
            client_upserts = []
            client_samples = []
            
            for c in clients:
                mac = c["mac"]
                client_upserts.append((payload["device_id"], mac, c.get("name", ""), c["type"], c["connection_status"], c.get("ip_address"), int(c.get("is_blocked", False)), c.get("wifi_experience"), now_iso))
                client_samples.append((now_iso, payload["device_id"], mac, c["connection_status"], c.get("ip_address"), int(c.get("is_blocked", False)), c.get("wifi_experience")))

            # Synchronize static client lookup states
            await connection.executemany(
                """
                INSERT INTO clients (device_id, mac, name, type, connection_status, ip_address, is_blocked, wifi_experience, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, mac) DO UPDATE SET
                    connection_status = excluded.connection_status,
                    ip_address = excluded.ip_address,
                    is_blocked = excluded.is_blocked,
                    wifi_experience = excluded.wifi_experience,
                    last_seen_at = excluded.last_seen_at
                """,
                client_upserts
            )

            # Append historical client samples
            await connection.executemany(
                """
                INSERT INTO client_samples (sampled_at, device_id, mac, connection_status, ip_address, is_blocked, wifi_experience)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                client_samples
            )

        # 5. Commit transaction safely
        await connection.commit()
        
    except Exception as e:
        await connection.rollback()
        # Log response failure history metadata safely
        await log_api_error(connection, payload.get("endpoint", "unknown"), str(e))
        raise e


async def log_api_error(connection: aiosqlite.Connection, endpoint: str, error_message: str) -> None:
    """Helper to log runtime failures directly into the tracking database tables."""
    try:
        await connection.execute(
            """
            INSERT INTO api_response_log (fetched_at, endpoint, err, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (datetime.utcnow().isoformat(), endpoint, error_message, "{}")
        )
        await connection.commit()
    except Exception:
        pass  # Prevent cascading errors if database write locks hard


async def get_active_devices(connection: aiosqlite.Connection) -> list[aiosqlite.Row]:
    """Fetches clean records for UI state synchronization inside tui.py."""
    async with connection.execute("SELECT id, name, model, state, client_count, last_seen_at FROM devices ORDER BY name ASC") as cursor:
        return await cursor.fetchall()


if __name__ == "__main__":
    import asyncio
    
    async def main():
        async with database_connection("test.db") as conn:
            async with conn.execute(
                "SELECT * FROM schema_migrations LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                print(dict(row) if row else None)

    asyncio.run(main())
