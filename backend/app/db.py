"""PostgreSQL access. All SQL in the application uses bound parameters (never string formatting)."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.numeric import FloatLoader
from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None

# NUMERIC columns (battery %, limits, coordinates) are returned as float so the JSON API emits numbers.
psycopg.adapters.register_loader("numeric", FloatLoader)


def _conninfo() -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "row_factory": dict_row,
        # Required for Supabase's transaction pooler (Supavisor), which cannot hold prepared statements.
        "prepare_threshold": None,
        "application_name": "acme-clinical-api",
        "connect_timeout": 10,
    }
    if settings.db_ssl_root_cert:
        kwargs["sslmode"] = "verify-full"
        kwargs["sslrootcert"] = settings.db_ssl_root_cert
    return settings.database_url, kwargs


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        conninfo, kwargs = _conninfo()
        _pool = ConnectionPool(
            conninfo,
            kwargs=kwargs,
            min_size=0,
            max_size=get_settings().db_pool_max_size,
            open=True,
            timeout=15,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _set_limits(conn: psycopg.Connection) -> None:
    conn.execute("set local statement_timeout = '10s'")
    conn.execute("set local lock_timeout = '5s'")


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """A connection with an open transaction; commits on success, rolls back on error."""
    with get_pool().connection() as conn:
        with conn.transaction():
            _set_limits(conn)
            yield conn


def get_db() -> Iterator[psycopg.Connection]:
    """FastAPI dependency: one transaction per request.

    Convention: an HTTPException is a *handled* outcome (denied, throttled, not found...). Work done
    before it is raised - security audit entries, failed-login counters - is committed. Any other
    exception rolls the whole transaction back. Endpoints therefore validate before they write.
    """
    handled: HTTPException | None = None
    with get_pool().connection() as conn:
        with conn.transaction():
            _set_limits(conn)
            try:
                yield conn
            except HTTPException as exc:
                handled = exc
    if handled is not None:
        raise handled
