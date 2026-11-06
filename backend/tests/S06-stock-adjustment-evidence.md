# S-06: concurrent stock adjustments

Base: `clone_main`, commit `5d335439c56308ecaa7103788aa453b0acc6815c`.
Branch: `codex/s06-stock-adjustment-locks`; edits made in place under `backend/`.

`test_stock_adjustment_postgres.py` runs two independent SQLAlchemy sessions
against the same batch. It pauses transaction one after its batch SELECT and
starts transaction two. Before releasing transaction one, it requires either
transaction two to read the batch (old code), or PostgreSQL `pg_blocking_pids`
to confirm transaction two waits on transaction one (fixed code). No serial
execution or SQLite substitute is accepted.

Each case creates and drops its own schema in local PostgreSQL
`localhost:5433/milana_test`; public tables are untouched.

| Case | Before fix | After fix |
| --- | --- | --- |
| Batch deltas +10 and +20 from 100 | Final 110, ledger expects 130: FAIL | Final 130, ledger expects 130: PASS |
| Absolute targets 110 then 120 from 100 | Final 110, deltas +10/+20, ledger expects 130: FAIL | Final 120, deltas +10/+10, ledger expects 120: PASS |

Original code: **2 failed**, both with `Lost update: on hand 110.0, ledger expects 130.0`.
Fixed code: **2 passed** (3.43 seconds).

Run with `S06_POSTGRES_URL` set to the local PostgreSQL connection URL:

```sh
python -m pytest -q -s backend/tests/test_stock_adjustment_postgres.py
```

The test sits outside `app/tests` because its conftest explicitly forces SQLite.
The normal existing suite is run separately with `python -m pytest -q`.

The endpoint locks the item (also serializing adjustments with no existing batch)
and all batch rows before computing the current total and delta. The helper locks
its batch rows before changing quantities. Both use the existing PostgreSQL
`lazyload(StockBatch.item)` / `with_for_update(of=StockBatch)` reservation pattern.
`populate_existing()` refreshes any already-loaded ORM quantities after locking.

No migration, production data change, merge, or deployment.

## Full existing suite

SQLite, unchanged `backend/app/tests/conftest.py` database isolation:
**1,832 passed, 47 skipped, 2 warnings in 557.49 seconds**.

The first run from the repository had 1,828 passed, 47 skipped and four failures
because this macOS machine lacks the Linux/Windows font paths expected by the
PDF/label code. All four also failed on the original `clone_main` route code
(targeted baseline run: 4 failed in 11.17 seconds). No application fix was made
for this environment issue. Temporary symlinks outside the repository supplied
macOS Arial and Arial Bold at `C:/Windows/Fonts/arial.ttf` and `arialbd.ttf`.
The entire suite was then rerun from that temporary directory:

```sh
cd /private/tmp/s06-suite-env
python -m pytest -q \
  -c /Users/murmurbek/Code/Milana-ERP/pyproject.toml \
  /Users/murmurbek/Code/Milana-ERP/backend/app/tests
```

Ruff (`backend/app` and `backend/tests`), Python compilation and `git diff --check`
also passed. Original/fixed PostgreSQL logs and both suite logs are retained under
`/private/tmp/s06-{before,after,suite,suite-fonts,baseline-failures}.log`.
