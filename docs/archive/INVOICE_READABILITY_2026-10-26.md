# Invoice readability release — 26 October 2026

## Invoice readability deployed (2026-10-26)

- Current backend/frontend: green `20261026_085306`, exact application `439555a77ef583b1b212398e16ecd52ced786e45`; retained running blue rollback `20261026_055538` / `dc8d1aea60ace79ff15dfb1900a1b96b2e5108f6`. Both source manifests, immutable images, slots and symlinks agree. Manifest `9511b57bf62fd3142c865f3bb07aaf3e2f1053629f90c8521a652cd6da9139e2`; database unchanged at `0149_besttex_cutting_access`.
- Customer/transport details use 11 pt; all product headers, descriptions, sizes, quantities, weights, prices and totals use 9 pt. The original SVG logo has its own proportional header area. Long text wraps and rows grow; A4 repeats table headings across pages. Excel uses matching configured font sizes, wrapping and numeric widths, preserving numeric values and hidden-price behavior.
- Invoice-only deployment from verified live source preserved the newer factory fixes. No refactoring, permissions, schema, stock, shipment, invoice value or other business-data changes were introduced. The matching patch is prepared separately for `clone_main` in draft PR #310; its pending namespace work was not deployed.
- Exact immutable CI [40295387623](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40295387623), affected regressions, independent code/ops reviews, 12 EN/RU/UZ price-mode/PDF cases, repeated multi-page headings, bounded 80-render/max4 integrity check, signed candidate/public invoice/Excel parity and actual browser screenshots passed. The existing shipment snapshot remained unchanged. Local full Windows pytest did not finish and local Turbopack rejected an external dependency junction; neither is counted as a pass. Exact final-commit CI supplies the full backend and standard production-build gates; local strict types/lint/contracts and a 98-route webpack build also passed. Excel desktop/physical-paper output was not exercised; workbook rendering and Windows Calibri measurements were checked.
- Fresh verified 0600 backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20261026_085306.dump`, 91,962,336 bytes, 1246 restore objects; SHA-256 `bd1f793756b2de8071b212c1d83672b4afa017bc3819ba744b51ddd38b83a129`. All four immediate health checks, router/runtime/rollback checks and unchanged performance budgets passed. No 30-minute timed observation was performed, as expressly waived by the owner. Detailed evidence follows.
- The first closing public gate failed inventory-stock p95 `146.14 -> 186.60 ms` (+27.69%), so both roles were gracefully rolled back to blue and all four health checks passed. A single matched 200-sample diagnostic reproduced p95 `182.87 ms` on the old public release while direct blue/green were `37.87/32.31 ms`. The original before/after benchmarks also changed originating containers. One predeclared corrected attempt used the exact same retained-blue client container/image for both phases, with all five queries, 120 samples, warmups, spacing, percentile calculation and original limits unchanged. Its stock p95 was `176.45 -> 182.02 ms` (medians `142.22 -> 141.01 ms`). The full corrected gate passed; the original failure, rollback and every raw sample remain recorded. The public-path tail variation's precise cause remains unproven; this relative pass is not a claim that the original slowdown is resolved. No network or production configuration was changed.


- Backend immutable image: `ghcr.io/shmirzaev/milana-erp-backend@sha256:598255938f2450383cd53a913c67d6f44ae670a44ac9f7d8e27c3ec19c832e72`.
- Owner scope and authorization: invoice fix only; deploy without the 30-minute observation; no refactoring job. The owner explicitly authorized Codex implementation because the prescribed MiniMax runtime was unavailable. Technical evidence is AI verified; factory/operator visual acceptance remains pending and is not inferred from deployment authorization.
- Final affected suite: 96 passed. Exact runtime CI full backend: 3,887 passed, 311 optional skips; separate PostgreSQL suites included 108 and 176 passing tests. Skips are not counted as passes.
- Closing disk usage: backend 79.36%, frontend 76.22%. Capacity remains an operational constraint for the next release; no cleanup was performed.
- Frontend immutable image: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:047fc6847bc509c89282ef80fa56bb009745cedce0fff5225bcd9bebf5aed9d0`.
- Source archive SHA-256 `b65d7389924c814813ce6869ec89ad4fa82313a4c30c53d44d27d1ed278db29a`; 1436 exact Git files verified.
- Worktree `C:/ERP/.codex-work/invoice-readable-20261026`, branch `codex/invoice-readable-20261026`, runtime commit `439555a77ef583b1b212398e16ecd52ced786e45`. Application branch pushed; no integration/refactoring merge. Invoice-only clone_main patch: `C:/ERP/.codex-work/invoice-readable-integration-20261026`, `codex/invoice-readable-integration-20261026`, commit `70c4bf3c`, draft PR #310, not merged or deployed.
- Existing real read-only QA shipment: `SH-2026-000160`. Print table cell text, workbook values and frozen snapshot match retained blue; only presentation changes.
- Evidence, raw measurements, CI logs, screenshots and local limitations: `outputs/deployment/` and `outputs/invoice-qa/` in the release worktree. Temporary QA gateways are stopped after verification. No cleaning/deleting releases, images, backups, volumes, uploads or manufacturing records was needed.
- Retained rollback readiness verified without switching traffic. Run `C:/ERP/.codex-work/qr-besttex-nav-20261026/.venv/Scripts/python.exe outputs/deployment/rollback.py` from this worktree for read-only readiness. Add `--apply` to restore blue backend first, then frontend, repoint both current symlinks and run all four health checks. No database downgrade.
- Operator acceptance checklist: open existing invoice in EN/RU/UZ; verify 11 pt customer/delivery and 9 pt product rows; one separated sharp logo; long sizes/descriptions wrap; A4 at 100% continues with repeated headings; hidden-price cells remain blank; Excel keeps numeric totals and matching configured fonts. Production/operator acceptance is separate from technical deployment authorization.

