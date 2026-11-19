"""Deletion scope typing retains raw direct-call compatibility and refusal order."""
from typing import get_type_hints

import pytest
from fastapi import HTTPException

from app.api.routes import catalog
from app.libs.enums.catalog import CatalogScope
from app.models.catalog import models_service


@pytest.mark.parametrize(('raw', 'expected'), [
    ('', CatalogScope.STANDARD), (' STANDARD ', CatalogScope.STANDARD),
    ('UsLuGa', CatalogScope.USLUGA), (CatalogScope.STANDARD, CatalogScope.STANDARD),
    (CatalogScope.USLUGA, CatalogScope.USLUGA),
])
def test_delete_scope_normalizes_before_typed_lookup(monkeypatch, raw, expected):
    seen = []
    def missing(db, mid, scope):
        seen.append((mid, scope))
        return None
    monkeypatch.setattr(models_service, '_catalog_model_for_scope', missing)
    with pytest.raises(HTTPException) as exc:
        models_service.delete_model(None, object(), 123, raw)
    assert exc.value.status_code == 404
    assert seen == [(123, expected)] and seen[0][1] is expected


def test_delete_invalid_scope_refuses_before_lookup(monkeypatch):
    def forbidden(*args):
        pytest.fail('invalid scope must refuse before model lookup or mutation')
    monkeypatch.setattr(models_service, '_catalog_model_for_scope', forbidden)
    with pytest.raises(HTTPException) as exc:
        models_service.delete_model(None, object(), 123, 'invalid')
    assert exc.value.status_code == 400


def test_delete_scope_service_and_route_use_canonical_type():
    assert get_type_hints(models_service.delete_model)['catalog_scope'] is CatalogScope
    assert get_type_hints(catalog.delete_model)['catalog_scope'] is CatalogScope
    assert catalog._typed_standard_catalog_scope() is CatalogScope.STANDARD
