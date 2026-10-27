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

def test_owned_lifecycle_checks_each_admin_connection_and_refuses_unowned(monkeypatch):
    from app.tests import pg_approved_instance as guard
    _set_config(monkeypatch, APPROVED); instance = load_approved_instance(); records = []
    class Result:
        def one(self): return _Row(**{**LIVE.__dict__, "database": "postgres"})
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement): records.append("preflight"); return Result()
        def exec_driver_sql(self, sql): records.append(sql)
    class Engine:
        def connect(self): return Connection()
        def dispose(self): records.append("dispose")
    def engine(*args, **kwargs):
        assert kwargs["connect_args"]["connect_timeout"] == 5
        return Engine()
    monkeypatch.setattr(guard, "create_engine", engine)
    target = guard.create_target_database(instance); name = guard.owned_target_name(target)
    guard.drop_target_database(target)
    assert records == ["preflight", f'CREATE DATABASE "{name}"', "dispose", "preflight", f'DROP DATABASE "{name}"', "dispose"]
    with pytest.raises(ApprovedInstanceUnavailable): guard.drop_target_database(target)
    with pytest.raises(ApprovedInstanceUnavailable): guard.drop_target_database(guard.OwnedTarget())

def test_wrong_actual_database_prevents_mutation(monkeypatch):
    from app.tests import pg_approved_instance as guard
    _set_config(monkeypatch, APPROVED); instance = load_approved_instance()
    class Result:
        def one(self): return _Row(**{**LIVE.__dict__, "database": "wrong"})
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement): return Result()
        def exec_driver_sql(self, sql): pytest.fail("mutated wrong database")
    class Engine:
        def connect(self): return Connection()
        def dispose(self): pass
    monkeypatch.setattr(guard, "create_engine", lambda *a, **k: Engine())
    with pytest.raises(ApprovedInstanceUnavailable): guard.create_target_database(instance)

def test_target_engine_checks_every_checkout(monkeypatch):
    from app.tests import pg_approved_instance as guard
    _set_config(monkeypatch, APPROVED); instance = load_approved_instance()
    target = guard.OwnedTarget(); guard._owned_targets[target] = (instance, "review_mm_catalog_0123456789ab")
    listeners = []
    class Engine: pass
    monkeypatch.setattr(guard, "create_engine", lambda *a, **k: Engine())
    monkeypatch.setattr(guard.event, "listens_for", lambda engine, name: lambda fn: listeners.append(fn) or fn)
    guard.target_engine(target)
    class Result:
        def __init__(self, database): self.database = database
        def one(self): return _Row(**{**LIVE.__dict__, "database": self.database})
    class Connection:
        def __init__(self, database): self.database, self.rolled_back = database, False
        def execute(self, statement): return Result(self.database)
        def rollback(self): self.rolled_back = True
    good = Connection("review_mm_catalog_0123456789ab"); listeners[0](good); assert good.rolled_back
    bad = Connection("review_mm_catalog_deadbeef1234")
    with pytest.raises(ApprovedInstanceUnavailable): listeners[0](bad)
    assert bad.rolled_back
    del guard._owned_targets[target]
    with pytest.raises(ApprovedInstanceUnavailable): listeners[0](good)

def test_drop_failure_retains_ownership_and_never_issues_ddl(monkeypatch):
    from app.tests import pg_approved_instance as guard
    _set_config(monkeypatch, APPROVED); instance = load_approved_instance()
    target = guard.OwnedTarget(); guard._owned_targets[target] = (instance, "review_mm_catalog_0123456789ab")
    class Result:
        def one(self): return _Row(**{**LIVE.__dict__, "host": "127.0.0.2", "database": "postgres"})
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, statement): return Result()
        def exec_driver_sql(self, sql): pytest.fail("drop on mismatched server")
    class Engine:
        def connect(self): return Connection()
        def dispose(self): pass
    monkeypatch.setattr(guard, "create_engine", lambda *a, **k: Engine())
    with pytest.raises(BaseExceptionGroup): guard.drop_target_database(target)
    assert guard.owned_target_name(target) == "review_mm_catalog_0123456789ab"
    del guard._owned_targets[target]

