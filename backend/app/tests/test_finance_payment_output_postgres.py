"""Typed Finance payment replay on the approved disposable PostgreSQL target.

Reuse the existing PostgreSQL race/rollback oracles, but supply the migrated,
identity-pinned customer fixture instead of the legacy shared-DSN fixture.
Calling the oracle functions directly avoids requesting their `postgres_sessions`
fixture, which creates its own schema on STABILIZATION_POSTGRES_URL.
"""

import pytest

from app.tests.test_customer_create_postgres import customer_pg_sessions
from app.tests.test_idempotency_identity import (
    test_postgres_concurrent_payment_retries as _concurrent_payment_retries,
    test_postgres_other_users_key_does_not_wait_for_first_user as _other_user_key_is_independent,
    test_postgres_rollback_releases_retry_lock_without_committing_business_write as _rollback_releases_retry_lock,
)


@pytest.mark.parametrize(
    "case",
    ["same", "other_user", "other_factory", "changed_payload"],
    ids=["same-key-replay", "different-user", "different-factory", "changed-payload"],
)
def test_pg_typed_payment_concurrent_retries(customer_pg_sessions, case, monkeypatch):
    _concurrent_payment_retries(customer_pg_sessions, case, monkeypatch)


def test_pg_typed_payment_other_user_key_is_independent(customer_pg_sessions):
    _other_user_key_is_independent(customer_pg_sessions)


def test_pg_typed_payment_rollback_releases_retry_lock(customer_pg_sessions):
    _rollback_releases_retry_lock(customer_pg_sessions)
