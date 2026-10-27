"""Offline guard checks for the approved PostgreSQL instance boundary.

No database and no server: these checks read the guard itself, so they can run
without the approved test instance. The real create/drop round trip stays a
separate real-PostgreSQL gate.
"""

import json
import re

import pytest

from app.tests.pg_approved_instance import (
    CONFIG_ENV,
    ApprovedInstanceUnavailable,
    compare_identity,
    create_database_sql,
    drop_database_sql,
    identity_of,
    load_approved_instance,
    target_database_name,
)

APPROVED = {
    "admin_dsn": "postgresql+psycopg2://postgres@127.0.0.1:51716/postgres",
    "host": "127.0.0.1",
    "port": 51716,
    "server_version": "17.11",
    "system_identifier": "7700371345869473300",
    "data_directory": "C:/example/data",
    "target_prefix": "review_mm_catalog_",
}


class _Row:
    def __init__(self, **values):
        self.__dict__.update(values)


LIVE = _Row(
    host="127.0.0.1",
    port=51716,
    server_version="17.11",
    system_identifier="7700371345869473300",
    data_directory="C:/example/data",
)


def _set_config(monkeypatch, value):
    monkeypatch.setenv(CONFIG_ENV, json.dumps(value) if isinstance(value, dict) else value)


def test_an_absent_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    with pytest.raises(ApprovedInstanceUnavailable):
        load_approved_instance()


def test_a_malformed_configuration_fails_closed(monkeypatch):
    _set_config(monkeypatch, "{not json")
    with pytest.raises(ApprovedInstanceUnavailable):
        load_approved_instance()


def test_an_incomplete_configuration_fails_closed(monkeypatch):
    _set_config(monkeypatch, {key: value for key, value in APPROVED.items() if key != "system_identifier"})
    with pytest.raises(ApprovedInstanceUnavailable):
        load_approved_instance()


def test_a_complete_configuration_loads(monkeypatch):
    _set_config(monkeypatch, APPROVED)
    instance = load_approved_instance()
    assert instance.admin_url.host == "127.0.0.1"
    assert instance.admin_url.port == 51716
    assert instance.admin_url.database == "postgres"
    assert instance.target_prefix == "review_mm_catalog_"


def test_the_target_name_is_a_fresh_recorded_name_inside_the_approved_namespace(monkeypatch):
    _set_config(monkeypatch, APPROVED)
    instance = load_approved_instance()
    first = target_database_name(instance)
    second = target_database_name(instance)
    assert re.fullmatch(r"review_mm_catalog_[0-9a-f]{12}", first)
    assert first != second


def test_the_matching_identity_is_accepted(monkeypatch):
    _set_config(monkeypatch, APPROVED)
    instance = load_approved_instance()
    compare_identity(instance, identity_of(LIVE))


@pytest.mark.parametrize(
    "field,value",
    [
        ("host", "127.0.0.2"),
        ("port", 5432),
        ("server_version", "16.9"),
        ("system_identifier", "1"),
        ("data_directory", "C:/other/data"),
    ],
)
def test_a_mismatched_identity_fails_closed(monkeypatch, field, value):
    _set_config(monkeypatch, APPROVED)
    instance = load_approved_instance()
    actual = identity_of(LIVE)
    actual[field] = value
    with pytest.raises(ApprovedInstanceUnavailable) as error:
        compare_identity(instance, actual)
    assert field in str(error.value)


def test_the_sql_templates_target_exactly_the_recorded_name():
    name = "review_mm_catalog_0123456789ab"
    assert create_database_sql(name) == f'CREATE DATABASE "{name}"'
    assert drop_database_sql(name) == f'DROP DATABASE "{name}"'


def test_the_cleanup_templates_never_widen_the_boundary():
    name = "review_mm_catalog_0123456789ab"
    drop = drop_database_sql(name).lower()
    assert "force" not in drop
    assert "like" not in drop
    assert "pg_terminate_backend" not in drop
    assert name in drop