@pytest.mark.parametrize("failure", ["exit", "dispose"])
def test_create_success_then_admin_teardown_failure_drops_owned_target(monkeypatch, failure):
    from app.tests import pg_approved_instance as guard
    _set_config(monkeypatch, APPROVED); instance = load_approved_instance(); calls=[]
    class Result:
        def one(self): return _Row(**{**LIVE.__dict__, "database": "postgres"})
    class Connection:
        def __init__(self, number): self.number=number
        def __enter__(self): return self
        def __exit__(self,*args):
            if self.number==0 and failure=='exit': raise RuntimeError('admin exit')
        def execute(self, statement): return Result()
        def exec_driver_sql(self, sql): calls.append(sql)
    class Engine:
        def __init__(self, number): self.number=number
        def connect(self): return Connection(self.number)
        def dispose(self):
            if self.number==0 and failure=='dispose': raise RuntimeError('admin dispose')
    engines=[]
    def make(*args,**kwargs):
        value=Engine(len(engines)); engines.append(value); return value
    monkeypatch.setattr(guard, 'create_engine', make)
    with pytest.raises(RuntimeError, match='admin'):
        guard.create_target_database(instance)
    assert len(calls)==2 and calls[0].startswith('CREATE DATABASE ') and calls[1]==calls[0].replace('CREATE','DROP',1)
    assert not guard._owned_targets


def test_failed_create_and_cleanup_report_both_and_keep_owned_name(monkeypatch):
    from app.tests import pg_approved_instance as guard
    _set_config(monkeypatch, APPROVED); instance = load_approved_instance()
    class Result:
        def one(self): return _Row(**{**LIVE.__dict__, 'database':'postgres'})
    class Connection:
        def __enter__(self): return self
        def __exit__(self,*args): raise RuntimeError('connection exit')
        def execute(self, statement): return Result()
        def exec_driver_sql(self, sql):
            if sql.startswith('DROP'): raise RuntimeError('drop refused')
    class Engine:
        def connect(self): return Connection()
        def dispose(self): pass
    monkeypatch.setattr(guard, 'create_engine', lambda *a, **k: Engine())
    with pytest.raises(BaseExceptionGroup) as caught: guard.create_target_database(instance)
    assert 'connection exit' in repr(caught.value) and 'drop refused' in repr(caught.value)
    target=next(iter(guard._owned_targets)); assert guard.owned_target_name(target).startswith(instance.target_prefix)
    del guard._owned_targets[target]


def test_uncertain_create_outcome_keeps_record_without_automatic_drop(monkeypatch):
    from app.tests import pg_approved_instance as guard
    _set_config(monkeypatch, APPROVED); instance = load_approved_instance(); calls=[]
    class Result:
        def one(self): return _Row(**{**LIVE.__dict__, 'database':'postgres'})
    class Connection:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def execute(self, statement): return Result()
        def exec_driver_sql(self, sql): calls.append(sql); raise RuntimeError('unknown create outcome')
    class Engine:
        def connect(self): return Connection()
        def dispose(self): pass
    monkeypatch.setattr(guard, 'create_engine', lambda *a, **k: Engine())
    with pytest.raises(BaseExceptionGroup) as caught: guard.create_target_database(instance)
    assert 'outcome uncertain' in repr(caught.value) and len(calls)==1
    target=next(iter(guard._pending_targets)); assert target in guard._owned_targets
    with pytest.raises(ApprovedInstanceUnavailable): guard.drop_target_database(target)
    guard._pending_targets.remove(target); del guard._owned_targets[target]


def test_dispose_failure_does_not_prevent_drop_and_preserves_setup_error(monkeypatch):
    from app.tests import pg_approved_instance as guard
    calls=[]
    class Engine:
        def dispose(self): calls.append('dispose'); raise RuntimeError('dispose failure')
    monkeypatch.setattr(guard, 'drop_target_database', lambda target: calls.append(('drop',target)))
    target=object()
    with pytest.raises(BaseExceptionGroup) as caught:
        try: raise ValueError('setup failure')
        finally: guard.finalize_target(target, Engine())
    assert calls==['dispose',('drop',target)]
    assert 'setup failure' in repr(caught.value) and 'dispose failure' in repr(caught.value)


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
