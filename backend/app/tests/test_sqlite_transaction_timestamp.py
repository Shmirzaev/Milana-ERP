"""The disposable SQLite clock models PostgreSQL transaction timestamp semantics."""
import time

from app.tests.conftest import test_engine


def test_timestamp_is_stable_across_statement_second_boundary_and_refreshes_after_commit():
    with test_engine.begin() as connection:
        first = connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one()
        time.sleep(1.1)
        second = connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one()
        assert second == first
    with test_engine.begin() as connection:
        following = connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one()
    assert following > first


def test_simultaneous_connections_keep_their_own_transaction_clock():
    with test_engine.begin() as first_connection:
        first = first_connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one()
        with test_engine.begin() as second_connection:
            second = second_connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one()
            assert second > first
            assert first_connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one() == first
            assert second_connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one() == second
