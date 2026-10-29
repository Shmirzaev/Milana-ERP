"""Persisted sales-order vocabulary shared by sales and its callers.

These are the stored `sales_orders.status` strings plus the two fixed
categorisation columns of a sales order. `ck_sales_orders_status` and the
column defaults are derived from them, so the values must not drift apart.

Membership in an enum is not a permission and not a state transition: the
services keep enforcing every rule. `SalesOrderType` and
`SalesOrderItemSourceType` name the values the application writes; the create
payload accepts only these members, while the stored columns stay plain string
columns and carry no CHECK constraint.
"""

from enum import Enum


class SalesOrderStatus(str, Enum):
    """The stored `sales_orders.status` values, in `ck_sales_orders_status` order."""

    DRAFT = "draft"
    PENDING_SALES_APPROVAL = "pending_sales_approval"
    CONFIRMED = "confirmed"
    PLANNING = "planning"
    PLANNING_APPROVED = "planning_approved"
    IN_PRODUCTION = "in_production"
    PRODUCTION = "production"
    CUTTING = "cutting"
    PRINTING = "printing"
    SEWING = "sewing"
    PACKAGING = "packaging"
    STORAGE = "storage"
    READY_TO_SHIP = "ready_to_ship"
    READY = "ready"
    RESERVED = "reserved"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class SalesOrderType(str, Enum):
    """The stored `sales_orders.order_type` values.

    The sales-order create endpoint accepts `CLIENT_ORDER` and
    `BRANDED_STOCK_SALE` only; the service guard refuses `BRANDED_STOCK`.
    `BRANDED_STOCK` is still a member because the manual shipment invoice path
    writes it, posting a frozen delivery straight into a sales order.
    """

    CLIENT_ORDER = "client_order"
    BRANDED_STOCK_SALE = "branded_stock_sale"
    BRANDED_STOCK = "branded_stock"


class SalesOrderItemSourceType(str, Enum):
    """The stored `sales_order_items.source_type` values.

    The create payload accepts only these three values for a line source.
    """

    PRODUCE_NEW = "produce_new"
    FROM_STOCK = "from_stock"
    FIRST_GRADE = "first_grade"
