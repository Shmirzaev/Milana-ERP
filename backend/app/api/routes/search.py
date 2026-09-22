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
    combined = union_all(sales, bundles, models, customers).subquery()
    total = int(db.execute(select(func.count()).select_from(combined)).scalar() or 0)
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
    results: list[dict] = []
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

    sales_rows = (
        db.query(SalesOrder.id, SalesOrder.order_no, SalesOrder.customer_id, Customer.name)
        .outerjoin(Customer, Customer.id == SalesOrder.customer_id)
        .filter(order_reference_contains(SalesOrder.order_no, pattern) | sales_model_match)
        .order_by(SalesOrder.id.desc())
        .limit(limit)
        .all()
    )
    for sales_order_id, order_no, customer_id, customer_name_value in sales_rows:
        customer_name = customer_name_value or (f"Customer #{customer_id}" if customer_id else "No customer")
        results.append(
            {
                "type": "SalesOrder",
                "id": sales_order_id,
                "label": f"{order_no} - {customer_name}",
                "url": f"/sales-orders/{sales_order_id}",
            }
        )

    bundle_rows = (
        db.query(Bundle.id, Bundle.bundle_no, Bundle.barcode, Bundle.model_id, Model.code, Model.name)
        .outerjoin(Model, Model.id == Bundle.model_id)
        .filter(
            (Bundle.barcode.ilike(pattern))
            | order_reference_contains(Bundle.bundle_no, pattern)
            | (normalized_model_code_column(Model.code).ilike(model_code_pattern))
        )
        .order_by(Bundle.id.desc())
        .limit(limit)
        .all()
    )
    for bundle_id, bundle_no, barcode, model_id, model_code, model_name in bundle_rows:
        model_label = f"{model_code} - {model_name}" if model_code else f"Model #{model_id}"
        results.append(
            {
                "type": "Bundle",
                "id": bundle_id,
                "label": f"{bundle_no} - {barcode} - {model_label}",
                "url": f"/bundles/{bundle_id}",
            }
        )

    model_rows = (
        db.query(Model.id, Model.code, Model.name)
        .filter(Model.catalog_scope == "standard")
        .filter(
            (normalized_model_code_column(Model.code).ilike(model_code_pattern))
            | (Model.name.ilike(pattern))
        )
        .order_by(Model.id.desc())
        .limit(limit)
        .all()
    )
    for model_id, model_code, model_name in model_rows:
        results.append(
            {
                "type": "Model",
                "id": model_id,
                "label": f"{model_code} - {model_name}",
                "url": f"/models/{model_id}",
            }
        )

    customer_rows = (
        db.query(Customer.id, Customer.name)
        .filter(Customer.name.ilike(pattern))
        .order_by(Customer.id.desc())
        .limit(limit)
        .all()
    )
    for customer_id, customer_name in customer_rows:
        results.append(
            {
                "type": "Customer",
                "id": customer_id,
                "label": customer_name,
                "url": f"/customers?q={customer_name}",
            }
        )

    return results
