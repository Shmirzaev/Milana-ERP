from uuid import uuid4

from sqlalchemy import event

from app.models import Brand, Collection, CollectionModel, Model
from app.services.finished_goods import _model_collection_metadata
from app.tests.conftest import TestSessionLocal


def test_model_collection_metadata_aggregates_link_rows_and_preserves_ambiguity():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        shared_brand = Brand(name=f"PERF35 aggregate brand {marker}")
        other_brand = Brand(name=f"PERF35 aggregate other brand {marker}")
        same_brand_model = Model(
            code=f"PERF35-AGG-SAME-{marker}", name="Same-brand model", status="approved"
        )
        mixed_brand_model = Model(
            code=f"PERF35-AGG-MIXED-{marker}", name="Mixed-brand model", status="approved"
        )
        db.add_all([shared_brand, other_brand, same_brand_model, mixed_brand_model])
        db.flush()
        collections = [
            Collection(brand_id=shared_brand.id, name=f"PERF35 A {marker}", year=2026),
            Collection(brand_id=shared_brand.id, name=f"PERF35 B {marker}", year=2026),
            Collection(brand_id=other_brand.id, name=f"PERF35 C {marker}", year=2026),
        ]
        db.add_all(collections)
        db.flush()
        db.add_all([
            CollectionModel(model_id=same_brand_model.id, collection_id=collections[0].id),
            CollectionModel(model_id=same_brand_model.id, collection_id=collections[1].id),
            CollectionModel(model_id=mixed_brand_model.id, collection_id=collections[0].id),
            CollectionModel(model_id=mixed_brand_model.id, collection_id=collections[2].id),
        ])
        db.flush()

        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from collection_models " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            same_brand = _model_collection_metadata(db, model_id=int(same_brand_model.id))
            mixed_brand = _model_collection_metadata(db, model_id=int(mixed_brand_model.id))
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert same_brand.brand_id == int(shared_brand.id)
        assert same_brand.collection_id is None
        assert mixed_brand.brand_id is None
        assert mixed_brand.collection_id is None

    assert len(statements) == 2
    assert all("count(distinct(collection_models.collection_id))" in statement for statement in statements)
    assert all("count(distinct(collections.brand_id))" in statement for statement in statements)
    assert all("collection_models.collection_id, collections.brand_id" not in statement for statement in statements)
