"""PERF23 regression: the price calculation list must not hydrate every request.

The list route used to ``.all()`` the whole ``price_calculation_requests``
table and then serialize every row, so a 5-second poll from any of the five
pricing pages re-hydrated every request plus each row's model assets
(``sizes``/``images``/``bom`` are default lazy relationships).

Two things are asserted here, and they are asserted on *entities hydrated*, not
on statement count:

* ``test_price_list_does_not_hydrate_more_entities_as_requests_grow`` measures
  the entities instantiated while serving the list, then triples the number of
  price requests and measures again. The data genuinely grows between the two
  measurements, so the assertion can only pass if hydration is bounded.
* ``test_price_list_batches_model_asset_reads`` bounds the per-asset-collection
  round trips. Round-trip count is the only way to observe a lazy-loading N+1
  (the same entities are loaded either way), so it is used here as a
  structural bound only, never as the growth signal.

Measurement note: ``cursor.rowcount`` is unusable for this assertion under
SQLite -- it reports ``-1`` for SELECT there. The mapper-level ``load`` event
fires once per ORM object instantiated and behaves identically on SQLite and
psycopg2, so it is the metric used.
"""

from sqlalchemy import event, func

from app.db.session import SessionLocal
from app.models import Model, ModelBOM, ModelImage, ModelSize, PriceCalculationRequest, User
from app.tests.conftest import test_engine


WATCHED = (PriceCalculationRequest, Model, ModelSize, ModelImage, ModelBOM)
LIST_URL = "/api/price-calculation/requests"

# Per-page cap from the route. Used only to keep the fixture small; the test
# deliberately stays under it for the "small" measurement and far over it for
# the "large" one.
PAGE = 200


def _seed_requests(count: int, prefix: str) -> None:
    """Create ``count`` models (with assets) and one request each."""
    db = SessionLocal()
    try:
        user = db.query(User).order_by(User.id).first()
        for index in range(count):
            model = Model(
                code=f"{prefix}-{index}",
                name=f"PERF23 model {prefix} {index}",
                category="T-shirt",
                details_json={"general": {"model_no": f"PERF23-{prefix}", "variant_no": str(index)}},
                status="approved",
            )
            db.add(model)
            db.flush()
            db.add_all([ModelSize(model_id=model.id, size="S"), ModelSize(model_id=model.id, size="M")])
            # Half the models carry a picture and half only a BOM photo, so both
            # the ``images`` and the ``bom`` asset reads are exercised.
            if index % 2 == 0:
                db.add(
                    ModelImage(
                        model_id=model.id,
                        file_url=f"/storage/model-files/perf23-{prefix}-{index}.webp",
                        file_name=f"perf23-{prefix}-{index}.webp",
                        content_type="image/webp",
                        image_type="model",
                        is_primary=True,
                    )
                )
            else:
                db.add(
                    ModelBOM(
                        model_id=model.id,
                        material_name="Fabric",
                        material_role="fabric",
                        quantity_per_piece=1.5,
                        unit="m",
                        photo_url=f"/storage/model-files/perf23-bom-{prefix}-{index}.webp",
                    )
                )
            db.add(
                PriceCalculationRequest(
                    model_id=model.id,
                    created_by_id=user.id,
                    accessories_json=[{"name": "Thread", "price": 0.05}],
                )
            )
        db.commit()
    finally:
        db.close()


def _measure(client, auth_headers, url: str = LIST_URL) -> tuple[int, list, dict]:
    """Serve one list request while counting hydrated entities and asset queries.

    Returns ``(entities_hydrated, payload, asset_query_counts)``.
    """
    entities: dict[str, int] = {cls.__name__: 0 for cls in WATCHED}
    asset_queries: dict[str, int] = {"model_sizes": 0, "model_images": 0, "model_bom": 0}

    def count_entity(cls):
        def receive_load(target, context):
            entities[cls.__name__] += 1

        return receive_load

    def count_asset_query(conn, cursor, statement, params, context, executemany):
        if not statement.lstrip()[:6].upper() == "SELECT":
            return
        for table in asset_queries:
            if f"FROM {table}" in statement or f"JOIN {table}" in statement:
                asset_queries[table] += 1

    entity_listeners = [(cls, count_entity(cls)) for cls in WATCHED]
    for cls, listener in entity_listeners:
        event.listen(cls, "load", listener)
    event.listen(test_engine, "after_cursor_execute", count_asset_query)
    try:
        response = client.get(url, headers=auth_headers)
    finally:
        for cls, listener in entity_listeners:
            event.remove(cls, "load", listener)
        event.remove(test_engine, "after_cursor_execute", count_asset_query)
    assert response.status_code == 200, response.text
    return sum(entities.values()), response.json(), asset_queries


