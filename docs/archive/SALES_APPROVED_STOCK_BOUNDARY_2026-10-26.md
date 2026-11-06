# Approved Sales / Fulfillment reservation operation

26 October 2026. Engineer: Ismail (Sales) / Mirshoir (Fulfillment); reciprocal
review. Work-management participant: Dilmurod / Mirshoir. AI executor: Codex Sales
subagent; independent integration/review: root Codex. Human visual acceptance
remains pending.

## Authorization and source

Ismail first requested a mentor-grounded boundary revision. Actual Meditech
`b4c646ce471efbf6fe984f3315bba366b197281a` and Pizza House
`0039d4752910c05c15995c3239524b450410f72d` source were read: resolver/controller ->
named typed service method -> schema model, with public calls for another service's
responsibility and canonical enums in real contracts/schema definitions.
Ismail then explicitly answered **“Approve revised boundary”** to the named
`reserve_pieces` / `reserve_packs` proposal. This permits implementation, not
runtime/human acceptance, merge, deployment or new business behavior.

Implementation base: `a3c278d7dad5e14cf463bad4652ec4b2014e2074`. Ten earlier
Sales worker files were frozen and SHA-256 verified before adoption. The earlier
unapproved generic-allocation draft remains separate and was not integrated.
The scoped system-shortage task extraction follows the already assigned
`models/work_management/tasks_service.py` responsibility and the user's requirement
for public domain calls/schema-owned participants; no general Task CRUD change.

## Actual call and write path

`api/routes/sales.py` -> `models/sales/orders_service.py` -> Sales reservation
coordination -> `models/fulfillment/stock_service.reserve_pieces/reserve_packs` ->
`schemas/fulfillment/stock_persistence.py`.

Fulfillment owns physical stock eligibility, selection, metadata repair and stock /
reservation writes. It accepts scalar actor/order IDs plus typed immutable demands;
no Sales model crosses the reservation boundary. Sales retains the order lock,
pack replay refusal, line quantities, total, status/notes, audit/idempotency and
outer commit. Every participant uses the same Session. Metadata inference remains
the existing owning helper; its decided mapped updates now use the schema writer.
Shortage Task insertion now goes through Work management -> its schema writer.
Shared audit/notification/idempotency schema writers are inherited from the base.

The pack caller uses opaque request-local ordinal keys to map quantities back to
its lines; it does not require database IDs or add a flush for newly created lines.
Stock writes precede Sales quantity updates within the same uncommitted operation;
no intermediate database flush is introduced. Both public stock operations
validate malformed demand types and fields before any database access.

## Preserved behavior

- Pieces select whole packages before eligible legacy remainder. Whole six plus
  legacy two satisfies eight; legacy persisted package ID remains present while
  its display ID remains null. Partial remaining stock retains its prior status.
- Package subset selection order is predecessor reconstruction, not ascending ID;
  lock acquisition order remains ascending independently. Audit payload order is
  unchanged. Pack counts reserve complete rows by assignment; pieces add quantities.
- Standard/first-grade are the piece action subset; packs stay standard only.
  Second-grade remains outside Sales. Zero pieces are valid input but all-zero
  allocation retains the old fully-reserved 409. Pack counts remain strict positive.
- Package -> metadata repair/flush -> stock FOR NO KEY UPDATE is preserved for
  pieces. Sales order -> package -> stock FOR UPDATE remains the pack sequence.
- Shortage tasks retain exact title, description, recipient, actor, deadline,
  pending/high fields and duplicate behavior. No new user-facing permission,
  entity link, notification, audit or deduplication rule is added.
- A historically empty persisted Sales order still gets the existing empty result;
  Sales does not send a malformed empty request to the new public boundary.

## Types and table coverage

| Tables / contracts | Converted in this operation | Remaining coverage |
| --- | --- | --- |
| Sales orders/items | Existing worker canonical Sales input/output enums and schema-owned create/status/quantity/total/note writes; typed reservation summaries/shortages | Update/query/frontend contracts and other lifecycle writes remain separate operations. |
| Packages | Canonical PackageStockKind in actual piece input and candidate query; same stored VARCHAR, CHECK text, defaults | Packaging DTOs/other writers still need system-wide reconciliation. |
| Finished goods / reservations | Typed public demands/results, schema-owned quantities/status/reservation and metadata writes; FinishedGoodsStatus in internal writes and unchanged schema CHECK/default | Other routes/dispatch/reopen writers remain pending. |
| Tasks | Public system-shortage participant -> schema write; TaskStatus/TaskPriority match mapping comments and TasksDrawer unions, used in the writer/defaults | General Task DTOs/CRUD/historical-value audit remain pending. |
| Audit/notifications/idempotency | Existing owned shared writers used in same outer operation | Whole shared-domain coverage is not claimed. |

`ready_pack_candidates` read consumers were updated to its owning Fulfillment
module, including first-grade/options and lock tests. These legacy option readers
still use mapped read results; this is a named pending read-interface conversion,
not a claim that all Sales/Fulfillment access is isolated.

## Evidence gates

Freeze exact paths/hashes in the task manifest. Automated cases include the
existing Sales suites and independent enum/late-participant assertions, new strict
public-input checks, unflushed-line attribution and current behavior characterization.
Real PostgreSQL cases include actual INSERT failure rollback/retry, Task and
idempotency participation, direct competing piece/pack reservations without Sales
numbering serialization, and existing PERF26 lock/query/metadata-repair checks.

Record actual outcomes with the frozen manifest. A worker's test pass is not
independent AI verification. Combined-source review, actual connected-browser
screenshots/actions, persisted readback, bounded UI stress and human visual
acceptance remain required. Do not mark all Sales or Fulfillment complete from
this operation. No production write, migration, push, merge or deployment performed.

## Review corrections: shared mapping and actual service results

The first candidate `747caa9` accidentally removed Finance's existing
`InvoiceStatusType` during adoption of an earlier Sales mapping file. The
separate correction `8fe0905` restores the exact integration-base conversion,
`Mapped[InvoiceStatus]` annotation and enum-member default. SQL DDL equality
alone did not catch this runtime regression; existing Finance enum reload,
expiration, API, payment and independent roundtrip/atomicity tests must accompany
the Sales tests whenever this shared mapping changes. All 32 original candidate
paths were compared to the integration base; no other unrelated rollback was
identified. Preserve the original evidence and correction chain.

Creation now returns an actual `SalesOrderDetail` from its service and declares
that return type in its route. It validates the same enriched/signed payload the
HTTP response model already used. The shared serializer used by history, list,
get, update and confirm remains unchanged. The nested model's `composition` was
already excluded by the existing HTTP response model; no wire field is removed.

The reserve-stock service returns `SalesStockReservationOut` for both live work
and saved replay. The route declares that response model, so OpenAPI now names
the existing reservation and shortage shapes. Package display identity may still
be null for legacy partial allocation; shortage brand identity may still be null.
The same JSON shape is saved for idempotency, with response validation before
the existing store/outer commit. No allocation, locking, permission or retry
policy changes. Invalid internal result shapes now fail validation rather than
silently leaving the service as an unstructured dictionary.
