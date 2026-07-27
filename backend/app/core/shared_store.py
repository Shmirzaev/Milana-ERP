from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Protocol
from urllib.parse import urlparse

from app.core.config import settings


class SharedCounterStore(Protocol):
    def increment(self, key: str, ttl_seconds: int) -> int: ...
    def ttl(self, key: str) -> int | None: ...
    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...
    def delete(self, *keys: str) -> None: ...
    def clear_namespace(self, namespace: str) -> None: ...


@dataclass
class InMemorySharedCounterStore:
    """Local/dev/test fallback. Not suitable for multi-worker production."""

    _values: dict[str, tuple[int | str, float]] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [key for key, (_, expires_at) in self._values.items() if expires_at <= now]
        for key in expired:
            self._values.pop(key, None)

    def increment(self, key: str, ttl_seconds: int) -> int:
        ttl = max(1, int(ttl_seconds or 1))
        with self._lock:
            self._purge_expired()
            now = time.time()
            value, expires_at = self._values.get(key, (0, now + ttl))
            count = int(value) + 1
            self._values[key] = (count, expires_at)
            return count

    def ttl(self, key: str) -> int | None:
        with self._lock:
            self._purge_expired()
            row = self._values.get(key)
            if not row:
                return None
            remaining = int(row[1] - time.time())
            return max(1, remaining)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        ttl = max(1, int(ttl_seconds or 1))
        with self._lock:
            self._purge_expired()
            self._values[key] = (value, time.time() + ttl)

    def delete(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._values.pop(key, None)

    def clear_namespace(self, namespace: str) -> None:
        with self._lock:
            prefix = f"{namespace}:"
            for key in [key for key in self._values if key == namespace or key.startswith(prefix)]:
                self._values.pop(key, None)


class RedisSharedCounterStore:
    def __init__(self, url: str, *, prefix: str) -> None:
        try:
            from redis import Redis
        except ImportError as exc:
            raise RuntimeError("Redis shared store is configured, but the redis package is not installed") from exc

        self._client = Redis.from_url(url, decode_responses=True)
        self._prefix = prefix.strip(":")
        self._client.ping()

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}" if self._prefix else key

    def increment(self, key: str, ttl_seconds: int) -> int:
        ttl = max(1, int(ttl_seconds or 1))
        redis_key = self._key(key)
        pipe = self._client.pipeline()
        pipe.incr(redis_key)
        pipe.ttl(redis_key)
        count, current_ttl = pipe.execute()
        if int(current_ttl) < 0:
            self._client.expire(redis_key, ttl)
        return int(count)

    def ttl(self, key: str) -> int | None:
        current_ttl = int(self._client.ttl(self._key(key)))
        if current_ttl < 0:
            return None
        return max(1, current_ttl)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        ttl = max(1, int(ttl_seconds or 1))
        self._client.set(self._key(key), value, ex=ttl)

    def delete(self, *keys: str) -> None:
        if keys:
            self._client.delete(*(self._key(key) for key in keys))

    def clear_namespace(self, namespace: str) -> None:
        pattern = self._key(f"{namespace}:*")
        keys = list(self._client.scan_iter(pattern))
        if keys:
            self._client.delete(*keys)


class SQLiteSharedCounterStore:
    """Single-container shared store for deployments that do not have Redis."""

    def __init__(self, url: str, *, prefix: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "sqlite":
            raise ValueError("SQLite shared store URL must use sqlite:///path.db")

        raw_path = parsed.path
        if parsed.netloc:
            raw_path = f"//{parsed.netloc}{parsed.path}"
        elif os.name == "nt" and len(raw_path) >= 4 and raw_path[0] == "/" and raw_path[2] == ":":
            raw_path = raw_path[1:]
        if not raw_path:
            raise ValueError("SQLite shared store URL must include a database path")

        self._db_path = Path(raw_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._prefix = prefix.strip(":")
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shared_counters (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_shared_counters_expires_at ON shared_counters (expires_at)")

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}" if self._prefix else key

    @staticmethod
    def _purge_expired(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM shared_counters WHERE expires_at <= ?", (time.time(),))

    def increment(self, key: str, ttl_seconds: int) -> int:
        ttl = max(1, int(ttl_seconds or 1))
        db_key = self._key(key)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._purge_expired(conn)
            row = conn.execute("SELECT value, expires_at FROM shared_counters WHERE key = ?", (db_key,)).fetchone()
            now = time.time()
            if row:
                try:
                    count = int(row[0]) + 1
                except (TypeError, ValueError):
                    count = 1
                expires_at = float(row[1])
            else:
                count = 1
                expires_at = now + ttl
            conn.execute(
                "INSERT OR REPLACE INTO shared_counters (key, value, expires_at) VALUES (?, ?, ?)",
                (db_key, str(count), expires_at),
            )
            conn.commit()
            return count

    def ttl(self, key: str) -> int | None:
        db_key = self._key(key)
        with self._lock, self._connect() as conn:
            self._purge_expired(conn)
            row = conn.execute("SELECT expires_at FROM shared_counters WHERE key = ?", (db_key,)).fetchone()
            if not row:
                return None
            remaining = int(float(row[0]) - time.time())
            return max(1, remaining)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        ttl = max(1, int(ttl_seconds or 1))
        with self._lock, self._connect() as conn:
            self._purge_expired(conn)
            conn.execute(
                "INSERT OR REPLACE INTO shared_counters (key, value, expires_at) VALUES (?, ?, ?)",
                (self._key(key), value, time.time() + ttl),
            )

    def delete(self, *keys: str) -> None:
        if not keys:
            return
        with self._lock, self._connect() as conn:
            conn.executemany("DELETE FROM shared_counters WHERE key = ?", [(self._key(key),) for key in keys])

    def clear_namespace(self, namespace: str) -> None:
        prefix = self._key(namespace)
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM shared_counters WHERE key = ? OR key LIKE ?", (prefix, f"{prefix}:%"))


_store: SharedCounterStore | None = None


def get_shared_counter_store() -> SharedCounterStore:
    global _store
    if _store is not None:
        return _store

    url = settings.shared_store_url
    if url:
        parsed = urlparse(url)
        if parsed.scheme in {"redis", "rediss"}:
            _store = RedisSharedCounterStore(url, prefix=settings.SHARED_STORE_KEY_PREFIX)
        elif parsed.scheme == "sqlite":
            _store = SQLiteSharedCounterStore(url, prefix=settings.SHARED_STORE_KEY_PREFIX)
        else:
            raise RuntimeError("SHARED_STORE_URL must use redis://, rediss://, or sqlite:///")
        return _store

    if settings.strict_security_required:
        raise RuntimeError("SHARED_STORE_URL or REDIS_URL is required for rate limits and auth lockouts in production/public deployments")

    _store = InMemorySharedCounterStore()
    return _store


def reset_shared_counter_store_for_tests() -> None:
    global _store
    _store = InMemorySharedCounterStore()
