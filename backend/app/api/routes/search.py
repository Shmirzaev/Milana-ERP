from typing import Annotated

from app.core.order_reference import order_reference_contains
from fastapi import APIRouter, Query
from sqlalchemy import func, literal, select, union_all

from app.core.deps import DbSession, CurrentUser
from app.core.model_search import normalized_model_code_column, normalized_model_code_pattern
from app.models import SalesOrder, SalesOrderItem, Bundle, Model, Customer
from app.schemas.search import SearchPageOut, SearchResultOut

router = APIRouter(tags=["search"])


def _paged_search(db, *, pattern: str, model_code_pattern: str, sales_model_match, page: int, page_size: int):
    sales = select(
        literal("SalesOrder").label("type"),
        literal(0).label("type_rank"),
        SalesOrder.id.label("id"),
        SalesOrder.order_no.label("value1"),
        Customer.name.label("value2"),
        literal(None).label("value3"),
        literal(None).label("value4"),
        SalesOrder.customer_id.label("related_id"),
    ).select_from(SalesOrder).outerjoin(
        Customer,
        Customer.id == SalesOrder.customer_id,
    ).where(order_reference_contains(SalesOrder.order_no, pattern) | sales_model_match)
    bundles = select(
        literal("Bundle").label("type"),
        literal(1).label("type_rank"),
        Bundle.id.label("id"),
        Bundle.bundle_no.label("value1"),
        Bundle.barcode.label("value2"),
        Model.code.label("value3"),
        Model.name.label("value4"),
        Bundle.model_id.label("related_id"),
    ).select_from(Bundle).outerjoin(
        Model,
        Model.id == Bundle.model_id,
    ).where(
        Bundle.barcode.ilike(pattern)
        | order_reference_contains(Bundle.bundle_no, pattern)
        | normalized_model_code_column(Model.code).ilike(model_code_pattern)
    )
    models = select(
        literal("Model").label("type"),
        literal(2).label("type_rank"),
        Model.id.label("id"),
        Model.code.label("value1"),
        Model.name.label("value2"),
        literal(None).label("value3"),
        literal(None).label("value4"),
        literal(None).label("related_id"),
    ).where(
        Model.catalog_scope == "standard",
        normalized_model_code_column(Model.code).ilike(model_code_pattern) | Model.name.ilike(pattern),
    )
    customers = select(
        literal("Customer").label("type"),
        literal(3).label("type_rank"),
        Customer.id.label("id"),
        Customer.name.label("value1"),
        literal(None).label("value2"),
        literal(None).label("value3"),
        literal(None).label("value4"),
        literal(None).label("related_id"),
    ).where(Customer.name.ilike(pattern))
    sales_matches = select(SalesOrder.id.label("id")).where(
        order_reference_contains(SalesOrder.order_no, pattern) | sales_model_match
    )
    bundle_matches = select(Bundle.id.label("id")).select_from(Bundle).outerjoin(
        Model,
        Model.id == Bundle.model_id,
    ).where(
        Bundle.barcode.ilike(pattern)
        | order_reference_contains(Bundle.bundle_no, pattern)
        | normalized_model_code_column(Model.code).ilike(model_code_pattern)
    )
    model_matches = select(Model.id.label("id")).where(
        Model.catalog_scope == "standard",
        normalized_model_code_column(Model.code).ilike(model_code_pattern) | Model.name.ilike(pattern),
    )
    customer_matches = select(Customer.id.label("id")).where(Customer.name.ilike(pattern))
    combined = union_all(sales, bundles, models, customers).subquery()
    count_matches = union_all(
        sales_matches,
        bundle_matches,
        model_matches,
        customer_matches,
    ).subquery()
    total = int(db.execute(select(func.count()).select_from(count_matches)).scalar() or 0)
    rows = db.execute(
        select(combined)
        .order_by(combined.c.type_rank.asc(), combined.c.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).mappings().all()
    results = []
    for row in rows:
        if row["type"] == "SalesOrder":
            customer_name = row["value2"] or (
                f"Customer #{row['related_id']}" if row["related_id"] else "No customer"
            )
            label = f"{row['value1']} - {customer_name}"
            url = f"/sales-orders/{row['id']}"
        elif row["type"] == "Bundle":
            model_label = (
                f"{row['value3']} - {row['value4']}"
                if row["value3"]
                else f"Model #{row['related_id']}"
            )
            label = f"{row['value1']} - {row['value2']} - {model_label}"
            url = f"/bundles/{row['id']}"
        elif row["type"] == "Model":
            label = f"{row['value1']} - {row['value2']}"
            url = f"/models/{row['id']}"
        else:
            label = row["value1"]
            url = f"/customers?q={row['value1']}"
        results.append({"type": row["type"], "id": row["id"], "label": label, "url": url})
    return {
        "rows": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.get("/search", response_model=list[SearchResultOut] | SearchPageOut)
def global_search(
    q: str,
    db: DbSession,
    _: CurrentUser,
    limit_per_type: int = 100,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=200)] = None,
):
    """Search key entities and return a unified list with direct URLs."""
    query = (q or "").strip()
    paginated = page is not None or page_size is not None
    effective_page = page or 1
    effective_page_size = page_size or max(1, min(int(limit_per_type or 100), 200))
    if not query:
        if paginated:
            return {
                "rows": [],
                "total": 0,
                "page": effective_page,
                "page_size": effective_page_size,
                "has_more": False,
            }
        return []

    limit = max(1, min(int(limit_per_type or 100), 200))
    pattern = f"%{query}%"
    model_code_pattern = normalized_model_code_pattern(query)
    sales_model_match = (
        db.query(SalesOrderItem.id)
        .join(Model, Model.id == SalesOrderItem.model_id)
        .filter(
            SalesOrderItem.sales_order_id == SalesOrder.id,
            (
                normalized_model_code_column(Model.code).ilike(model_code_pattern)
                | Model.name.ilike(pattern)
            ),
        )
        .exists()
    )
    if paginated:
        return _paged_search(
            db,
            pattern=pattern,
            model_code_pattern=model_code_pattern,
            sales_model_match=sales_model_match,
            page=effective_page,
            page_size=effective_page_size,
        )

    sales = select(
        literal("SalesOrder").label("type"),
        literal(0).label("type_rank"),
        SalesOrder.id.label("id"),
        SalesOrder.order_no.label("value1"),
        Customer.name.label("value2"),
        literal(None).label("value3"),
        literal(None).label("value4"),
        SalesOrder.customer_id.label("related_id"),
    ).select_from(SalesOrder).outerjoin(
        Customer, Customer.id == SalesOrder.customer_id,
    ).where(order_reference_contains(SalesOrder.order_no, pattern) | sales_model_match)
    bundles = select(
        literal("Bundle").label("type"),
        literal(1).label("type_rank"),
        Bundle.id.label("id"),
        Bundle.bundle_no.label("value1"),
        Bundle.barcode.label("value2"),
        Model.code.label("value3"),
        Model.name.label("value4"),
        Bundle.model_id.label("related_id"),
    ).select_from(Bundle).outerjoin(
        Model, Model.id == Bundle.model_id,
    ).where(
        Bundle.barcode.ilike(pattern)
        | order_reference_contains(Bundle.bundle_no, pattern)
        | normalized_model_code_column(Model.code).ilike(model_code_pattern)
    )
    models = select(
        literal("Model").label("type"),
        literal(2).label("type_rank"),
        Model.id.label("id"),
        Model.code.label("value1"),
        Model.name.label("value2"),
        literal(None).label("value3"),
        literal(None).label("value4"),
        literal(None).label("related_id"),
    ).where(
        Model.catalog_scope == "standard",
        normalized_model_code_column(Model.code).ilike(model_code_pattern) | Model.name.ilike(pattern),
    )
    customers = select(
        literal("Customer").label("type"),
        literal(3).label("type_rank"),
        Customer.id.label("id"),
        Customer.name.label("value1"),
        literal(None).label("value2"),
        literal(None).label("value3"),
        literal(None).label("value4"),
        literal(None).label("related_id"),
    ).where(Customer.name.ilike(pattern))
    combined = union_all(sales, bundles, models, customers).subquery()
    ranked = select(
        combined,
        func.row_number().over(
            partition_by=combined.c.type_rank,
            order_by=combined.c.id.desc(),
        ).label("type_row_number"),
    ).subquery()
    rows = db.execute(
        select(ranked)
        .where(ranked.c.type_row_number <= limit)
        .order_by(ranked.c.type_rank.asc(), ranked.c.id.desc())
    ).mappings().all()
    results = []
    for row in rows:
        if row["type"] == "SalesOrder":
            customer_name = row["value2"] or (
                f"Customer #{row['related_id']}" if row["related_id"] else "No customer"
            )
            label = f"{row['value1']} - {customer_name}"
            url = f"/sales-orders/{row['id']}"
        elif row["type"] == "Bundle":
            model_label = (
                f"{row['value3']} - {row['value4']}"
                if row["value3"]
                else f"Model #{row['related_id']}"
            )
            label = f"{row['value1']} - {row['value2']} - {model_label}"
            url = f"/bundles/{row['id']}"
        elif row["type"] == "Model":
            label = f"{row['value1']} - {row['value2']}"
            url = f"/models/{row['id']}"
        else:
            label = row["value1"]
            url = f"/customers?q={row['value1']}"
        results.append({"type": row["type"], "id": row["id"], "label": label, "url": url})
    return results
