"""Dependency readiness probes share one worker and deadline per process."""
from threading import Event, Lock, Thread
from time import perf_counter

from sqlalchemy import text

from app.core.shared_store import get_shared_counter_store
from app.db.session import engine


_READINESS_CHECK_SLOT = Lock()
_READINESS_PROBE: tuple[Event, dict[str, str], float] | None = None


def _probe_postgresql() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()


def _probe_shared_store() -> None:
    get_shared_counter_store().ttl("readiness")


def _readiness_checks_within(timeout_seconds: float) -> dict[str, str]:
    """Share one probe and deadline; a stuck dependency cannot spawn more threads."""
    global _READINESS_PROBE
    slot = _READINESS_CHECK_SLOT
    with slot:
        if _READINESS_PROBE is None or _READINESS_PROBE[0].is_set():
            completed = Event()
            checks = {"postgresql": "unavailable", "shared_store": "unavailable"}
            deadline = perf_counter() + max(timeout_seconds, 0.001)
            _READINESS_PROBE = (completed, checks, deadline)

            def run_probe() -> None:
                try:
                    for name, probe in (("postgresql", _probe_postgresql), ("shared_store", _probe_shared_store)):
                        if perf_counter() >= deadline:
                            break
                        try:
                            probe()
                        except Exception:
                            pass
                        else:
                            with slot:
                                if perf_counter() < deadline:
                                    checks[name] = "ok"
                finally:
                    completed.set()

            try:
                Thread(target=run_probe, name="dependency-readiness", daemon=True).start()
            except Exception:
                completed.set()
        completed, checks, deadline = _READINESS_PROBE

    completed.wait(timeout=max(0.0, deadline - perf_counter()))
    with slot:
        return checks.copy()
