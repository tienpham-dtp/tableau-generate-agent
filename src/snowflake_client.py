"""Snowflake connection wrapper for schema exploration and data sampling."""

from __future__ import annotations

from typing import Any

import snowflake.connector

from src.config import SnowflakeConfig


class SnowflakeClient:
    def __init__(self, config: SnowflakeConfig):
        self._config = config
        self._conn: snowflake.connector.SnowflakeConnection | None = None

    def connect(self) -> None:
        self._conn = snowflake.connector.connect(
            account=self._config.account,
            user=self._config.user,
            password=self._config.password,
            warehouse=self._config.warehouse,
            database=self._config.database,
            schema=self._config.schema_name,
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def conn(self) -> snowflake.connector.SnowflakeConnection:
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._conn

    def list_tables(self) -> list[dict[str, str]]:
        """Return list of tables/views in the configured schema."""
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT table_name, table_type "
                "FROM information_schema.tables "
                "WHERE table_schema = %s "
                "ORDER BY table_name",
                (self._config.schema_name,),
            )
            return [
                {"table_name": row[0], "table_type": row[1]} for row in cur
            ]
        finally:
            cur.close()

    def describe_table(self, table_name: str) -> list[dict[str, Any]]:
        """Return column metadata for a given table."""
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position",
                (self._config.schema_name, table_name),
            )
            return [
                {
                    "column_name": row[0],
                    "data_type": row[1],
                    "is_nullable": row[2],
                    "column_default": row[3],
                }
                for row in cur
            ]
        finally:
            cur.close()

    def fetch_sample(self, sql: str, limit: int = 5000) -> list[dict[str, Any]]:
        """Execute a SQL query and return up to `limit` rows as dicts."""
        cur = self.conn.cursor()
        try:
            cur.execute(f"SELECT * FROM ({sql}) AS _sub LIMIT {limit}")
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur]
        finally:
            cur.close()

    def run_query(self, sql: str) -> list[dict[str, Any]]:
        """Execute arbitrary SQL and return all rows as dicts."""
        cur = self.conn.cursor()
        try:
            cur.execute(sql)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur]
        finally:
            cur.close()
