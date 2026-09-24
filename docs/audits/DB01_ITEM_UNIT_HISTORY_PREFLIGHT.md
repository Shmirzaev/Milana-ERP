# DB01 historical item-unit preflight

Run from `backend` with an explicitly selected database configured through
`ITEM_UNIT_AUDIT_DATABASE_URL`:

```powershell
python scripts/audit_item_unit_history.py
```

The script compares `unit` with the referenced `items.unit` in `stock_batches`,
`material_reservations`, `purchase_request_lines`, `purchase_order_lines`,
`stock_movements`, and item-attributed `forecast_recommendations`. It returns
JSON containing scanned/equal/missing/mismatch counts and every mismatch's row
ID, item ID, stored unit, and catalog unit. It also separately reports rows
whose non-null `item_id` has no matching item row. Recommendations without an
`item_id` are excluded. It does not select item names, notes, or recommendation
reasons. PostgreSQL runs in a repeatable-read,
read-only transaction; SQLite enables `query_only` on the connection. Other
dialects fail closed. `scanned_count` includes only rows with a non-null
`item_id`; orphaned item references remain included and are counted separately.

The comparison is exact label equality. It does not normalize spelling or
case, infer unit conversions, inspect quantity meaning, or decide whether a
historical value was valid when created. Rows with a null or blank unit are
counted as missing and omitted from mismatch details; recommendation rows
without an `item_id` are outside this comparison. Equal labels do not prove
the stored quantity was historically correct. Mismatches are evidence for
manual review, not a correction plan. Run only against a database whose schema
contains all listed tables and columns.
