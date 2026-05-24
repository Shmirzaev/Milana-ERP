from fastapi import APIRouter

from app.core.deps import DbSession, CurrentUser
from app.models import SalesOrder, Bundle, Model, Customer

router = APIRouter(tags=["search"])


@router.get("/search")
def global_search(
    q: str,
    db: DbSession,
    _: CurrentUser,
    limit_per_type: int = 5,
):
    """Search key entities and return a unified list with direct URLs."""
    query = (q or "").strip()
    if not query:
        return []

    limit = max(1, min(int(limit_per_type or 5), 25))
    pattern = f"%{query}%"
    results: list[dict] = []

    sales_rows = (
        db.query(SalesOrder, Customer)
        .outerjoin(Customer, Customer.id == SalesOrder.customer_id)
        .filter(SalesOrder.order_no.ilike(pattern))
        .order_by(SalesOrder.id.desc())
        .limit(limit)
        .all()
    )
    for so, customer in sales_rows:
        customer_name = customer.name if customer else (f"Customer #{so.customer_id}" if so.customer_id else "No customer")
        results.append(
            {
                "type": "SalesOrder",
                "id": so.id,
                "label": f"{so.order_no} - {customer_name}",
                "url": f"/sales-orders/{so.id}",
            }
        )

    bundle_rows = (
        db.query(Bundle, Model)
        .outerjoin(Model, Model.id == Bundle.model_id)
        .filter((Bundle.barcode.ilike(pattern)) | (Bundle.bundle_no.ilike(pattern)))
        .order_by(Bundle.id.desc())
        .limit(limit)
        .all()
    )
    for bundle, model in bundle_rows:
        model_label = f"{model.code} - {model.name}" if model else f"Model #{bundle.model_id}"
        results.append(
            {
                "type": "Bundle",
                "id": bundle.id,
                "label": f"{bundle.bundle_no} - {bundle.barcode} - {model_label}",
                "url": f"/bundles/{bundle.id}",
            }
        )

    model_rows = (
        db.query(Model)
        .filter((Model.code.ilike(pattern)) | (Model.name.ilike(pattern)))
        .order_by(Model.id.desc())
        .limit(limit)
        .all()
    )
    for model in model_rows:
        results.append(
            {
                "type": "Model",
                "id": model.id,
                "label": f"{model.code} - {model.name}",
                "url": f"/models/{model.id}",
            }
        )

    customer_rows = (
        db.query(Customer)
        .filter(Customer.name.ilike(pattern))
        .order_by(Customer.id.desc())
        .limit(limit)
        .all()
    )
    for customer in customer_rows:
        results.append(
            {
                "type": "Customer",
                "id": customer.id,
                "label": customer.name,
                "url": f"/customers?q={customer.name}",
            }
        )

    return results
