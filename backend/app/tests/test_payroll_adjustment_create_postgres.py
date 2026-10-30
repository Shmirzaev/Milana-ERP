"""Approved PostgreSQL wrappers for the manual adjustment operation oracles."""

from app.tests.test_customer_create_postgres import customer_pg_sessions  # noqa: F401
from app.tests import test_payroll_period_races as payroll_period_race_oracles


def test_approved_pg_adjustment_writer_serializes_before_period_lock(customer_pg_sessions, monkeypatch):
    """Run the existing lock-order oracle on the approved isolated database."""
    payroll_period_race_oracles.test_postgres_adjustment_writer_serializes_before_period_lock(
        (customer_pg_sessions, None), monkeypatch
    )


def test_approved_pg_manual_adjustment_flush_and_audit_failure_roll_back(customer_pg_sessions, monkeypatch):
    """Run the existing transaction rollback/retry oracle on approved PostgreSQL."""
    payroll_period_race_oracles.test_postgres_manual_adjustment_flush_and_audit_failure_roll_back(
        (customer_pg_sessions, None), monkeypatch
    )
