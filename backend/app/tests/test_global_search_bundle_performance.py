import pytest

from app.api.routes.search import global_search
from app.core.model_search import normalized_model_code_key
from app.schemas import Bundle, Model, ProductionOrder
from app.schemas.order_reference import BusinessOrderAlias


@pytest.fixture
def search_bundles():
    from app.db import session as session_module

    with session_module.SessionLocal() as db:
        model = Model(code="РJ99123-009911", name="Search fixture")
        service = Model(code="PJ99123-V-009912", name="Service fixture",
                        catalog_scope="usluga", factory_code="ECO")
        other = Model(code="OTHER-SEARCH", name="PJ99123 name only")
        db.add_all([model, service, other])
        db.flush()
        order = ProductionOrder(production_no="PO-SEARCH-PERF", model_id=model.id,
                                production_type="branded_stock", planned_quantity=1000)
        db.add(order)
        db.flush()
        bundles = [Bundle(bundle_no=f"BND-SP-{i}", barcode=f"BAR-SP-{i}",
                          production_order_id=order.id, model_id=model_id,
                          color="White", size="122", quantity=1)
                   for i, model_id in enumerate([model.id, model.id, service.id, other.id])]
        db.add_all(bundles)
        db.flush()
        db.add(BusinessOrderAlias(namespace="BND", entity_id=bundles[0].id,
                                  reference="HISTORIC-SP", canonical_reference=bundles[0].bundle_no))
        db.commit()
        yield db, bundles, other.id


@pytest.mark.parametrize("query,indices", [
    ("PJ99123", [2, 1, 0]),
    ("РJ99123-V-009911", [1, 0]),
    ("V=009912", [2]),
    ("BAR-SP-3", [3]),
    ("BND-SP-2", [2]),
    ("HISTORIC-SP", [0]),
    ("BND-SP-%", [3, 2, 1, 0]),
    ("BND-SP-_", [3, 2, 1, 0]),
    ("missing-search-code", []),
])
@pytest.mark.parametrize("limit", [1, 2, 100])
def test_bundle_search_keeps_matches_order_and_limit(client, auth_headers, search_bundles, query, indices, limit):
    _, bundles, _ = search_bundles
    response = client.get("/api/search", params={"q": query, "limit_per_type": limit}, headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = [row for row in response.json() if row["type"] == "Bundle"]
    assert [row["id"] for row in rows] == [bundles[i].id for i in indices[:limit]]
    for row in rows:
        bundle = next(bundle for bundle in bundles if bundle.id == row["id"])
        assert row["label"].startswith(f"{bundle.bundle_no} - {bundle.barcode} - ")
        assert row["url"] == f"/bundles/{bundle.id}"
    assert bundles[2].model_id not in {row["id"] for row in response.json() if row["type"] == "Model"}


def test_model_normalization_work_does_not_grow_with_bundle_count(search_bundles):
    db, bundles, other_id = search_bundles
    calls = []
    connection = db.connection().connection.driver_connection
    connection.create_function("model_code_normalize", 1,
                               lambda value: calls.append(value) or normalized_model_code_key(value),
                               deterministic=True)
    try:
        before = global_search("PJ99123", db, None)
        baseline_calls = len(calls)
        db.add_all([Bundle(bundle_no=f"UNRELATED-SP-{i}", barcode=f"UNRELATED-BAR-SP-{i}",
                           production_order_id=bundles[0].production_order_id, model_id=other_id,
                           color="White", size="122", quantity=1) for i in range(600)])
        db.flush()
        calls.clear()
        after = global_search("PJ99123", db, None)
        assert after == before
        assert len(calls) == baseline_calls, "Bundle growth must not repeat model-code normalization"
    finally:
        connection.create_function("model_code_normalize", 1, normalized_model_code_key, deterministic=True)


def test_global_search_still_requires_authentication(client):
    assert client.get("/api/search", params={"q": "PJ99123"}).status_code == 401
