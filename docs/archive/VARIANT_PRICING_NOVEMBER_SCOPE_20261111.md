# November pricing request scope — 11 November 2026

Owner instruction: “this is the latest prices only keep the undpriced variants
created after nov 1 do not request for usluga variants”. Source: `11-11.xlsx`.
The earlier USD 0.30 addition, exact model-and-variant preference and globally
unique variant fallback remain authorized. Deployment is authorized; the owner
waived 30-minute monitoring. Earlier two measured performance exceptions are not
blanket exceptions for this release.

Base: clone_main c02f83ac03d22d98575ed23887e883925b3c3581. Verified production
before edits: blue 20261110_135430, application cfe03885e03e4310e9b7c86ec9649ff350565d65,
manifest 1abc90b9e4b87f3e16ef0e255fe1829d15e9b510d6f61f1b2c030baf33fa89a3,
schema 0156_variant_price_workflow. This candidate needs no schema migration.

Only standard, unpriced variants with Model.created_at from 1 November 2026,
00:00 Asia/Tashkent (31 October 19:00 UTC), qualify for active pricing. Request
creation dates do not qualify older variants. Automatic passport creation skips
excluded variants without blocking Cutting. Manual creation, repricing, cost
updates/submissions and Finance approval cannot bypass the rule. Pending views
and pending Excel reports use the same policy. All/history reports retain old
records and existing prices. The obsolete priced-variant repricing control is
removed. No Sales order prices, quantities, manufacturing or inventory rules change.

Excluded active requests are explicitly cancelled, never deleted. Submitted
costs, submission timestamps, source evidence and history survive cancellation
and passport unlinking. The administrative CLI defaults to read-only preview;
apply requires an exact reviewed request/model/revision list, locks Models before
requests and commits once. A stale list refuses the whole operation. It requires
an active global Finance approver, not merely a factory wildcard.

Workbook SHA256: d9086c9af59cbd1388bb7e9d65faa37b5fce12f3ac6f3c93366eac143c3bb1ee.
Reviewed manifest v3 canonical SHA256:
697865bce5c759d405c0edfb546749b2fe26056da751a073430c2fbcd378a162.
There are 9,670 positive source rows. Read-only comparison selected 6,435 standard
variants: 6,421 existing prices already agree and 14 missing prices total USD83.60.
No existing priced amount changes. Column F plus USD0.30 is applied exactly once;
blank F with a cached G value of USD0.30 is excluded. Exact structured pair wins
over punctuation-compatible code matches; variant-only uniqueness includes every
catalogue, including Usluga. Ambiguities are excluded.

Initial queue preview: retire 131 older requests, retain 36 recent unpriced
requests (33 Milana, 3 Eco Cotton standard), zero Usluga. All retirements have no
submitted costs. Eleven of the fourteen fills intersect the older requests:
retire the fresh reviewed exclusions FIRST, then import the fourteen prices.
Normal factory activity can change previews; recheck identities and revisions
immediately before writes. Back up production PostgreSQL before material changes.
Neither this document nor initial counts establish that production was changed.

Domain owners: Planning/Finance/Catalog Ismail, independent human reviewer
Mirshoir; Production Mirshoir, reviewer Ismail; Shavkat supplies operator business
acceptance. Implementation /root; independent AI review /root/pricing_review.
Human QA-master acceptance is not claimed by AI test results.

Local evidence: 53 focused SQLite workflow/import/scope cases; 9 real PostgreSQL
cases including whole-transaction commit-failure recovery and retirement racing
with Finance approval/import; 53 offline required-gate validator cases. Ruff,
compile, frontend ESLint, strict TypeScript and pricing workflow regression pass.
The required PostgreSQL inventory adds exactly three case identities (648 total).
Evidence is private under outputs/pricing-november-scope; no workbook, credentials
or production dumps are committed.

Remaining release gates: independent final source review, exact-commit official CI
and required PostgreSQL gate, immutable artifact/source verification, staged real
browser and complete read-only performance/health checks, fresh backup and exact
data previews, post-write readback and protected business-fact verification.

Human visual checklist: open Purchasing and Accessories as administrator; verify
only recent unpriced standard variants remain; verify old and Usluga requests
cannot be submitted; open Finance pending/approval and full Excel; verify history
retains cancelled rows and imported prices retain source; create an ordinary
Cutting Passport for an excluded variant and verify normal downstream handoff on
isolated QA data. Production business data must not be fabricated for this check.