## Integration addendum — 26 October 2026

The release-time statements above about a separate draft patch and `70c4bf3c`
being "not merged or deployed" are preserved as history. The invoice port has
subsequently merged through [PR #310](https://github.com/Shmirzaev/Milana-ERP/pull/310)
as `cdcbdfe5e7cfeb08a65e6a86da27fc7b6175733d`, whose verified Git tree is
`aabd33becc5662469eb2ba408f832fb0059f1229` (parents `b92ee8f` and `623e35f`).
This records the port's integration state, not a second deployment or a new
verification of the production observations recorded above.

The refactor integrator is preparing an isolated successor from frozen candidate
`d0920f6367b702f63c88d5940cf1b44155b34aec` plus that merge. This successor is
**not deployed, not AI-verified and not human-approved**. Its exact combined source
requires applicable technical checks and actual invoice/browser/export inspection,
persisted readback and bounded integrity checks. Earlier invoice-only release
results and d092 screenshots remain evidence for their original sources; they
must not be relabeled as successor execution. Human technical/visual approval
remains separate from both PR merge and the prior invoice deployment authority.

The imported `deploy/production-base.json` records application
`439555a77ef583b1b212398e16ecd52ced786e45`, release `20261026_085306`, manifest
`9511b57bf62fd3142c865f3bb07aaf3e2f1053629f90c8521a652cd6da9139e2` and database
`0149_besttex_cutting_access`. These are historical upstream assertions retained
without alteration; this documentation review contacted no production host or
database. The candidate's Alembic files end at `0148_second_grade_packages` and
do not contain migration 0149. The earlier successor study did not establish the
recorded runtime commit's ancestry/content relative to the refactor. Reconciliation
of exact release source, newer factory fixes, migration chain, manifests and slots
is ongoing before any future deployment. The six-file invoice port alone cannot
close that gap; no missing migration is fabricated and no production fault is inferred.

Ismail's full-system mentor-discipline objective and explicit Codex-subagent
authorization remain in force. Schema-owned writes, canonical enum contracts and
all domain ledgers retain their operation-level gates; neither this port nor its
historical release accepts the whole ERP. See [current context](../PROJECT_CONTEXT.md)
and [the engineering workflow](../ENGINEERING_WORKFLOW.md).
