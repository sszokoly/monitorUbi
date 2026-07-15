"""SQLite setup and migration helpers for monitorUbi."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


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
