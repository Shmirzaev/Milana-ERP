# Variant paid-operation reconciliation — 2026-09-29

Production data repair applied using reviewed script commit `0bef50e8`; application deployment remains paused.

- Reviewed plan SHA-256: `ba0280b3d949db973339b68a8b7eee36b7111857e478e6dd241e657a62228781`.
- Updated 282 existing model/variant records in 177 exact catalog families, covering 520 factory lists and 809 target/factory assignments. Seven existing parent-model records received operations. No model record was created.
- Copied 31,113 operation entries into empty or exact untouched default lists. Existing configured lists, other factory operations, identity, prices, sizes, BOMs, payroll records and issued labels were preserved. Internal import identities were excluded. All updates and 809 audit events committed atomically after preimage checks.
- PJ1236: the user explicitly selected V-6120 as the source. Its 41 Milana operations were saved to PJ1236, V-6121, V-6123 and V-6146. Existing V-6120 and V-6147 lists were preserved; five code/section metadata differences between those donors were not silently rewritten.
- Exact unpriced five-row application defaults were treated as placeholders, never as authoritative donors. Any modified default counted as configured data. Comparisons ignored only operation storage IDs and legacy source IDs; every other field and list order had to agree.
- 27 model families / 77 factory lists still have conflicting configured donors and were left unchanged. Evidence and full donor/target choices: `outputs/reconciliation/review.md`, `plan.json`, `result.json`, `verification.json` in the task worktree.

## Verification

- Six new planner/apply tests passed, covering defaults, real-rate conflicts, explicit choices, factory/catalog/legacy isolation, protected fields, repeatability, stale preimages and altered-plan rejection. Ruff passed. The prior application change had already passed 1,044 backend tests and frontend validation/build.
- The transaction compared matching before/after fingerprints for 7,260 issued labels and 2,628 payroll records, model sizes/BOMs, all non-operation model fields, and all untargeted model rows. No correctness claim relies on live row counts being static outside that transaction.
- Active application is unchanged: green `20260928_114232`, manifest `b95dcf4c46a00c1235efc56ff0966c824c2d5e9d4ac90f8428464fb0bfabf230`; blue `20260926_094041` remains rollback; database revision `0133_storage_customers` unchanged.

- Independent post-commit verification matched all 282 changed-record fingerprints; repeat planning found zero further applicable updates. All six PJ1236 records have 41 operations, totaling 8,230 UZS per piece. All four internal/public health/login checks returned 200.

## Backup

- `/opt/milana-erp/shared/backups/milana_erp_pre_20260929_033219.dump`: 54,548,179 bytes, mode 0600, 1,203 verified restore objects.
- Dump SHA-256: `278d53b9eca74a9732c6aefee5362cc63bcab98479f8113fb9b73ffaa5cf60c7`.
- Restore-list SHA-256: `f56d88d15a488376018d9e732e351524294e904c9c9ded71736adeea96af1707`.

## Conflicting families left unchanged

| Model family | Factories requiring a source choice | Configured source versions |
| --- | --- | --- |
| pg10502 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| pg10515 | milana | milana: 2 |
| pj1173 | milana, besttex, eco_cotton | milana: 3; besttex: 2; eco_cotton: 2 |
| sj4004 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| sj4010 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| sj4013 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| sj4015 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| sj4022 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| sj4035 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| tj2080 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| tj2092 | milana, besttex, eco_cotton | milana: 3; besttex: 2; eco_cotton: 2 |
| tj2199 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| xj3013 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| xj3044 | milana, besttex, eco_cotton | milana: 3; besttex: 3; eco_cotton: 3 |
| рj1013 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| рj1102 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| рj1108 | milana | milana: 3 |
| рj1110 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| рj1142 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| рj1183 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| тj2026 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| тj2096 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| тj2189 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| хj3030 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| хj3033 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| хj3062 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
| хj3128 | milana, besttex, eco_cotton | milana: 2; besttex: 2; eco_cotton: 2 |
