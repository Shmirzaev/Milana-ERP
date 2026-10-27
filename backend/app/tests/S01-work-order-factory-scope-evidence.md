# S-01 work-order mutation factory scope

Base: `clone_main` at `5391e327`; branch: `codex/s01-work-order-factory-scope`.
Edits made in place under real `backend/` paths.

## Handler enumeration before the fix

| Protection | Direct work-order mutation handlers |
| --- | --- |
| Missing | `update_wo`, `start_wo`, `collect_printing_wo`, `complete_wo`, `complete_cutting_with_shortage`, `split_cutting_work_order_batches`, `add_extra_cutting_batch` |
| Existing `require_work_order_factory_access` | `update_cutting_batch`, `update_usluga_report_pieces`, `update_usluga_bundle_size_counts`, `post_cutting`, `approve_usluga_cutting_batch`, `reject_usluga_cutting_batch`, `update_cutting_record_details`, `finish_milana_cutting_and_print`, `update_cutting_bundle_quantities`, `post_printing`, `post_sewing`, `post_quality` |
| Same helper delegated to service | `replace_cutting_material` via `replace_cutting_material_batch` |
| Existing packaging factory/department protection | `receive_packaging_from_sewing`, `post_packaging` via `require_packaging_work_order_access` |

No separate block/unblock or reassign routes exist in `production.py`.
PATCH owns reassignment and status changes (including pause/resume).
Broader production-order planning, deadline cascade and admin repair operations
also affect work orders indirectly; they are not direct work-order mutation routes
and were not modified by this narrowly scoped fix.

Each missing direct handler now calls the existing helper immediately after the
work-order 404 check and before business logic or mutation.

## SQLite fail-before / pass-after

New fixture follows `test_quality_check_factory_scope.py`: MIL, BST, ECO,
scoped users, and explicit factory claims in authenticated session tokens.

Before fix: **60 failed, 31 passed** (9.99 seconds).
All 60 cross-factory cases expected 403:

- 42 instead returned **200**: start, complete, update, reassign, pause, resume,
  and collect across all six directed factory pairs.
- 18 instead reached operation validation and returned **400**: shortage,
  split and extra-batch requests against the printing fixture. These prove the
  factory gate must precede operation checks; they do not claim those mutations
  succeeded before the fix.

After fix, new regression plus existing quality-scope tests:
**103 passed** (9.79 seconds). Denials preserve work-order state and audit counts.
Same-factory requests and explicit selected-factory sessions remain allowed;
missing work orders remain 404.

```sh
python -m pytest -q backend/app/tests/test_work_order_factory_scope.py
python -m pytest -q backend/app/tests/test_work_order_factory_scope.py \
  backend/app/tests/test_quality_check_factory_scope.py
```

Database for all these tests: the normal isolated SQLite test database.
No PostgreSQL run is claimed or needed for this authorization change.

Logs: `/private/tmp/s01-before.log`, `/private/tmp/s01-after.log`,
`/private/tmp/s01-suite.log`.

## Full suite and static checks

**1,960 passed, 47 skipped, 2 warnings in 579.27 seconds**, using the normal
SQLite fixtures. On this Mac, ran from the temporary external font environment
already used for S-06, supplying Arial/Arial Bold at the Windows font paths the
existing PDF/label code expects. No repository font or production changes.

```sh
cd /private/tmp/s06-suite-env
python -m pytest -q \
  -c /Users/murmurbek/Code/Milana-ERP/pyproject.toml \
  /Users/murmurbek/Code/Milana-ERP/backend/app/tests
```

Ruff (`backend/app`), Python compilation and `git diff --check` passed.
No merge or deployment; no production data touched.
