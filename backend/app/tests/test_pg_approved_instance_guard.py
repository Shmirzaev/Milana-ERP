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

@pytest.mark.parametrize("field,value", [
    ("admin_dsn", "postgresql+psycopg2://postgres@192.0.2.1:51716/postgres"),
    ("admin_dsn", "postgresql+psycopg2://postgres@127.0.0.1:51716/other"),
    ("admin_dsn", "postgresql+psycopg2://postgres@127.0.0.1:51716/postgres?host=other"),
    ("admin_dsn", "postgresql+psycopg2://postgres@127.0.0.1:51717/postgres"),
    ("target_prefix", 'review_"evil_'), ("target_prefix", "a" * 52 + "_"),
])
def test_unsafe_configuration_is_rejected_before_connect(monkeypatch, field, value):
    _set_config(monkeypatch, {**APPROVED, field: value})
    with pytest.raises(ApprovedInstanceUnavailable): load_approved_instance()

@pytest.mark.parametrize("name", ['x";DROP DATABASE other;--', "x" * 64, "UPPER", "x-y"])
def test_sql_rejects_untrusted_identifiers(name):
    with pytest.raises(ApprovedInstanceUnavailable): create_database_sql(name)
    with pytest.raises(ApprovedInstanceUnavailable): drop_database_sql(name)

class _HoldObserved(BaseException):
    """Pure-fake observer only; never a real cleanup authorization."""


@pytest.fixture
def fake_admin(monkeypatch):
    from types import SimpleNamespace
    from app.tests import pg_approved_instance as guard

    _set_config(monkeypatch, APPROVED)
    # These maps belong only to this import in the network-NONE offline run.
    monkeypatch.setattr(guard, "_owned_targets", {})
    monkeypatch.setattr(guard, "_pending_targets", set())
    monkeypatch.setattr(guard, "_lifecycles", {})
    calls, engines, holds, listeners = [], [], [], []
    state = SimpleNamespace(host=LIVE.host, database="postgres", fault=None)

    class Result:
        def __init__(self, row=None, scalar=None): self.row, self.scalar = row, scalar
        def one(self): return self.row
        def scalar_one(self): return self.scalar

    class Connection:
        def __init__(self, number): self.number = number
        def __enter__(self): calls.append(("enter", self.number)); return self
        def __exit__(self, *args):
            calls.append(("exit", self.number))
            if self.number == 0 and state.fault == "exit": raise RuntimeError("admin exit")
        def execute(self, statement, parameters=None):
            sql = str(statement)
            if sql == guard._IDENTITY_SQL:
                calls.append("preflight")
                return Result(_Row(**{**LIVE.__dict__, "host":state.host, "database":state.database}))
            if sql == guard._DRAIN_SQL:
                calls.append("drain")
                return Result(_Row(stats_visible=True, target_exists=True, clients=0, prepared=0, locks=0))
            assert sql.startswith("SELECT EXISTS"), sql
            calls.append("absence")
            return Result(scalar=False)
        def exec_driver_sql(self, sql):
            calls.append(sql)
            if state.fault == "create" and sql.startswith("CREATE"):
                raise RuntimeError("unknown create outcome")

    class Engine:
        def __init__(self, number):
            self.number = number
            self.pool = SimpleNamespace(checkedout=lambda:0)
        def connect(self): return Connection(self.number)
        def dispose(self):
            calls.append(("dispose", self.number))
            if (self.number == 0 and state.fault == "dispose") or state.fault == "target_dispose":
                raise RuntimeError("dispose failure")

    def make(*args, **kwargs):
        assert kwargs["connect_args"]["connect_timeout"] == 5
        engine = Engine(len(engines)); engines.append(engine); return engine

    def observe(operation, retained, errors):
        holds.append((operation, retained, list(errors)))
        raise _HoldObserved()

    monkeypatch.setattr(guard, "create_engine", make)
    monkeypatch.setattr(guard, "_park", observe)
    monkeypatch.setattr(guard.event, "listens_for", lambda engine, name: lambda fn:listeners.append(fn) or fn)
    return SimpleNamespace(guard=guard, state=state, calls=calls, engines=engines, holds=holds, listeners=listeners)


def test_owned_lifecycle_checks_each_admin_connection_and_refuses_unowned(fake_admin):
    f = fake_admin; guard = f.guard
    target = guard.create_target_database(load_approved_instance()); name = guard.owned_target_name(target)
    guard.drop_target_database(target)
    assert [call for call in f.calls if isinstance(call,str)] == [
        "preflight", f'CREATE DATABASE "{name}"', "preflight", "drain", f'DROP DATABASE "{name}"', "absence"]
    assert not guard._owned_targets and not guard._lifecycles
    with pytest.raises(ApprovedInstanceUnavailable): guard.drop_target_database(target)
    with pytest.raises(ApprovedInstanceUnavailable): guard.drop_target_database(guard.OwnedTarget())


def test_wrong_actual_database_prevents_mutation(fake_admin):
    f = fake_admin; f.state.database = "wrong"
    with pytest.raises(ApprovedInstanceUnavailable): f.guard.create_target_database(load_approved_instance())
    assert not any(isinstance(call,str) and call.startswith("CREATE") for call in f.calls)
    assert not f.guard._owned_targets and not f.guard._lifecycles and not f.holds


