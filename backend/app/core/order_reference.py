"""Read-only matching of compact order labels against preserved legacy references."""
import re

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.models.order_reference import BusinessOrderAlias


def _entity(namespace):
    from app.models import Bundle, SalesOrder, ProductionOrder, PurchaseRequest, PurchaseOrder
    entities = {"SO": (SalesOrder, "order_no"), "PO": (ProductionOrder, "production_no"),
                "USL": (ProductionOrder, "production_no"), "PR": (PurchaseRequest, "request_no"),
                "PUR": (PurchaseOrder, "po_no"), "PUBLIC_PO": (ProductionOrder, "production_no"),
                "BND": (Bundle, "bundle_no")}
    if namespace not in entities:
        raise ValueError("Unknown order-reference namespace")
    return entities[namespace]


def _find_order(db, namespace, reference=None, entity_id=None, *, lookup=None):
    model, attr = _entity(namespace)
    query = None
    if lookup is None:
        query = db.query(model)
        if namespace == "USL":
            query = query.filter(model.source_type == "usluga")
    if entity_id is not None:
        return lookup.by_id(namespace, entity_id) if lookup is not None else query.filter(model.id == entity_id).first()
    text = str(reference or "").strip()
    if not text:
        return None
    direct = lookup.by_reference(namespace, text) if lookup is not None else query.filter(getattr(model, attr) == text).first()
    if direct:
        return direct
    namespaces = ["PO", "USL", "PUBLIC_PO"] if namespace == "PO" else [namespace]
    aliases = (lookup.aliases(namespaces, text) if lookup is not None else
               db.query(BusinessOrderAlias).filter(BusinessOrderAlias.namespace.in_(namespaces),
                                                   BusinessOrderAlias.reference == text).all())
    ids = {alias.entity_id for alias in aliases}
    if len(ids) > 1:
        raise HTTPException(409, "Ambiguous historical production reference; provide the production order ID")
    if not ids:
        return None
    entity_id = next(iter(ids))
    return lookup.by_id(namespace, entity_id) if lookup is not None else query.filter(model.id == entity_id).first()


def resolve_order_id(db, namespace: str, reference: str | None, *, lookup=None) -> int | None:
    """Resolve only the requested entity type; public factory SO labels are not sales."""
    if namespace == "PUBLIC_PO":
        raise ValueError("Public order labels do not identify sales records")
    row = _find_order(db, namespace, reference, lookup=lookup)
    return row.id if row else None


def _public_order(db, reference, production_order_id=None, *, lookup=None):
    from app.models import ProductionOrder
    if production_order_id is not None:
        return lookup.by_id("PO", production_order_id) if lookup is not None else db.get(ProductionOrder, production_order_id)
    alias = (next(iter(lookup.aliases(["PUBLIC_PO"], reference)), None) if lookup is not None else
             db.query(BusinessOrderAlias).filter(BusinessOrderAlias.namespace == "PUBLIC_PO",
                                                 BusinessOrderAlias.reference == reference).first())
    if alias:
        return lookup.by_id("PO", alias.entity_id) if lookup is not None else db.get(ProductionOrder, alias.entity_id)
    # Historical sales_order_no fields can now contain the real standalone PO.
    if re.fullmatch(r"(?:PO|USL)-[0-9]{4}", str(reference or "")):
        if lookup is not None:
            row = lookup.by_reference("PO", reference)
            return row if row is not None and row.sales_order_id is None else None
        return db.query(ProductionOrder).filter(ProductionOrder.production_no == reference,
                                                ProductionOrder.sales_order_id.is_(None)).first()
    return None


