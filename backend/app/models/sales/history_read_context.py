from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.schemas import (
    Customer, SalesOrder, SalesOrderItem, ProductionOrder, CuttingRecord, PrintingRecord,
    SewingRecord, PackagingRecord, Package, Shipment, ShipmentPackage, Invoice,
    Payment, StockMovement, Item, StockBatch, WorkOrder, ProductionOrderItem,
)


@dataclass
class HistoryReadContext:
    """Page-scoped summary inputs, loaded using the caller's session."""
    sales_items: list[SalesOrderItem]
    production_orders: list[ProductionOrder]
    cutting: list[CuttingRecord]
    printing: list[PrintingRecord]
    sewing: list[SewingRecord]
    packaging: list[PackagingRecord]
    packages: list[Package]
    shipments: list[Shipment]
    shipment_packages: list[ShipmentPackage]
    invoices: list[Invoice]
    payments: list[Payment]
    movements: list[tuple[StockMovement, Item, StockBatch | None]]
    customers: dict[int, Customer]
    products: list[dict]
    items_by_sales: dict[int, list[SalesOrderItem]] = field(init=False)
    production_by_sales: dict[int, list[ProductionOrder]] = field(init=False)
    stages_by_work: dict[str, dict[int, list]] = field(init=False)
    packages_by_sales: dict[int | None, list[Package]] = field(init=False)
    packages_by_production: dict[int | None, list[Package]] = field(init=False)
    shipments_by_sales: dict[int | None, list[Shipment]] = field(init=False)
    shipments_by_id: dict[int, Shipment] = field(init=False)
    links_by_package: dict[int, list[ShipmentPackage]] = field(init=False)
    links_by_shipment: dict[int, list[ShipmentPackage]] = field(init=False)
    invoices_by_sales: dict[int, list[Invoice]] = field(init=False)
    payments_by_invoice: dict[int | None, list[Payment]] = field(init=False)
    movements_by_reference: dict[tuple[str | None, int | None], list[tuple[StockMovement, Item, StockBatch | None]]] = field(init=False)
    movement_rank: dict[int, int] = field(init=False)
    payment_rank: dict[int, int] = field(init=False)
    products_by_id: dict[int, tuple[int, dict]] = field(init=False)

    def __post_init__(self):
        def grouped(rows, key):
            result = defaultdict(list)
            for row in rows:
                result[key(row)].append(row)
            return result

        self.items_by_sales = grouped(self.sales_items, lambda row: row.sales_order_id)
        self.production_by_sales = grouped(self.production_orders, lambda row: row.sales_order_id)
        self.stages_by_work = {
            name: grouped(rows, lambda row: row.work_order_id)
            for name, rows in (("cutting", self.cutting), ("printing", self.printing),
                               ("sewing", self.sewing), ("packaging", self.packaging))
        }
        self.packages_by_sales = grouped(self.packages, lambda row: row.sales_order_id)
        self.packages_by_production = grouped(self.packages, lambda row: row.production_order_id)
        self.shipments_by_sales = grouped(self.shipments, lambda row: row.sales_order_id)
        self.shipments_by_id = {row.id: row for row in self.shipments}
        self.links_by_package = grouped(self.shipment_packages, lambda row: row.package_id)
        self.links_by_shipment = grouped(self.shipment_packages, lambda row: row.shipment_id)
        self.invoices_by_sales = grouped(self.invoices, lambda row: row.sales_order_id)
        self.payments_by_invoice = grouped(self.payments, lambda row: row.invoice_id)
        self.movements_by_reference = grouped(self.movements, lambda row: (row[0].reference_type, row[0].reference_id))
        self.movement_rank = {row[0].id: index for index, row in enumerate(self.movements)}
        self.payment_rank = {row.id: index for index, row in enumerate(self.payments)}
        self.products_by_id = {row["model_id"]: (index, row) for index, row in enumerate(self.products)}

    def stage_rows(self, name: str, work_ids: set[int]) -> list:
        return sorted((row for wid in work_ids for row in self.stages_by_work[name].get(wid, ())), key=lambda row: row.id)

    def movement_rows(self, references: dict[str, set[int]]) -> list[tuple[StockMovement, Item, StockBatch | None]]:
        rows = {row[0].id: row for kind, ids in references.items() for ref_id in ids
                for row in self.movements_by_reference.get((kind, ref_id), ())}
        return sorted(rows.values(), key=lambda row: self.movement_rank[row[0].id])

    def products_for(self, model_ids: set[int]) -> list[dict]:
        found = (self.products_by_id[mid] for mid in model_ids if mid in self.products_by_id)
        return [row for _, row in sorted(found, key=lambda entry: entry[0])]


