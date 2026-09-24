# DB01 historical item-unit preflight

Run from `backend` with an explicitly selected database configured through
`ITEM_UNIT_AUDIT_DATABASE_URL`:

```powershell
python scripts/audit_item_unit_history.py
```

The script compares `unit` with the referenced catalog item's `unit` in
`stock_batches`, `material_reservations`, `purchase_request_lines`,
`purchase_order_lines`, `stock_movements`, item-attributed
`forecast_recommendations`, `waste_records`, `model_bom`,
`production_order_materials`, `cutting_material_usages`,
`cutting_beika_material_usages`, `manual_accessory_issues`, and
`eco_fabric_rolls`. Direct `item_id` references are joined to `items`; rows
linked by `batch_id` or `stock_batch_id` are resolved through the referenced
stock batch to its catalog item. When a row has both item and batch references,
the preflight also reports an unresolved reference if the batch is missing, its
item is missing, or its item differs from the direct item. Rows with neither
reference are omitted. It returns JSON containing scanned/equal/missing/mismatch
counts and every mismatch's row ID, resolved item ID, stored unit, and catalog
unit. Orphans and conflicting references appear in `unresolved_items` with row
and reference IDs plus a reason. It does not select item names, notes, or
recommendation reasons. PostgreSQL runs in a repeatable-read,
read-only transaction; SQLite enables `query_only` on the connection. Other
dialects fail closed. `scanned_count` includes rows with at least one direct
item or batch reference; unresolved references remain included and are counted
separately.

The comparison is exact label equality. It does not normalize spelling or
case, infer unit conversions, inspect quantity meaning, or decide whether a
historical value was valid when created. Rows with a null or blank unit are
counted as missing and omitted from mismatch details; unlinked forecast, waste,
and descriptive BOM rows without a resolvable item or batch are outside this
comparison. Equal labels do not prove the stored quantity was historically
correct. Mismatches and unresolved references are evidence for manual review,
not a correction plan. Run only against a database whose schema contains all
listed tables and columns.