def canonical_order_reference(db, namespace: str, reference: str | None, *,
                              entity_id: int | None = None, production_order_id: int | None = None,
                              lookup=None) -> str | None:
    """Canonicalize known references, retaining manual/unresolved text unchanged.

    An optional request-scoped lookup supplies complete by_id, by_reference and
    aliases reads; it does not replace the identity/ambiguity rules below.
    """
    from app.models import public_production_order_no
    row = _find_order(db, namespace, reference, entity_id, lookup=lookup)
    if namespace == "SO" and entity_id is None:
        public = _public_order(db, reference, production_order_id, lookup=lookup)
        if public is not None:
            if production_order_id is not None:
                return public.order_no
            if row is not None and row.id != public.sales_order_id:
                raise HTTPException(409, "Ambiguous sales/factory order reference; provide the production order ID")
            if row is None:
                return public_production_order_no(public.production_no)
    if row is None:
        return reference
    return str(getattr(row, _entity(namespace)[1]))


def order_reference_variants(db, namespace: str, reference: str | None, *,
                             entity_id: int | None = None, production_order_id: int | None = None,
                             lookup=None) -> set[str]:
    canonical = canonical_order_reference(db, namespace, reference, entity_id=entity_id,
                                          production_order_id=production_order_id, lookup=lookup)
    row = _find_order(db, namespace, reference, entity_id, lookup=lookup)
    alias_namespaces = ["PO", "USL", "PUBLIC_PO"] if namespace == "PO" else [namespace]
    if namespace == "SO" and entity_id is None:
        public = _public_order(db, reference, production_order_id, lookup=lookup)
        if public is not None and (production_order_id is not None or row is None):
            if public.sales_order_id:
                row = public.sales_order
                alias_namespaces = ["SO"]
            else:
                row = public
                alias_namespaces = ["PUBLIC_PO"]
    values = {str(canonical)} if canonical else set()
    if row is not None:
        if lookup is not None:
            values.update(lookup.alias_references(alias_namespaces, row.id))
        else:
            values.update(value for (value,) in db.query(BusinessOrderAlias.reference).filter(
                BusinessOrderAlias.namespace.in_(alias_namespaces), BusinessOrderAlias.entity_id == row.id).all())
    elif reference:
        values.add(reference)
    return values


def order_reference_contains(column, pattern: str):
    normal_match = column.ilike(pattern)
    table = getattr(getattr(column, "table", None), "name", "")
    name = getattr(column, "key", "")
    namespaces = {
        "sales_orders": ["SO"], "production_orders": ["PO", "USL", "PUBLIC_PO"],
        "purchase_requests": ["PR"], "purchase_orders": ["PUR"], "bundles": ["BND"],
    }.get(table)
    if namespaces is None:
        namespaces = ["PO", "USL"] if name == "production_no" else ["SO", "PUBLIC_PO"] if name == "sales_order_no" else ["SO", "PO", "USL", "PR", "PUR", "PUBLIC_PO"]
    value = BusinessOrderAlias.canonical_reference
    alias_query = select(value).where(BusinessOrderAlias.namespace.in_(namespaces), BusinessOrderAlias.reference.ilike(pattern))
    return or_(normal_match, column.in_(alias_query))


def canonical_business_order_reference(db, reference: str | None) -> str | None:
    """Resolve generic order fields; unknown supplier/customer references stay intact."""
    if not reference:
        return reference
    prefix = re.match(r"^(SO|PO|USL|PR|PUR)-", reference)
    if prefix:
        return canonical_order_reference(db, prefix[1], reference)
    aliases = db.query(BusinessOrderAlias).filter(BusinessOrderAlias.reference == reference).all()
    identities = {(row.namespace if row.namespace not in {"PO", "USL", "PUBLIC_PO"} else "PO", row.entity_id) for row in aliases}
    if len(identities) > 1:
        raise HTTPException(409, "Ambiguous historical order reference; select its linked order")
    if not aliases:
        return reference
    public = next((row for row in aliases if row.namespace == "PUBLIC_PO"), None)
    if public:
        return canonical_order_reference(db, "SO", reference, production_order_id=public.entity_id)
    row = aliases[0]
    return canonical_order_reference(db, row.namespace, reference, entity_id=row.entity_id)