def load_history_read_context(
    db: Session, sales: list[SalesOrder], stock: list[ProductionOrder],
    products_loader: Callable[..., list[dict]],
) -> HistoryReadContext:
    sales_ids = [int(so.id) for so in sales]
    items = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id.in_(sales_ids)).order_by(SalesOrderItem.id.asc()).all() if sales_ids else []
    production = db.query(ProductionOrder).options(
        joinedload(ProductionOrder.items), joinedload(ProductionOrder.batches),
        joinedload(ProductionOrder.work_orders),
    ).filter(ProductionOrder.sales_order_id.in_(sales_ids)).order_by(ProductionOrder.id.asc()).all() if sales_ids else []
    all_production = production + stock
    stock_ids = [int(po.id) for po in stock]
    # Reusable CTEs keep selected IDs bound once even when several child
    # reference branches appear in one SQL statement.
    sales_cte = select(SalesOrder.id).where(SalesOrder.id.in_(sales_ids)).cte("history_sales")
    sales_scope = select(sales_cte.c.id)
    po_cte = select(ProductionOrder.id).where(or_(
        ProductionOrder.sales_order_id.in_(sales_scope), ProductionOrder.id.in_(stock_ids),
    )).cte("history_production")
    po_scope = select(po_cte.c.id)
    work_cte = select(WorkOrder.id).where(WorkOrder.production_order_id.in_(po_scope)).cte("history_work")
    work_scope = select(work_cte.c.id)

    def stages(model):
        return db.query(model).filter(model.work_order_id.in_(work_scope)).order_by(model.id.asc()).all() if all_production else []

    cutting, printing, sewing, packaging = (stages(model) for model in (CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord))
    package_filters = []
    if sales_ids:
        package_filters.append(Package.sales_order_id.in_(sales_scope))
    if all_production:
        package_filters.append(Package.production_order_id.in_(po_scope))
    packages = db.query(Package).filter(or_(*package_filters)).order_by(Package.id.asc()).all() if package_filters else []
    # Stock summaries never inspect shipments. Only selected sales packages can
    # bring a linked shipment into a sales summary.
    sales_po_scope = select(ProductionOrder.id).where(ProductionOrder.sales_order_id.in_(sales_scope))
    sales_package_scope = select(Package.id).where(or_(
        Package.sales_order_id.in_(sales_scope), Package.production_order_id.in_(sales_po_scope),
    ))
    linked_shipment_scope = select(ShipmentPackage.shipment_id).where(
        ShipmentPackage.package_id.in_(sales_package_scope),
    )
    shipment_scope = select(Shipment.id).where(or_(
        Shipment.sales_order_id.in_(sales_scope), Shipment.id.in_(linked_shipment_scope),
    ))
    shipments = db.query(Shipment).filter(
        Shipment.id.in_(shipment_scope),
    ).order_by(Shipment.id.asc()).all() if sales_ids else []
    # The legacy builder retains all direct-shipment links only when that sales
    # order has no packages. With packages it keeps only links to those packages.
    sales_has_package = db.query(Package.id).outerjoin(
        ProductionOrder, ProductionOrder.id == Package.production_order_id,
    ).filter(or_(
        Package.sales_order_id == Shipment.sales_order_id,
        ProductionOrder.sales_order_id == Shipment.sales_order_id,
    )).correlate(Shipment).exists()
    direct_without_packages = select(Shipment.id).where(
        Shipment.sales_order_id.in_(sales_scope), ~sales_has_package,
    )
    shipment_packages = db.query(ShipmentPackage).filter(or_(
        ShipmentPackage.package_id.in_(sales_package_scope),
        ShipmentPackage.shipment_id.in_(direct_without_packages),
    )).order_by(ShipmentPackage.id.asc()).all() if sales_ids else []
    invoices = db.query(Invoice).filter(Invoice.sales_order_id.in_(sales_scope)).order_by(Invoice.id.asc()).all() if sales_ids else []
    invoice_scope = db.query(Invoice.id).filter(Invoice.sales_order_id.in_(sales_scope))
    payments = db.query(Payment).filter(Payment.invoice_id.in_(invoice_scope)).order_by(Payment.paid_at.desc().nullslast(), Payment.id.desc()).all() if sales_ids else []
    movement_filters = []
    if sales_ids:
        movement_filters.append((StockMovement.reference_type == "SalesOrder") & StockMovement.reference_id.in_(sales_scope))
    if all_production:
        movement_filters.extend([
            (StockMovement.reference_type == "ProductionOrder") & StockMovement.reference_id.in_(po_scope),
            (StockMovement.reference_type == "CuttingRecord") & StockMovement.reference_id.in_(db.query(CuttingRecord.id).filter(CuttingRecord.work_order_id.in_(work_scope))),
            (StockMovement.reference_type == "PackagingRecord") & StockMovement.reference_id.in_(db.query(PackagingRecord.id).filter(PackagingRecord.work_order_id.in_(work_scope))),
        ])
    movements = db.query(StockMovement, Item, StockBatch).join(Item, Item.id == StockMovement.item_id).outerjoin(StockBatch, StockBatch.id == StockMovement.batch_id).filter(or_(*movement_filters)).order_by(StockMovement.created_at.desc(), StockMovement.id.desc()).all() if movement_filters else []
    customer_ids = {int(so.customer_id) for so in sales if so.customer_id}
    customers = {int(c.id): c for c in db.query(Customer).filter(Customer.id.in_(customer_ids)).all()} if customer_ids else {}
    model_scope = db.query(SalesOrderItem.model_id).filter(SalesOrderItem.sales_order_id.in_(sales_scope)).union(
        db.query(ProductionOrder.model_id).filter(ProductionOrder.id.in_(po_scope)),
        db.query(ProductionOrderItem.model_id).filter(ProductionOrderItem.production_order_id.in_(po_scope)),
    )
    products = products_loader(db, set(), model_filter=model_scope) if sales_ids or stock_ids else []
    return HistoryReadContext(items, production, cutting, printing, sewing, packaging, packages, shipments, shipment_packages, invoices, payments, movements, customers, products)