def test_target_engine_checks_every_checkout(fake_admin):
    f = fake_admin; guard = f.guard
    target = guard.create_target_database(load_approved_instance()); name = guard.owned_target_name(target)
    engine = guard.target_engine(target)
    class Result:
        def __init__(self, database): self.database = database
        def one(self): return _Row(**{**LIVE.__dict__, "database":self.database})
    class Connection:
        def __init__(self, database): self.database, self.rolled_back = database, False
        def execute(self, statement): return Result(self.database)
        def rollback(self): self.rolled_back = True
    good = Connection(name); f.listeners[0](good); assert good.rolled_back
    bad = Connection("review_mm_catalog_deadbeef1234")
    with pytest.raises(ApprovedInstanceUnavailable): f.listeners[0](bad)
    assert bad.rolled_back
    guard.finalize_target(target, engine)
    with pytest.raises(ApprovedInstanceUnavailable): f.listeners[0](good)


def test_drop_preflight_failure_holds_original_owner_without_ddl(fake_admin):
    f = fake_admin; guard = f.guard
    target = guard.create_target_database(load_approved_instance()); owner = guard._lifecycles[target]
    f.state.host = "127.0.0.2"
    with pytest.raises(_HoldObserved): guard.drop_target_database(target)
    assert f.holds[0][0] == "DROP_PREFLIGHT_OR_DRAIN" and f.holds[0][1] == (owner,)
    assert owner.held and target in guard._owned_targets
    assert not any(isinstance(call,str) and call.startswith("DROP") for call in f.calls)
    with pytest.raises(ApprovedInstanceUnavailable): guard.owned_target_name(target)


@pytest.mark.parametrize("failure", ["exit", "dispose"])
def test_create_success_then_admin_teardown_failure_retains_without_drop(fake_admin, failure):
    f = fake_admin; guard = f.guard; f.state.fault = failure
    with pytest.raises(_HoldObserved): guard.create_target_database(load_approved_instance())
    owner = f.holds[0][1][0]
    assert owner.create is guard._OperationState.ACKNOWLEDGED and owner.held
    assert owner.admin_engine is f.engines[0]
    assert len([call for call in f.calls if isinstance(call,str) and call.startswith("CREATE")]) == 1
    assert not any(isinstance(call,str) and call.startswith("DROP") for call in f.calls)
    assert owner.target in guard._owned_targets and owner.target not in guard._pending_targets


def test_create_close_failure_preserves_first_error_and_never_attempts_drop(fake_admin):
    f = fake_admin; f.state.fault = "exit"
    with pytest.raises(_HoldObserved): f.guard.create_target_database(load_approved_instance())
    owner = f.holds[0][1][0]
    assert len(owner.errors) == 1 and str(owner.errors[0]) == "admin exit"
    assert not any(isinstance(call,str) and call.startswith("DROP") for call in f.calls)
    assert ("dispose",0) not in f.calls


def test_uncertain_create_outcome_keeps_record_without_automatic_drop(fake_admin):
    f = fake_admin; guard = f.guard; f.state.fault = "create"
    with pytest.raises(_HoldObserved): guard.create_target_database(load_approved_instance())
    owner = f.holds[0][1][0]
    assert owner.create is guard._OperationState.ISSUED_UNKNOWN
    assert owner.target in guard._pending_targets and owner.target in guard._owned_targets
    assert ("exit",0) not in f.calls and ("dispose",0) not in f.calls
    assert not any(isinstance(call,str) and call.startswith("DROP") for call in f.calls)
    with pytest.raises(ApprovedInstanceUnavailable): guard.drop_target_database(owner.target)


def test_dispose_failure_prevents_drop_and_retains_setup_error(fake_admin):
    f = fake_admin; guard = f.guard
    target = guard.create_target_database(load_approved_instance()); engine = guard.target_engine(target)
    owner = guard._lifecycles[target]; setup_error = ValueError("setup failure")
    f.state.fault = "target_dispose"
    with pytest.raises(_HoldObserved):
        try: raise setup_error
        finally: guard.finalize_target(target, engine)
    assert owner.errors[0] is setup_error and str(owner.errors[1]) == "dispose failure"
    assert f.holds[0][0] == "TARGET_DISPOSE" and owner.target_engine is engine
    assert not any(isinstance(call,str) and call.startswith("DROP") for call in f.calls)


def test_required_mode_fails_and_missing_optional_configuration_skips(monkeypatch):
    from app.tests import pg_approved_instance as guard
    monkeypatch.delenv(guard.CONFIG_ENV, raising=False)
    monkeypatch.delenv(guard.REQUIRE_ENV, raising=False)
    error=ApprovedInstanceUnavailable('no config')
    with pytest.raises(pytest.skip.Exception): guard.require_or_skip(error)
    monkeypatch.setenv(guard.REQUIRE_ENV,'1')
    with pytest.raises(pytest.fail.Exception): guard.require_or_skip(error)
    monkeypatch.delenv(guard.REQUIRE_ENV)
    monkeypatch.setenv(guard.CONFIG_ENV,'bad')
    with pytest.raises(pytest.fail.Exception): guard.require_or_skip(error)
