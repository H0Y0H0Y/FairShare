"""SQLite connection lifecycle and one-time initialization.

A single shared ``aiosqlite`` connection is used for the whole process. The bot
is a single async process, so one WAL-mode connection is both sufficient and the
simplest thing that is correct.
"""
from __future__ import annotations

import os
from pathlib import Path

import aiosqlite

from app.config import Settings

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() has not been called")
        return self._conn

    async def connect(self) -> None:
        """Open the connection, apply the schema, and seed the two partners."""
        db_path = self._settings.db_path
        # Ensure the parent directory exists (first boot on an empty volume).
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        self._conn = await aiosqlite.connect(db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON;")
        await self._init_schema()
        await self._seed_partners()

    async def _init_schema(self) -> None:
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        await self.conn.executescript(schema)
        await self.conn.commit()

    async def _seed_partners(self) -> None:
        """Keep the ``partners`` table in sync with configured env values.

        Upsert on the fixed ids (1, 2) so renaming a partner or changing a
        Telegram id in the environment is reflected without losing history.
        """
        for p in self._settings.partners:
            await self.conn.execute(
                """
                INSERT INTO partners (id, telegram_id, name)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    telegram_id = excluded.telegram_id,
                    name        = excluded.name
                """,
                (p.id, p.telegram_id, p.name),
            )
        await self.conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
