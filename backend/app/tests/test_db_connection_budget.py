import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import exc
from sqlalchemy.pool import QueuePool


SLOTCTL = Path(__file__).parents[3] / "deploy" / "slotctl.py"
spec = importlib.util.spec_from_file_location("slotctl_connection_budget", SLOTCTL)
slotctl = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(slotctl)


class _FakeConnection:
    def rollback(self):
        pass

    def close(self):
        pass


def test_blue_green_backend_pool_budget_is_bounded_by_documented_postgres_ceiling():
    assert slotctl.backend_connection_budget() == 48
    assert slotctl.POSTGRES_MAX_CONNECTIONS == 100
    assert slotctl.POSTGRES_MAX_CONNECTIONS - slotctl.backend_connection_budget() == 52
    slotctl.validate_backend_connection_budget()


@pytest.mark.parametrize(
    ("slots", "workers", "pool_size", "max_overflow"),
    [(0, 2, 8, 4), (2, 0, 8, 4), (2, 2, 0, 4), (2, 2, 8, -1)],
)
def test_backend_connection_budget_rejects_invalid_dimensions(slots, workers, pool_size, max_overflow):
    with pytest.raises(ValueError):
        slotctl.backend_connection_budget(
            slots=slots,
            workers=workers,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )


def test_four_worker_pools_can_checkout_the_configured_overlap_capacity_without_postgres():
    pools = [
        QueuePool(
            creator=_FakeConnection,
            pool_size=slotctl.DB_POOL_SIZE,
            max_overflow=slotctl.DB_MAX_OVERFLOW,
            timeout=0.01,
        )
        for _ in range(2 * slotctl.BACKEND_WORKERS)
    ]
    checkouts = []
    try:
        for pool in pools:
            checkouts.extend(pool.connect() for _ in range(slotctl.DB_POOL_SIZE + slotctl.DB_MAX_OVERFLOW))
            assert pool.checkedout() == slotctl.DB_POOL_SIZE + slotctl.DB_MAX_OVERFLOW
            with pytest.raises(exc.TimeoutError):
                pool.connect()
        assert sum(pool.checkedout() for pool in pools) == slotctl.backend_connection_budget()
    finally:
        for connection in checkouts:
            connection.close()
        for pool in pools:
            pool.dispose()


def test_backend_stage_passes_the_budgeted_worker_and_pool_limits_to_docker():
    commands = []
    with (
        patch.object(slotctl, "inspect_image"),
        patch.object(slotctl, "remove_inactive_container"),
        patch.object(slotctl, "wait_for_health"),
        patch.object(slotctl, "warm"),
        patch.object(slotctl, "run", side_effect=lambda *args, **_kwargs: commands.append(args)),
    ):
        slotctl.stage("backend", "green", "test-release", "example/backend:test")

    docker_run = commands[0]
    assert f"DB_POOL_SIZE={slotctl.DB_POOL_SIZE}" in docker_run
    assert f"DB_MAX_OVERFLOW={slotctl.DB_MAX_OVERFLOW}" in docker_run
    assert f"WEB_CONCURRENCY={slotctl.BACKEND_WORKERS}" in docker_run