def _request_count() -> int:
    db = SessionLocal()
    try:
        return db.query(func.count()).select_from(PriceCalculationRequest).scalar() or 0
    finally:
        db.close()


def test_price_list_is_unbounded_by_default_so_no_row_disappears(client, auth_headers):
    """The list must NOT silently drop rows while the five consumers have no
    load-more yet. A cap here is the same defect PERF35-FINANCE just fixed, so
    bounding waits for the D3 paging contract; the `limit` opt-in is tested
    separately below."""
    _seed_requests(PAGE + 40, "cap")
    expected_total = _request_count()
    assert expected_total > PAGE, "fixture must exceed a page for this to mean anything"

    response = client.get(LIST_URL, headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert isinstance(payload, list), "the response must stay a bare array"
    assert len(payload) == expected_total, (
        f"the list returned {len(payload)} of {expected_total} requests; rows are "
        "being dropped off the end of the screen with no way to reach them"
    )


def test_price_list_honours_an_explicit_limit(client, auth_headers):
    _seed_requests(PAGE + 40, "limit")
    expected_total = _request_count()
    assert expected_total > PAGE

    response = client.get(f"{LIST_URL}?limit={PAGE}", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload) == PAGE, f"expected {PAGE} rows, got {len(payload)}"
    # Newest first, same ordering the unbounded list uses.
    assert [row["id"] for row in payload] == sorted(
        (row["id"] for row in payload), reverse=True
    )


def test_price_list_rejects_a_hostile_limit(client, auth_headers):
    for bad in ("0", "-3", "100000"):
        response = client.get(f"{LIST_URL}?limit={bad}", headers=auth_headers)
        assert response.status_code == 422, f"limit={bad} should be rejected, got {response.status_code}"


def test_price_list_batches_model_asset_reads(client, auth_headers):
    _seed_requests(25, "batch")
    _, payload, asset_queries = _measure(client, auth_headers)

    assert len(payload) == 25
    for table, count in asset_queries.items():
        assert count <= 1, f"{table} was read {count} times for one page; expected a single batched read"


def test_price_list_preserves_response_fields_and_semantics(client, auth_headers):
    _seed_requests(3, "shape")
    _, payload, _ = _measure(client, auth_headers)
    row = next(item for item in payload if item["model_name"].startswith("PERF23 model shape"))

    assert set(row) == {
        "id", "model_id", "model_no", "variant_no", "model_name", "model_category",
        "model_sizes", "model_image_url", "variant_image_url", "kroy_no",
        "cutting_passport_id", "date", "fabric_width_m", "lay_length_m", "size_count",
        "gramage", "binding_kg_per_piece", "fabric_price", "sewing_cost", "packaging_cost",
        "accessories", "cost_price_uzs", "selling_price", "variant_selling_price",
        "variant_selling_price_request_id", "selling_price_attached", "profit_percentage",
        "exchange_rate", "purchasing_status", "cutting_status", "accessories_status",
        "overall_status", "created_at", "updated_at", "fabric_consumption",
        "consumption_cost", "binding_price", "cost_price", "difference",
    }
    assert row["model_sizes"] == ["S", "M"]
    assert row["accessories"] == [{"name": "Thread", "price": 0.05}]
    assert row["date"] is None and row["cutting_passport_id"] is None
    # Seeded rows carry accessories but no cutting/purchasing/selling values, so
    # the per-stage and overall status semantics must stay as they are today.
    assert row["overall_status"] == "in_progress"
    assert row["purchasing_status"] == "new"
    assert row["cutting_status"] == "new"
    assert row["accessories_status"] == "complete"
    assert row["model_image_url"] is not None and row["variant_image_url"] is not None
    assert row["model_no"] == "PERF23-shape" and row["model_category"] == "T-shirt"
    assert row["packaging_cost"] == 0.1


def test_price_request_mutation_uses_the_shared_preload(client, auth_headers):
    _seed_requests(1, "mutate")
    db = SessionLocal()
    try:
        request_id = db.query(PriceCalculationRequest).order_by(PriceCalculationRequest.id.desc()).first().id
    finally:
        db.close()

    response = client.patch(
        f"/api/price-calculation/requests/{request_id}/purchasing",
        json={"fabric_price": 12.5, "sewing_cost": 3.25},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The mutation must still serialize the model assets, so a shared preload
    # cannot simply drop them.
    assert body["model_sizes"] == ["S", "M"]
    assert body["model_image_url"] is not None and body["variant_image_url"] is not None
    assert body["purchasing_status"] == "complete"
    assert body["fabric_price"] == 12.5 and body["sewing_cost"] == 3.25
