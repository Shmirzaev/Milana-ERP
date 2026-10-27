"""The approved PostgreSQL instance boundary for the real-PostgreSQL fixtures.

Reusable repository tests must not carry a machine-specific database URL. They
read the explicitly approved test configuration from the environment, verify
that the live server really is that approved instance, create exactly one
recorded target database, and drop exactly that database again.

Nothing here widens the boundary: no wildcard cleanup, no prefix scan, no
terminating of other connections and no `FORCE`. A configuration that is absent
or that does not match the live server fails closed, so a fixture never runs
against an unapproved server.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

CONFIG_ENV = "MILANA_TEST_PG_INSTANCE"

_IDENTITY_SQL = """
SELECT host(inet_server_addr()) AS host,
       inet_server_port() AS port,
       current_setting('server_version') AS server_version,
       (SELECT system_identifier::text FROM pg_control_system()) AS system_identifier,
       current_setting('data_directory') AS data_directory
"""

_REQUIRED_KEYS = (
    "admin_dsn",
    "host",
    "port",
    "server_version",
    "system_identifier",
    "data_directory",
    "target_prefix",
)


class ApprovedInstanceUnavailable(RuntimeError):
    """The approved test instance is not configured, or does not match."""


@dataclass(frozen=True)
class ApprovedInstance:
    """The approved test instance and the target-namespace it may create in."""

    admin_dsn: str
    host: str
    port: int
    server_version: str
    system_identifier: str
    data_directory: str
    target_prefix: str

    @property
    def admin_url(self) -> URL:
        return make_url(self.admin_dsn)


def load_approved_instance() -> ApprovedInstance:
    """Read the approved configuration, or fail closed."""
    raw = os.environ.get(CONFIG_ENV)
    if not raw:
        raise ApprovedInstanceUnavailable(
            f"{CONFIG_ENV} is not set; the real-PostgreSQL fixtures run only against the "
            "explicitly approved test instance"
        )
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise ApprovedInstanceUnavailable(f"{CONFIG_ENV} is not valid JSON") from error
    if not isinstance(data, dict):
        raise ApprovedInstanceUnavailable(f"{CONFIG_ENV} must be a JSON object")
    missing = [key for key in _REQUIRED_KEYS if key not in data]
    if missing:
        raise ApprovedInstanceUnavailable(f"{CONFIG_ENV} is missing: {', '.join(sorted(missing))}")
    return ApprovedInstance(
        admin_dsn=str(data["admin_dsn"]),
        host=str(data["host"]),
        port=int(data["port"]),
        server_version=str(data["server_version"]),
        system_identifier=str(data["system_identifier"]),
        data_directory=str(data["data_directory"]),
        target_prefix=str(data["target_prefix"]),
    )


def identity_of(row) -> dict:
    """The identity fields of a live server row."""
    return {
        "host": str(row.host),
        "port": int(row.port),
        "server_version": str(row.server_version),
        "system_identifier": str(row.system_identifier),
        "data_directory": str(row.data_directory),
    }


def compare_identity(expected: ApprovedInstance, actual: dict) -> None:
    """Fail closed unless the live server is exactly the approved instance."""
    wanted = {
        "host": expected.host,
        "port": expected.port,
        "server_version": expected.server_version,
        "system_identifier": expected.system_identifier,
        "data_directory": expected.data_directory,
    }
    mismatched = sorted(key for key, value in wanted.items() if actual.get(key) != value)
    if mismatched:
        raise ApprovedInstanceUnavailable(
            "the live PostgreSQL server is not the approved test instance: "
            + ", ".join(f"{key}={actual.get(key)!r} != {wanted[key]!r}" for key in mismatched)
        )


def verify_approved_instance(instance: ApprovedInstance) -> dict:
    """Check the live server identity against the approved configuration."""
    engine = create_engine(instance.admin_url, connect_args={"connect_timeout": 5}, future=True)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(_IDENTITY_SQL)).one()
    finally:
        engine.dispose()
    actual = identity_of(row)
    compare_identity(instance, actual)
    return actual


def target_database_name(instance: ApprovedInstance) -> str:
    """The recorded target name: the approved prefix plus a fresh 12 hex."""
    return f"{instance.target_prefix}{secrets.token_hex(6)}"


def create_database_sql(name: str) -> str:
    """Create exactly the recorded database."""
    return f'CREATE DATABASE "{name}"'


def drop_database_sql(name: str) -> str:
    """Drop exactly the recorded database. No FORCE and no wildcard."""
    return f'DROP DATABASE "{name}"'


def create_target_database(instance: ApprovedInstance) -> str:
    """Create exactly one recorded target database and return its name."""
    name = target_database_name(instance)
    engine = create_engine(instance.admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(create_database_sql(name))
    finally:
        engine.dispose()
    return name


def drop_target_database(instance: ApprovedInstance, name: str) -> None:
    """Drop exactly the recorded target database."""
    engine = create_engine(instance.admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(drop_database_sql(name))
    finally:
        engine.dispose()
