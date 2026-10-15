"""Durable, database-backed fixed-window rate limiting (works across serverless instances)."""

import time

import psycopg

from app.errors import too_many


def hit(conn: psycopg.Connection, bucket: str, limit: int, window_seconds: int) -> None:
    window_start = int(time.time()) // window_seconds * window_seconds
    row = conn.execute(
        """insert into public.rate_limits (bucket, window_start, count)
           values (%s, to_timestamp(%s), 1)
           on conflict (bucket, window_start) do update set count = public.rate_limits.count + 1
           returning count""",
        (bucket[:200], window_start, ),
    ).fetchone()
    if row["count"] > limit:
        raise too_many(retry_after=window_seconds - (int(time.time()) - window_start))
