# Warehouse Stock speed verification — 2026-10-16

The candidate reduces measured server-side stock loading from a median of
20.7557 seconds to 3.4721 seconds (83.27% faster). It has not been deployed.
Public network time and browser rendering are not included in this measurement.

## Cause and change

The browser aborts JSON requests after 12 seconds. Production logs recorded
Storage Map responses taking 21–80 seconds. A read-only profile measured 17.7
of 21.3 seconds in family-picture resolution, including 15.3 seconds decoding
JSON. Model technical JSON is large and was repeated for each joined picture.

The fix selects only the small identity JSON section once per family member,
then fetches image metadata separately. Storage Map loads its displayed model
fields and resolves images in bulk. It no longer hydrates complete technical
details or unrelated model BOMs. All batches are limited to 400 IDs/keys.
Image blobs remain deferred. The 12-second timeout is unchanged.

## Production-data comparison

Source baseline: live green `20261015_095050`, immutable application commit
`b0f960c780bd3793bc20d71dd9e76d9b9c12fde0`. Both production source manifests
passed full verification and matched `deploy/production-base.json` on
`clone_main` at `4dd8ff4ebe18e4a027671f3259a832d000bd429b`.

The benchmark ran sequentially in a separate Python process using a single
PostgreSQL `REPEATABLE READ`, `READ ONLY` transaction. Fresh ORM sessions were
used for each sample. Baseline modules ran first; candidate module source was
loaded only into that diagnostic process. Serving workers and files were not
modified. Every sample had a 45-second process alarm and a 12-second SQL
statement limit. The transaction was rolled back afterward.

Measured operation: `storage_map(include_unplaced=True, stock_kind="standard")`,
followed by FastAPI JSON conversion and deterministic JSON serialization.

| Version | Samples, seconds | Median |
| --- | --- | --- |
| Baseline | 20.8973, 19.5442, 20.7557 | 20.7557 |
| Candidate | 3.5283, 3.5575, 3.4800, 3.4491, 3.4532, 3.4721, 3.4513 | 3.4721 |

Every sample produced the same complete normalized response:

- SHA-256: `7097cef715715f203a15b7be9eed63e62c0ad99442e9783bef3ea3e310ca3f8b`
- 1,252,148 bytes; 1,804 placement rows; 6,739 packages.
- Picture URLs, quantities, ordering, placement/search results and all other
  response fields matched exactly.

Seven candidate samples are useful repeated evidence, not a load test or a
statistically reliable tail-latency guarantee. A deployment still requires its
normal immutable-image, health, signed-in and performance gates.

The diagnostic harness and raw samples are retained in this task's worktree:
`outputs/warehouse_speed_probe.py` and `outputs/warehouse-speed-final.txt`.

## Regression verification

- 36 focused model-image, projection, legacy-stock, warehouse-report and
  package-lifecycle tests passed.
- The broader selection completed with 110 passed, 19 failed and 10 optional
  PostgreSQL tests skipped. Each failing test also failed on untouched
  `clone_main` in a separate baseline worktree.
- Three Storage Map tests had obsolete per-variant-picture and exact-query
  expectations. Their fixtures now explicitly identify distinct model
  families and include large unused technical payloads. They check unchanged
  picture results, no binary/full-details fetch, and bounded query growth at
  1, 50 and 401 models. The final combined projection/Storage Map run passed
  13 tests.
- Sixteen remaining inherited failures concern package context/label query
  expectations, embedded label pictures, catalog picture expectations and
  pending-correction print grouping. They remain outside this fix. No new
  failing test was observed.
- New behavioral cases cover primary/base precedence, camel-case identities,
  malformed/missing identity metadata, catalog/factory isolation, legacy
  picture evidence, missing images, cache invalidation, partial dispatch,
  first-grade stock, date/search filters and placed/unplaced stock.
- Scoped Ruff, Python compilation and `git diff --check` passed.

No production business data, schema, permissions, runtime configuration or
release was changed. No frontend timeout or layout change was made.
