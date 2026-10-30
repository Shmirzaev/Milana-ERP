"""Same-Session persistence operations for Production creation participants.

Business rules, reference checks, number allocation, and work-order transition
decisions remain in models/*. Schema operations own mapped construction and
mutation, use the supplied Session, and never commit or begin transactions.
"""
from __future__ import annotations

from typing import Sequence

from sqlalchemy.orm import Session

from app.libs.types.production import (
    ProductionBatchCreateValues,
    ProductionOrderCreateValues,
    ProductionOrderItemCreateValues,
    ProductionOrderMaterialCreateValues,
    WorkOrderCreateValues,
    WorkOrderInitialState,
)
from app.schemas.production.production import (
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOrderMaterial,
    WorkOrder,
)


def insert_production_order(db: Session, values: ProductionOrderCreateValues) -> ProductionOrder:
    """Insert and flush a new production-order header."""
    row = ProductionOrder(
        production_no=values.production_no,
        production_type=values.production_type.value,
        source_type=values.source_type.value,
        sales_order_id=values.sales_order_id,
        planning_order_id=values.planning_order_id,
        collection_id=values.collection_id,
        model_id=values.model_id,
        brand_id=values.brand_id,
        fabric_batch_id=values.fabric_batch_id,
        status="new",
        planned_quantity=values.planned_quantity,
        start_date=values.start_date,
        deadline=values.deadline,
        estimated_material_code=values.estimated_material_code,
        estimated_material_amount=values.estimated_material_amount,
        estimated_material_unit=values.estimated_material_unit,
        printing_instructions=values.printing_instructions,
        printing_attachments=values.printing_attachments,
        destination_warehouse_id=values.destination_warehouse_id,
        service_customer_name=values.service_customer_name,
        service_customer_reference=values.service_customer_reference,
        service_material_description=values.service_material_description,
        service_material_usage_kg=values.service_material_usage_kg,
        service_material_notes=values.service_material_notes,
        created_by=values.created_by,
    )
    db.add(row)
    db.flush()
    return row


def insert_production_order_components(
    db: Session,
    production_order_id: int,
    materials: Sequence[ProductionOrderMaterialCreateValues],
    items: Sequence[ProductionOrderItemCreateValues],
) -> None:
    """Insert material and item children, preserving the shared flush boundary."""
    for value in materials:
        db.add(ProductionOrderMaterial(
            production_order_id=production_order_id,
            stock_batch_id=value.stock_batch_id,
            estimated_quantity=value.estimated_quantity,
            unit=value.unit,
            position=value.position,
        ))
    for value in items:
        db.add(ProductionOrderItem(
            production_order_id=production_order_id,
            model_id=value.model_id,
            color=value.color,
            size=value.size,
            planned_quantity=value.planned_quantity,
            printing_required=value.printing_required,
        ))
    db.flush()


def insert_production_batches(
    db: Session,
    production_order_id: int,
    values: Sequence[ProductionBatchCreateValues],
) -> list[ProductionBatch]:
    """Insert already-validated batches and flush them on the caller Session."""
    rows = [ProductionBatch(
        production_order_id=production_order_id,
        batch_no=value.batch_no,
        batch_index=value.batch_index,
        name=value.name,
        planned_quantity=value.planned_quantity,
        start_date=value.start_date,
        deadline=value.deadline,
        notes=value.notes,
    ) for value in values]
    db.add_all(rows)
    db.flush()
    return rows


def add_work_orders(
    db: Session,
    production_order_id: int,
    values: Sequence[WorkOrderCreateValues],
) -> list[WorkOrder]:
    """Add work-order rows without flushing yet.

    The legacy caller uses autoflush-disabled Sessions: its following work-order
    query intentionally sees only pre-existing cutting rows. The final state
    operation retains the original single flush after transition calculation.
    """
    rows = [WorkOrder(
        production_order_id=production_order_id,
        production_batch_id=None,
        department_id=value.department_id,
        operation=value.operation,
        status=value.status.value,
        planned_input_qty=value.planned_input_qty,
        planned_output_qty=value.planned_output_qty,
        deadline=value.deadline,
    ) for value in values]
    db.add_all(rows)
    return rows


def apply_initial_production_workflow_state(
    db: Session,
    production_order: ProductionOrder,
    production_status: str,
    work_orders: Sequence[tuple[WorkOrder, WorkOrderInitialState]],
) -> None:
    """Apply service-decided initial state changes and flush all work orders."""
    production_order.status = production_status
    for row, state in work_orders:
        if row.id != state.work_order_id:
            raise ValueError("work-order state does not match its mapped row")
        row.status = state.status.value
        if state.set_start_time:
            row.start_time = state.start_time
    db.flush()
