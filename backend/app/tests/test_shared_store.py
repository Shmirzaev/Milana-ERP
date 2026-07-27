import time

from app.core.shared_store import SQLiteSharedCounterStore


def test_sqlite_shared_counter_store(tmp_path):
    store = SQLiteSharedCounterStore(f"sqlite:///{tmp_path / 'shared-store.db'}", prefix="test")

    assert store.increment("auth:login:alice", 30) == 1
    assert store.increment("auth:login:alice", 30) == 2
    assert store.ttl("auth:login:alice") is not None

    store.set("auth:login-lock:alice", "locked", 30)
    assert store.ttl("auth:login-lock:alice") is not None

    store.delete("auth:login:alice")
    assert store.ttl("auth:login:alice") is None

    store.clear_namespace("auth")
    assert store.ttl("auth:login-lock:alice") is None


def test_sqlite_shared_counter_store_expires(tmp_path):
    store = SQLiteSharedCounterStore(f"sqlite:///{tmp_path / 'shared-store.db'}", prefix="test")

    store.increment("short", 1)
    time.sleep(1.1)

    assert store.ttl("short") is None
    assert store.increment("short", 30) == 1
