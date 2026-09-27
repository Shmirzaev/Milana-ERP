"""Frozen schema owned by revision 0001_initial.

Source: application metadata at Git commit
a944a576121fb9ba3be2256a1bf4dd242ac308de (2026-06-18), the last
snapshot before the later table-creation migrations were introduced.
The 54 tables include early bootstrap-only objects such as cutting_passports,
sewing_flows, sewing_assignments and password_reset_tokens. Starting from the
older May snapshot would lose those objects: no later revision creates them.

Two nullable audit columns are also frozen here: prev_hash and entry_hash
(plus ix_audit_logs_entry_hash). Commit 553d298 introduced them in the models
without an ADD COLUMN migration; later migrations and the application rely on
them. All other later additions remain owned by their existing revisions.

Generated once from that historical metadata; no application-model imports
or historical ORM classes are needed at migration runtime. Do not regenerate
this bootstrap from current models when adding future migrations.
"""

import sqlalchemy as sa


def build_metadata() -> sa.MetaData:
    metadata = sa.MetaData()

    sa.Table('brands', metadata,
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('logo_url', sa.String(length=512), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )

    sa.Table('customers', metadata,
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=64), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('departments', metadata,
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    sa.UniqueConstraint('name')
    )

    sa.Table('items', metadata,
    sa.Column('sku', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('unit', sa.String(length=32), nullable=False),
    sa.Column('default_cost', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('reorder_level', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('track_batch', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('roles', metadata,
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('permissions', sa.JSON(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )

    sa.Table('suppliers', metadata,
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=64), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('system_settings', metadata,
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value_json', sa.JSON(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('collections', metadata,
    sa.Column('brand_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('season', sa.String(length=64), nullable=True),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('users', metadata,
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role_id', sa.Integer(), nullable=True),
    sa.Column('department_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tokens_valid_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('warehouses', metadata,
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('audit_logs', metadata,
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=True),
    sa.Column('old_value_json', sa.JSON(), nullable=True),
    sa.Column('new_value_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('prev_hash', sa.String(length=64), nullable=True),
    sa.Column('entry_hash', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('employees', metadata,
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('full_name', sa.String(length=255), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=True),
    sa.Column('position', sa.String(length=128), nullable=True),
    sa.Column('phone', sa.String(length=64), nullable=True),
    sa.Column('salary', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('notifications', metadata,
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('link', sa.String(length=512), nullable=True),
    sa.Column('is_read', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('package_change_requests', metadata,
    sa.Column('package_id', sa.Integer(), nullable=False),
    sa.Column('package_no', sa.String(length=64), nullable=False),
    sa.Column('request_type', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('before_json', sa.JSON(), nullable=True),
    sa.Column('payload_json', sa.JSON(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('requested_by', sa.Integer(), nullable=True),
    sa.Column('reviewed_by', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('password_reset_tokens', metadata,
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('sales_orders', metadata,
    sa.Column('order_no', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('order_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
    sa.Column('total_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('planning_estimated_material_cost', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('planning_estimated_labor_cost', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('planning_estimated_electricity_cost', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('planning_estimated_other_cost', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('planning_estimated_net_cost', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('planning_suggested_price_15', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('planning_suggested_price_20', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('planning_estimated_lead_time_minutes', sa.Integer(), nullable=True),
    sa.Column('planning_estimate_comment', sa.Text(), nullable=True),
    sa.Column('planning_estimate_submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('planning_estimate_submitted_by', sa.Integer(), nullable=True),
    sa.Column('printing_instructions', sa.Text(), nullable=True),
    sa.Column('printing_attachments', sa.JSON(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['planning_estimate_submitted_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('sewing_flows', metadata,
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('capacity_per_day', sa.Integer(), nullable=False),
    sa.Column('supervisor_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['supervisor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    sa.UniqueConstraint('name')
    )

    sa.Table('stock_batches', metadata,
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('batch_no', sa.String(length=64), nullable=False),
    sa.Column('supplier_id', sa.Integer(), nullable=True),
    sa.Column('color', sa.String(length=64), nullable=True),
    sa.Column('old_code', sa.String(length=64), nullable=True),
    sa.Column('color_code', sa.String(length=32), nullable=True),
    sa.Column('color_status', sa.String(length=64), nullable=True),
    sa.Column('order_no', sa.String(length=64), nullable=True),
    sa.Column('width', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('gsm', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('piece_count', sa.Integer(), nullable=True),
    sa.Column('processes', sa.String(length=255), nullable=True),
    sa.Column('unit', sa.String(length=32), nullable=False),
    sa.Column('cost_per_unit', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('received_date', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('warehouse_id', sa.Integer(), nullable=False),
    sa.Column('qc_status', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('tasks', metadata,
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('assigned_to', sa.Integer(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('priority', sa.String(length=16), nullable=False),
    sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('entity_type', sa.String(length=64), nullable=True),
    sa.Column('entity_id', sa.Integer(), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('invoices', metadata,
    sa.Column('sales_order_id', sa.Integer(), nullable=False),
    sa.Column('invoice_no', sa.String(length=64), nullable=False),
    sa.Column('external_source', sa.String(length=32), nullable=True),
    sa.Column('external_id', sa.String(length=128), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('invoice_no')
    )

    sa.Table('models', metadata,
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=64), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('brand_id', sa.Integer(), nullable=True),
    sa.Column('collection_id', sa.Integer(), nullable=True),
    sa.Column('product_type', sa.String(length=64), nullable=True),
    sa.Column('season', sa.String(length=64), nullable=True),
    sa.Column('constructor_employee_id', sa.Integer(), nullable=True),
    sa.Column('designer_employee_id', sa.Integer(), nullable=True),
    sa.Column('details_json', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('approved_by', sa.Integer(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sam_minutes', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ),
    sa.ForeignKeyConstraint(['constructor_employee_id'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['designer_employee_id'], ['employees.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('shipments', metadata,
    sa.Column('sales_order_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('shipment_no', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('shipment_no')
    )

    sa.Table('stock_movements', metadata,
    sa.Column('movement_type', sa.String(length=32), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=True),
    sa.Column('from_warehouse_id', sa.Integer(), nullable=True),
    sa.Column('to_warehouse_id', sa.Integer(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('unit', sa.String(length=32), nullable=False),
    sa.Column('reference_type', sa.String(length=64), nullable=True),
    sa.Column('reference_id', sa.Integer(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['stock_batches.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['from_warehouse_id'], ['warehouses.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
    sa.ForeignKeyConstraint(['to_warehouse_id'], ['warehouses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('collection_models', metadata,
    sa.Column('collection_id', sa.Integer(), nullable=False),
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('model_bom', metadata,
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('size', sa.String(length=32), nullable=True),
    sa.Column('color', sa.String(length=64), nullable=True),
    sa.Column('quantity_per_piece', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('unit', sa.String(length=32), nullable=False),
    sa.Column('waste_percent', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('model_colors', metadata,
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('color_name', sa.String(length=64), nullable=False),
    sa.Column('color_code', sa.String(length=16), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('model_images', metadata,
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('file_url', sa.String(length=512), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('content_type', sa.String(length=128), nullable=True),
    sa.Column('file_data', sa.LargeBinary(), nullable=True),
    sa.Column('image_type', sa.String(length=32), nullable=True),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('model_sizes', metadata,
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('size', sa.String(length=32), nullable=False),
    sa.Column('measurement_json', sa.JSON(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('payments', metadata,
    sa.Column('invoice_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('external_source', sa.String(length=32), nullable=True),
    sa.Column('external_id', sa.String(length=128), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('payment_method', sa.String(length=32), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ),
    sa.ForeignKeyConstraint(['invoice_id'], ['invoices.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('production_orders', metadata,
    sa.Column('production_no', sa.String(length=64), nullable=False),
    sa.Column('production_type', sa.String(length=32), nullable=False),
    sa.Column('sales_order_id', sa.Integer(), nullable=True),
    sa.Column('collection_id', sa.Integer(), nullable=True),
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('planned_quantity', sa.Integer(), nullable=False),
    sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
    sa.Column('estimated_material_code', sa.String(length=128), nullable=True),
    sa.Column('estimated_material_amount', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('estimated_material_unit', sa.String(length=32), nullable=True),
    sa.Column('destination_warehouse_id', sa.Integer(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['destination_warehouse_id'], ['warehouses.id'], ),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('sales_order_items', metadata,
    sa.Column('sales_order_id', sa.Integer(), nullable=False),
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('brand_id', sa.Integer(), nullable=True),
    sa.Column('collection_id', sa.Integer(), nullable=True),
    sa.Column('color', sa.String(length=64), nullable=False),
    sa.Column('size', sa.String(length=32), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('printing_required', sa.Boolean(), nullable=False),
    sa.Column('source_type', sa.String(length=32), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('cutting_passports', metadata,
    sa.Column('passport_no', sa.String(length=32), nullable=False),
    sa.Column('date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('production_order_id', sa.Integer(), nullable=True),
    sa.Column('operator_id', sa.Integer(), nullable=True),
    sa.Column('model_code', sa.String(length=128), nullable=True),
    sa.Column('variant', sa.String(length=64), nullable=True),
    sa.Column('mold_no', sa.String(length=64), nullable=True),
    sa.Column('image_ref', sa.String(length=512), nullable=True),
    sa.Column('operator_name_manual', sa.String(length=128), nullable=True),
    sa.Column('fabric_type', sa.String(length=128), nullable=True),
    sa.Column('has_print', sa.Boolean(), nullable=False),
    sa.Column('order_no', sa.String(length=128), nullable=True),
    sa.Column('lot_no', sa.String(length=64), nullable=True),
    sa.Column('size_range', sa.String(length=32), nullable=True),
    sa.Column('rolls_count', sa.Integer(), nullable=True),
    sa.Column('layer_weight_kg', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('total_layers', sa.Integer(), nullable=True),
    sa.Column('planned_kg', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('pieces', sa.Integer(), nullable=True),
    sa.Column('fabric_width_m', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('lay_length_m', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('gramage', sa.Numeric(precision=14, scale=6), nullable=True),
    sa.Column('waste_pct', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('beka_per_piece_kg', sa.Numeric(precision=14, scale=6), nullable=True),
    sa.Column('other_beka_per_piece_kg', sa.Numeric(precision=14, scale=6), nullable=True),
    sa.Column('scrap_kg', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('ribana_per_piece_kg', sa.Numeric(precision=14, scale=6), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['production_order_id'], ['production_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('production_batches', metadata,
    sa.Column('production_order_id', sa.Integer(), nullable=False),
    sa.Column('batch_no', sa.String(length=32), nullable=False),
    sa.Column('batch_index', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=True),
    sa.Column('planned_quantity', sa.Integer(), nullable=False),
    sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['production_order_id'], ['production_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('production_order_items', metadata,
    sa.Column('production_order_id', sa.Integer(), nullable=False),
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('color', sa.String(length=64), nullable=False),
    sa.Column('size', sa.String(length=32), nullable=False),
    sa.Column('planned_quantity', sa.Integer(), nullable=False),
    sa.Column('completed_quantity', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.ForeignKeyConstraint(['production_order_id'], ['production_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('bundles', metadata,
    sa.Column('bundle_no', sa.String(length=64), nullable=False),
    sa.Column('barcode', sa.String(length=64), nullable=False),
    sa.Column('qr_code_url', sa.String(length=512), nullable=True),
    sa.Column('production_order_id', sa.Integer(), nullable=False),
    sa.Column('production_batch_id', sa.Integer(), nullable=True),
    sa.Column('sales_order_id', sa.Integer(), nullable=True),
    sa.Column('brand_id', sa.Integer(), nullable=True),
    sa.Column('collection_id', sa.Integer(), nullable=True),
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('color', sa.String(length=64), nullable=False),
    sa.Column('size', sa.String(length=32), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('current_department_id', sa.Integer(), nullable=True),
    sa.Column('next_department_id', sa.Integer(), nullable=True),
    sa.Column('sewing_factory_code', sa.String(length=32), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['current_department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.ForeignKeyConstraint(['next_department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['production_batch_id'], ['production_batches.id'], ),
    sa.ForeignKeyConstraint(['production_order_id'], ['production_orders.id'], ),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('packages', metadata,
    sa.Column('package_no', sa.String(length=64), nullable=False),
    sa.Column('barcode', sa.String(length=64), nullable=False),
    sa.Column('qr_code_url', sa.String(length=512), nullable=True),
    sa.Column('production_order_id', sa.Integer(), nullable=False),
    sa.Column('production_batch_id', sa.Integer(), nullable=True),
    sa.Column('sales_order_id', sa.Integer(), nullable=True),
    sa.Column('brand_id', sa.Integer(), nullable=True),
    sa.Column('collection_id', sa.Integer(), nullable=True),
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('color', sa.String(length=64), nullable=False),
    sa.Column('package_type', sa.String(length=16), nullable=False),
    sa.Column('total_quantity', sa.Integer(), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('weight_kg', sa.Numeric(precision=14, scale=4), nullable=True),
    sa.Column('warehouse_id', sa.Integer(), nullable=True),
    sa.Column('storage_cell', sa.String(length=32), nullable=True),
    sa.Column('storage_shelf', sa.String(length=8), nullable=True),
    sa.Column('storage_placed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('packed_by', sa.Integer(), nullable=True),
    sa.Column('packed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('received_by', sa.Integer(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.ForeignKeyConstraint(['packed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['production_batch_id'], ['production_batches.id'], ),
    sa.ForeignKeyConstraint(['production_order_id'], ['production_orders.id'], ),
    sa.ForeignKeyConstraint(['received_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('work_orders', metadata,
    sa.Column('production_order_id', sa.Integer(), nullable=False),
    sa.Column('production_batch_id', sa.Integer(), nullable=True),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('operation', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('planned_input_qty', sa.Integer(), nullable=False),
    sa.Column('planned_output_qty', sa.Integer(), nullable=False),
    sa.Column('actual_input_qty', sa.Integer(), nullable=False),
    sa.Column('actual_output_qty', sa.Integer(), nullable=False),
    sa.Column('passed_qty', sa.Integer(), nullable=False),
    sa.Column('failed_qty', sa.Integer(), nullable=False),
    sa.Column('rework_qty', sa.Integer(), nullable=False),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
    sa.Column('assigned_to', sa.Integer(), nullable=True),
    sa.Column('sewing_flow_id', sa.Integer(), nullable=True),
    sa.Column('is_blocked', sa.Boolean(), nullable=False),
    sa.Column('block_reason', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['production_batch_id'], ['production_batches.id'], ),
    sa.ForeignKeyConstraint(['production_order_id'], ['production_orders.id'], ),
    sa.ForeignKeyConstraint(['sewing_flow_id'], ['sewing_flows.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('bundle_scan_logs', metadata,
    sa.Column('bundle_id', sa.Integer(), nullable=False),
    sa.Column('scanned_by', sa.Integer(), nullable=True),
    sa.Column('scan_type', sa.String(length=32), nullable=False),
    sa.Column('from_department_id', sa.Integer(), nullable=True),
    sa.Column('to_department_id', sa.Integer(), nullable=True),
    sa.Column('location', sa.String(length=128), nullable=True),
    sa.Column('scanned_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['bundle_id'], ['bundles.id'], ),
    sa.ForeignKeyConstraint(['from_department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['scanned_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['to_department_id'], ['departments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('cutting_records', metadata,
    sa.Column('work_order_id', sa.Integer(), nullable=False),
    sa.Column('production_batch_id', sa.Integer(), nullable=True),
    sa.Column('fabric_batch_id', sa.Integer(), nullable=True),
    sa.Column('input_quantity', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('input_unit', sa.String(length=32), nullable=False),
    sa.Column('cut_pieces', sa.Integer(), nullable=False),
    sa.Column('passed_pieces', sa.Integer(), nullable=False),
    sa.Column('defective_pieces', sa.Integer(), nullable=False),
    sa.Column('waste_quantity', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('waste_unit', sa.String(length=32), nullable=False),
    sa.Column('bundle_count', sa.Integer(), nullable=False),
    sa.Column('total_bundled_quantity', sa.Integer(), nullable=False),
    sa.Column('operator_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['fabric_batch_id'], ['stock_batches.id'], ),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['production_batch_id'], ['production_batches.id'], ),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('finished_goods_stock', metadata,
    sa.Column('production_order_id', sa.Integer(), nullable=True),
    sa.Column('sales_order_id', sa.Integer(), nullable=True),
    sa.Column('package_id', sa.Integer(), nullable=True),
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('collection_id', sa.Integer(), nullable=True),
    sa.Column('brand_id', sa.Integer(), nullable=True),
    sa.Column('color', sa.String(length=64), nullable=False),
    sa.Column('size', sa.String(length=32), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('available_qty', sa.Integer(), nullable=False),
    sa.Column('reserved_qty', sa.Integer(), nullable=False),
    sa.Column('sold_qty', sa.Integer(), nullable=False),
    sa.Column('cost_per_piece', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('selling_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('warehouse_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.ForeignKeyConstraint(['package_id'], ['packages.id'], ),
    sa.ForeignKeyConstraint(['production_order_id'], ['production_orders.id'], ),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('package_batch_allocations', metadata,
    sa.Column('package_id', sa.Integer(), nullable=False),
    sa.Column('production_batch_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['package_id'], ['packages.id'], ),
    sa.ForeignKeyConstraint(['production_batch_id'], ['production_batches.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('package_items', metadata,
    sa.Column('package_id', sa.Integer(), nullable=False),
    sa.Column('model_id', sa.Integer(), nullable=False),
    sa.Column('color', sa.String(length=64), nullable=False),
    sa.Column('size', sa.String(length=32), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['model_id'], ['models.id'], ),
    sa.ForeignKeyConstraint(['package_id'], ['packages.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('package_scan_logs', metadata,
    sa.Column('package_id', sa.Integer(), nullable=False),
    sa.Column('scanned_by', sa.Integer(), nullable=True),
    sa.Column('scan_type', sa.String(length=32), nullable=False),
    sa.Column('location', sa.String(length=128), nullable=True),
    sa.Column('scanned_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['package_id'], ['packages.id'], ),
    sa.ForeignKeyConstraint(['scanned_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('packaging_records', metadata,
    sa.Column('work_order_id', sa.Integer(), nullable=False),
    sa.Column('production_batch_id', sa.Integer(), nullable=True),
    sa.Column('input_qty', sa.Integer(), nullable=False),
    sa.Column('packed_qty', sa.Integer(), nullable=False),
    sa.Column('damaged_qty', sa.Integer(), nullable=False),
    sa.Column('package_count', sa.Integer(), nullable=False),
    sa.Column('total_packed_quantity', sa.Integer(), nullable=False),
    sa.Column('packaging_material_used', sa.String(length=255), nullable=True),
    sa.Column('operator_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['production_batch_id'], ['production_batches.id'], ),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('printing_records', metadata,
    sa.Column('work_order_id', sa.Integer(), nullable=False),
    sa.Column('production_batch_id', sa.Integer(), nullable=True),
    sa.Column('input_qty', sa.Integer(), nullable=False),
    sa.Column('printed_qty', sa.Integer(), nullable=False),
    sa.Column('passed_qty', sa.Integer(), nullable=False),
    sa.Column('rejected_qty', sa.Integer(), nullable=False),
    sa.Column('defect_reason', sa.String(length=255), nullable=True),
    sa.Column('print_type', sa.String(length=64), nullable=True),
    sa.Column('operator_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['production_batch_id'], ['production_batches.id'], ),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('quality_checks', metadata,
    sa.Column('work_order_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=True),
    sa.Column('checked_qty', sa.Integer(), nullable=False),
    sa.Column('passed_qty', sa.Integer(), nullable=False),
    sa.Column('failed_qty', sa.Integer(), nullable=False),
    sa.Column('defect_type', sa.String(length=128), nullable=True),
    sa.Column('defect_reason', sa.String(length=255), nullable=True),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('checked_by', sa.Integer(), nullable=True),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['checked_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('sewing_assignments', metadata,
    sa.Column('work_order_id', sa.Integer(), nullable=False),
    sa.Column('sewing_flow_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('completed_qty', sa.Integer(), nullable=False),
    sa.Column('planned_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('planned_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('actual_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('actual_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['sewing_flow_id'], ['sewing_flows.id'], ),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('sewing_records', metadata,
    sa.Column('work_order_id', sa.Integer(), nullable=False),
    sa.Column('production_batch_id', sa.Integer(), nullable=True),
    sa.Column('input_qty', sa.Integer(), nullable=False),
    sa.Column('sewn_qty', sa.Integer(), nullable=False),
    sa.Column('passed_qty', sa.Integer(), nullable=False),
    sa.Column('failed_qty', sa.Integer(), nullable=False),
    sa.Column('rework_qty', sa.Integer(), nullable=False),
    sa.Column('rejected_qty', sa.Integer(), nullable=False),
    sa.Column('defect_reason', sa.String(length=255), nullable=True),
    sa.Column('line_name', sa.String(length=64), nullable=True),
    sa.Column('operator_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['production_batch_id'], ['production_batches.id'], ),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('shipment_packages', metadata,
    sa.Column('shipment_id', sa.Integer(), nullable=False),
    sa.Column('package_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['package_id'], ['packages.id'], ),
    sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('shipment_scan_logs', metadata,
    sa.Column('shipment_id', sa.Integer(), nullable=False),
    sa.Column('package_id', sa.Integer(), nullable=True),
    sa.Column('scanned_code', sa.String(length=128), nullable=False),
    sa.Column('scan_result', sa.String(length=32), nullable=False),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('scanned_by', sa.Integer(), nullable=True),
    sa.Column('scanned_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['package_id'], ['packages.id'], ),
    sa.ForeignKeyConstraint(['scanned_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('waste_records', metadata,
    sa.Column('production_order_id', sa.Integer(), nullable=True),
    sa.Column('work_order_id', sa.Integer(), nullable=True),
    sa.Column('source_department_id', sa.Integer(), nullable=True),
    sa.Column('item_id', sa.Integer(), nullable=True),
    sa.Column('batch_id', sa.Integer(), nullable=True),
    sa.Column('waste_type', sa.String(length=64), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('unit', sa.String(length=32), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('sellable', sa.Boolean(), nullable=False),
    sa.Column('estimated_value', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['stock_batches.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
    sa.ForeignKeyConstraint(['production_order_id'], ['production_orders.id'], ),
    sa.ForeignKeyConstraint(['source_department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('stock_reservations', metadata,
    sa.Column('sales_order_id', sa.Integer(), nullable=False),
    sa.Column('finished_goods_stock_id', sa.Integer(), nullable=False),
    sa.Column('package_id', sa.Integer(), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('reserved_by', sa.Integer(), nullable=True),
    sa.Column('reserved_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['finished_goods_stock_id'], ['finished_goods_stock.id'], ),
    sa.ForeignKeyConstraint(['package_id'], ['packages.id'], ),
    sa.ForeignKeyConstraint(['reserved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['sales_order_id'], ['sales_orders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('waste_disposal_requests', metadata,
    sa.Column('waste_record_id', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('requested_by', sa.Integer(), nullable=True),
    sa.Column('approved_by', sa.Integer(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('proof_file_url', sa.String(length=512), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['waste_record_id'], ['waste_records.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    sa.Table('waste_sales', metadata,
    sa.Column('waste_record_id', sa.Integer(), nullable=False),
    sa.Column('buyer_name', sa.String(length=255), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=14, scale=4), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('sold_by', sa.Integer(), nullable=True),
    sa.Column('sold_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['sold_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['waste_record_id'], ['waste_records.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    sa.Index('ix_audit_logs_entry_hash', metadata.tables['audit_logs'].c['entry_hash'], unique=False)
    sa.Index('ix_bundles_barcode', metadata.tables['bundles'].c['barcode'], unique=True)
    sa.Index('ix_bundles_bundle_no', metadata.tables['bundles'].c['bundle_no'], unique=True)
    sa.Index('ix_bundles_production_batch_id', metadata.tables['bundles'].c['production_batch_id'], unique=False)
    sa.Index('ix_cutting_passports_passport_no', metadata.tables['cutting_passports'].c['passport_no'], unique=False)
    sa.Index('ix_items_sku', metadata.tables['items'].c['sku'], unique=True)
    sa.Index('ix_models_code', metadata.tables['models'].c['code'], unique=True)
    sa.Index('ix_package_batch_allocations_package_id', metadata.tables['package_batch_allocations'].c['package_id'], unique=False)
    sa.Index('ix_package_batch_allocations_production_batch_id', metadata.tables['package_batch_allocations'].c['production_batch_id'], unique=False)
    sa.Index('ix_package_change_requests_package_id', metadata.tables['package_change_requests'].c['package_id'], unique=False)
    sa.Index('ix_package_change_requests_package_no', metadata.tables['package_change_requests'].c['package_no'], unique=False)
    sa.Index('ix_package_change_requests_status', metadata.tables['package_change_requests'].c['status'], unique=False)
    sa.Index('ix_packages_barcode', metadata.tables['packages'].c['barcode'], unique=True)
    sa.Index('ix_packages_package_no', metadata.tables['packages'].c['package_no'], unique=True)
    sa.Index('ix_packages_production_batch_id', metadata.tables['packages'].c['production_batch_id'], unique=False)
    sa.Index('ix_password_reset_tokens_token_hash', metadata.tables['password_reset_tokens'].c['token_hash'], unique=True)
    sa.Index('ix_password_reset_tokens_user_id', metadata.tables['password_reset_tokens'].c['user_id'], unique=False)
    sa.Index('ix_production_batches_production_order_id', metadata.tables['production_batches'].c['production_order_id'], unique=False)
    sa.Index('ix_production_orders_production_no', metadata.tables['production_orders'].c['production_no'], unique=True)
    sa.Index('ix_sales_orders_order_no', metadata.tables['sales_orders'].c['order_no'], unique=True)
    sa.Index('ix_sewing_assignments_sewing_flow_id', metadata.tables['sewing_assignments'].c['sewing_flow_id'], unique=False)
    sa.Index('ix_sewing_assignments_work_order_id', metadata.tables['sewing_assignments'].c['work_order_id'], unique=False)
    sa.Index('ix_shipment_scan_logs_package_id', metadata.tables['shipment_scan_logs'].c['package_id'], unique=False)
    sa.Index('ix_shipment_scan_logs_shipment_id', metadata.tables['shipment_scan_logs'].c['shipment_id'], unique=False)
    sa.Index('ix_stock_batches_batch_no', metadata.tables['stock_batches'].c['batch_no'], unique=False)
    sa.Index('ix_system_settings_key', metadata.tables['system_settings'].c['key'], unique=True)
    sa.Index('ix_users_email', metadata.tables['users'].c['email'], unique=True)
    return metadata
