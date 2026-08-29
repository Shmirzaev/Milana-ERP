from fastapi import APIRouter

from app.core.deps import DbSession, CurrentUser
from app.core.model_search import normalized_model_code_column, normalized_model_code_pattern
from app.models import SalesOrder, SalesOrderItem, Bundle, Model, Customer

router = APIRouter(tags=["search"])


@router.get("/search")
def global_search(
    q: str,
    db: DbSession,
    _: CurrentUser,
    limit_per_type: int = 100,
):
    """Search key entities and return a unified list with direct URLs."""
    query = (q or "").strip()
    if not query:
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

    sales_rows = (
        db.query(SalesOrder.id, SalesOrder.order_no, SalesOrder.customer_id, Customer.name)
        .outerjoin(Customer, Customer.id == SalesOrder.customer_id)
        .filter(SalesOrder.order_no.ilike(pattern) | sales_model_match)
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
            | (Bundle.bundle_no.ilike(pattern))
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
