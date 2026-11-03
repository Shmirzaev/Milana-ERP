"""Cycle 3 characterization against the existing scoped lookup and create entrypoint."""
import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.libs.dto.catalog.model_size_input import ModelSizeIn
from app.libs.enums.catalog import CatalogScope
from app.models.catalog import models_service as service
from app.schemas import ModelSize, User
from app.tests.conftest import TestSessionLocal
from app.tests.test_modelsize_create_operation import size_case  # noqa: F401


def capture_sql(db):
    connection = db.connection()
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))
    event.listen(connection, 'before_cursor_execute', capture)
    return statements


def model_selects(statements):
    return [(sql, params) for sql, params in statements
            if sql.lstrip().upper().startswith('SELECT') and 'FROM models' in sql]


@pytest.mark.parametrize(('value', 'expected'), [
    (None, 'standard'), (0, 'standard'), ('', 'standard'),
    (' StAnDaRd ', 'standard'), (' USLUGA ', 'usluga'),
    ('standard', 'standard'), ('usluga', 'usluga'),
])
def test_wrapper_executes_one_scoped_query_on_supplied_session(size_case, value, expected):
    with TestSessionLocal() as db:
        statements = capture_sql(db)
        mid = size_case['models'][expected]
        result = service._catalog_model(db, mid, value)
        assert result is not None and result.id == mid
        queries = model_selects(statements)
        assert len(statements) == len(queries) == 1
        assert queries[0][1] == (mid, expected)
        assert result in db


@pytest.mark.parametrize('value', [' ', 'other', 'standard\u200b', CatalogScope.STANDARD, CatalogScope.USLUGA])
def test_wrapper_invalid_executes_no_sql(size_case, value):
    with TestSessionLocal() as db:
        statements = capture_sql(db)
        with pytest.raises(HTTPException) as exc:
            service._catalog_model(db, size_case['models']['standard'], value)
        assert (exc.value.status_code, exc.value.detail) == (400, 'Invalid model catalog scope')
        assert statements == []


@pytest.mark.parametrize(('model', 'scope'), [('standard', 'usluga'), ('usluga', 'standard')])
def test_wrapper_wrong_scope_returns_none(size_case, model, scope):
    with TestSessionLocal() as db:
        statements = capture_sql(db)
        mid = size_case['models'][model]
        assert service._catalog_model(db, mid, scope) is None
        assert len(statements) == 1 and model_selects(statements)[0][1] == (mid, scope)


@pytest.mark.parametrize(('scope', 'model', 'bound'), [
    (None, 'standard', 'standard'), (0, 'standard', 'standard'),
    ('', 'standard', 'standard'), (' StAnDaRd ', 'standard', 'standard'),
    (' USLUGA ', 'usluga', 'usluga'),
])
def test_direct_add_size_legacy_inputs_query_and_persist(size_case, scope, model, bound):
    with TestSessionLocal() as db:
        actor = db.get(User, size_case['actors']['standard'])
        statements = capture_sql(db)
        mid = size_case['models'][model]
        result = service.add_size(actor, db, mid, ModelSizeIn(size='cycle3'), scope)
        queries = model_selects(statements)
        assert len(queries) == 1 and queries[0][1] == (mid, bound)
        assert db.get(ModelSize, result['id']).model_id == mid


@pytest.mark.parametrize('scope', [' ', 'other', 'standard\u200b'])
def test_direct_add_size_invalid_executes_no_sql(size_case, scope):
    with TestSessionLocal() as db:
        actor = db.get(User, size_case['actors']['standard'])
        statements = capture_sql(db)
        with pytest.raises(HTTPException) as exc:
            service.add_size(actor, db, size_case['models']['standard'], ModelSizeIn(size='M'), scope)
        assert (exc.value.status_code, exc.value.detail) == (400, 'Invalid model catalog scope')
        assert statements == []


def test_direct_add_size_wrong_scope_404_before_write(size_case):
    with TestSessionLocal() as db:
        actor = db.get(User, size_case['actors']['standard'])
        statements = capture_sql(db)
        mid = size_case['models']['standard']
        with pytest.raises(HTTPException) as exc:
            service.add_size(actor, db, mid, ModelSizeIn(size='M'), 'usluga')
        assert (exc.value.status_code, exc.value.detail) == (404, 'Model not found')
        assert len(statements) == 1 and model_selects(statements)[0][1] == (mid, 'usluga')


@pytest.mark.parametrize(('entry', 'scope', 'model', 'expected'), [
    ('wrapper', ' StAnDaRd ', 'standard', 'STANDARD'),
    ('wrapper', ' USLUGA ', 'usluga', 'USLUGA'),
    ('create', ' StAnDaRd ', 'standard', 'STANDARD'),
    ('create', ' USLUGA ', 'usluga', 'USLUGA'),
])
def test_real_query_receives_canonical_enum(size_case, monkeypatch, entry, scope, model, expected):
    original = service._catalog_model_for_scope
    calls = []
    def inspect(session, model_id, actual_scope):
        assert session is db
        assert actual_scope is getattr(CatalogScope, expected)
        calls.append(actual_scope)
        return original(session, model_id, actual_scope)
    monkeypatch.setattr(service, '_catalog_model_for_scope', inspect)
    with TestSessionLocal() as db:
        mid = size_case['models'][model]
        if entry == 'wrapper':
            assert service._catalog_model(db, mid, scope).id == mid
        else:
            actor = db.get(User, size_case['actors']['standard'])
            assert service.add_size(actor, db, mid, ModelSizeIn(size='M'), scope)['id']
        assert calls == [getattr(CatalogScope, expected)]
