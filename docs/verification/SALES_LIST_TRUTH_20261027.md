# Sales list quantity and progress correction

Scope: Ismail's urgent correction, source bad3668ec4ed456fd7ba97f39dfb6d7f009df805.
Engineer Ismail (Codex implementation); independent technical reviewer root agent;
team reviewer Mirshoir; business/human approval remains separate.

The actual list page used rowMetrics(index) to invent quantity and completion
percentages for both responsive layouts. Changing row order changed the supposed
facts. Replace quantities with SUM(SalesOrderItem.quantity), grouped only over IDs
in the already filtered/paginated result. Add a list-only SalesOrderListRow DTO
with canonical inherited enums and required integer total_quantity; preserve
dict/list/envelope serialization for existing callers. Detail and create schemas
remain unchanged. Page and customer queries stay bounded; no item ORM hydration,
new persistence, locks, commits, migrations or permissions are introduced.

Piece inputs become stored item quantities. Pack inputs initially store zero;
reserve_ready_packs maps Fulfillment's actual allocated piece quantities back to
Sales lines through schema helpers. Therefore the list reports stored pieces:
zero for unallocated packs, actual allocated pieces afterward, never requested
pack count. No production progress is derived from reservations or order status.
Show the translated Progress unavailable label; an older API missing quantity
shows an em dash rather than zero. Status filters, tabs, dates, search, money,
CSV and create/detail navigation retain their existing behavior.

Validation: actual component rendering with2/6-piece rows, reversed ordering,
empty/zero, old-server missing field, EN/RU/UZ in desktop/mobile; the original
page fails the same regression. PostgreSQL checks cover totals, multiple lines,
pack units, list/envelope and filtered pagination, service route forwarding,
item hydration and aggregate rows/parameters bounded by page IDs, constant query
count as data grows, and caller pending work preserved. Existing list/shipment
reference query regressions run unchanged. Full frontend TypeScript is required.

Open gates: independent review of frozen candidate, combined source verification,
coordinator's actual browser desktop/mobile/reorder checks and persisted readback,
then recorded human visual approval. This document does not mark AI verification,
production acceptance, push or deployment.
