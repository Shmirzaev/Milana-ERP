# ECO fabric inventory and Qolip uploads — 5 November 2026

## User scope and baseline

User requests: make the ECO COTTON fabric inventory shown in the screenshot look
like Milana fabric inventory; accept `.gem` and `.gemx` in Model qolip uploads.
The earlier instruction remains: base changes on production, merge clone_main
later. No push, merge, deployment or production business write is authorized.

Continue clean task worktree `C:/ERP/.codex-work/cutting-search-order-fixes-20261105`,
branch `codex/cutting-search-order-fixes-20261105`, prior commit `ac3d6e041`.
This branch descends from exact active production `488f3d654`, release
`20261105_065721`; rechecked backend manifest is
`e6c603d4c1954c64a75962cf189427eb5e316c039ea23de4699b9bd4f3112095`.
The earlier four fixes remain committed and preserved, not deployed.

Human owners: Inventory/Catalog Ismail; reviewer Mirshoir; business acceptance
Shavkat. Actual Codex `/root` owns inventory presentation and integration;
`/root/cutting_reject_backend` owns the disjoint Qolip upload paths/tests.
A separate Codex reviewer must independently inspect both slices.

## Study and intended behavior

- Actual live `/inventory?group=materials` and its source establish the reference:
  picture, batch identity, material/color, quantity/reserved/available, unit/cost,
  supplier/warehouse, receipt/QC details and actions; mobile uses material cards.
- ECO `/eco-inventory?kind=fabric` already returns all needed information through
  `EcoBatch.receipt_details`. Render only that exact batch's picture and metadata.
  No shared-stock queries, new totals, mutations, schema or lifecycle are needed.
  Retain the existing ECO receive, history, quality, consumption, pagination,
  factory/permission and uncertain-request recovery behavior. Accessories retain
  their current presentation. Do not add unsupported reports or filters as decor.
- Standard and Usluga model upload aliases share Catalog's upload service. Extend
  only the pattern attachment allowlist and its UI picker. Preserve size limits,
  authorization, safe storage names and original bytes; files remain authenticated
  attachments. Model/material pictures and unrelated document endpoints retain
  their existing allowed formats. No guessed proprietary format magic is required.
- Fixed vocabularies remain existing ECO kind, quality status and image_type.
  No new enum values or business states. No broad layer/type refactor is in scope.

## Acceptance and evidence

Record actual tests, connected-browser screenshots, isolated upload/readback,
bounded integrity checks and independent review here. Missing required checks
are BLOCKED, never PASS. Human acceptance remains separate.

Human checklist: ECO fabric rows resemble the Milana reference, batch photos and
metadata stay exact, quantities and QC/consumption controls remain usable on
desktop and phone; accessories/history still work. Upload and download `.gem`
and `.gemx` from a model's Qolip tab; image-only pickers still reject them.

## Qolip implementation and backend evidence

Actual implementer: Codex `cutting_reject_backend`; Catalog human owner Ismail,
reviewer Mirshoir. A separate Codex `independent_review` inspected the final slice;
human and connected-browser acceptance are recorded separately by the coordinator.
The six changed/new runtime/test files (uploads helper, Catalog service, main file
download route, two CAD test modules and model-detail TSX) have aggregate SHA-256
`bde82965586bb6ab50ac07947d7db47c70f7fb06344699560012c9b2cc2c9b19`
(sorted repository-relative path, NUL, raw bytes, NUL). The coordinator records the
final combined commit; no worker commit/push/merge/deployment occurred.

The existing standard `POST /api/models/{mid}/images/upload` and ECO Usluga
`POST /api/usluga/models/{mid}/images/upload` contracts are retained. Only a
normalized `image_type=pattern` enables `.gem`/`.gemx` (case-insensitive extension).
The explicit `MODEL_PATTERN_CAD_EXTENSIONS: frozenset[str]` does not expand
SAFE_DOCUMENT_EXTENSIONS, raster uploads, BOM photos or Sales printing attachments.
The pattern picker includes the two extensions. The original filename is retained
and displayed, and the link suggests it through the download attribute. The
server's Content-Disposition uses the generated model/UUID storage basename;
downloaded bytes and extension are preserved, not necessarily the original name.

CAD bytes are treated as opaque, bounded at20 MiB using chunked reads. Empty and
oversized bodies, known executable headers and recognizable HTML/script headers
refuse before file/row persistence. Browser MIME variation is accepted but stored
content type is always application/octet-stream. No unknown proprietary magic is
required, and the synthetic fixtures do not prove genuine Gemini compatibility or
provide a general malware-scanning guarantee. Existing permission/factory/catalog
scope checks, worker-side scope recheck, cancellation/commit cleanup and audit
remain in the original upload lifecycle. New CAD files keep their original bytes
without image conversion or thumbnails and download only with the existing auth
token guard, as octet-stream attachments with nosniff. The legacy database-byte
fallback is unchanged; the new upload path always stores file_data=None and uses
the authenticated filesystem route.

No DTO, enum value, database definition or migration is added. Existing fixed
image_type/catalog_scope values and the legacy upload persistence implementation
are intentionally retained; this is not full Catalog type/schema-write adoption.

Automated evidence:

- PASS: new HTTP suite31 cases plus existing Production flow/security cases110:
  141 passed, four inherited warnings,49.31 seconds. Standard and Usluga aliases
  preserve byte-for-byte downloads and metadata across mixed/uppercase filenames,
  browser MIME variation and a traversal-shaped original filename. UUID targets
  remain inside the configured directory. Authenticated attachment headers,
  anonymous denial, pattern-only acceptance, independent BOM/Sales denial,
  permission/catalog-scope denial, executable/HTML/empty/oversize refusal and
  acceptance at exactly20 MiB were checked.
- PASS: real PostgreSQL worker lifecycle suite5 new cases plus existing15 upload
  scheduling/lifecycle cases:20 passed, four inherited warnings,7.18 seconds.
  Saved original CAD bytes/content type/name, finalized audit hashes, standard and
  Usluga persistence, post-file-write catalog scope recheck and injected worker
  failure rollback/file cleanup passed. Eight total uploads with two in flight
  created eight unique complete files, eight pattern rows and eight audit entries.
  No required PostgreSQL test skipped.
- PASS: Ruff and compileall for the five affected Python paths; diff whitespace
  check. Frontend full checks and actual browser evidence belong to the combined
  coordinator run.

Failures retained: the first new roundtrip test demonstrated `.gem` HTTP400 before
the change; the suite passed after it. An initial eight-simultaneous stress attempt
on a six-connection fixture pool failed after65.50 seconds (four earlier cases
passed): retained request Sessions consumed the pool before worker Sessions could
check out connections. The final bounded test uses eight total/two in flight and
passes. This does not establish support for eight simultaneous uploads on a
six-connection pool; connection budgeting remains a limit of the existing upload
lifecycle, outside this narrow format extension. The attempted targeted process
stop found that test processes had already exited; no application process stopped.

Isolated actual-UI setup: owned container `milana-qolip-qa-20261105`, PostgreSQL16,
only `127.0.0.1:15438`. Test modules create/drop separate synthetic schemas; no real
ERP database or business data was used. Public schema contains private QA accounts
with example.com addresses, standard/Usluga models and synthetic ECO fabric/accessory
batches/history. The existing0084 generated columns/index were applied only to this
disposable schema for real Catalog reads; no migration file or live migration ran.
The first temporary setup invocation lacked PYTHONPATH and failed before imports;
the corrected invocation completed. Private environment/credentials and clearly
synthetic `qa-pattern.GEM`/`qa-pattern.GEMX` stay outside Git under TEMP. Keep this
owned container/files until the coordinator finishes browser/readback, then remove
only those verified task-owned resources.

## Combined presentation and runtime verification

The new EcoFabricStock presentation uses the existing ECO API and exact batch
receipt_details. It follows Milana's picture/batch/material/stock/cost/supplier/
receipt columns, with readable batch cards below the desktop breakpoint. Existing
QC, consumption, receive, history, accessories, pagination, permission and retry
handlers remain the owners of their behavior. No totals or unsupported filters
were invented; there is no inventory backend, migration or permission change.

- PASS: actual connected Edge desktop inspection in English and Uzbek, plus
  390x844 phone cards in Uzbek and Russian, using disposable PostgreSQL/FastAPI
  fixtures. The two batches of the same item retain separate burgundy/navy images,
  width/GSM/cost/receipt metadata and quantities. Screenshots are retained locally
  under ignored outputs/qa: eco-fabric-desktop-en.png, eco-fabric-desktop-uz.png,
  eco-fabric-phone-uz.png and eco-fabric-phone-ru.png.
- PASS: exact-batch consumption form opening showed QA-ECO-LOT-1 and available400;
  Cancel closed it without a write. Attempting to hold the batch with36 reserved
  produced the expected409 release-allocation refusal and retained passed status
  and balances. This is a refusal check, not a successful QC save. History and
  accessories remained usable with their synthetic receipt/100pcs records.
- PASS: the new component rendering/action suite checks EN/RU/UZ, exact batch
  images, receipt fields, read-only permissions, disabled/zero-stock/uncertain
  actions and empty rows. Existing ECO decimal/retry/translation tests also pass.
  Final npm run build passed every configured suite and the optimized Next build;
  strict TypeScript, scoped ESLint and git diff --check passed. The build restored
  next-env.d.ts naturally; no generated declaration change is included.
- PASS: standalone HTTP against the running loopback API uploaded .GEM and .GEMX
  to each standard/Usluga fixture (four201 responses), reread original filenames
  through model detail, and downloaded all four byte-for-byte. Synthetic payloads
  were65 bytes, SHA-256 eb1a20abaeaf7a0f565c955c97a9878f4da2a033e4230109fd08a054f092f9d2.
  Authenticated downloads returned200/octet-stream/attachment/nosniff; anonymous
  downloads returned401. The two ECO batches retained exactly436/36/400/passed and
  25/25/0/hold (balance/reserved/available/QC). Non-secret readback is retained in
  ignored outputs/qa/qolip-http-readback.json.
- PASS: independent Codex review found no actionable source blocker. Reviewed
  inventory component/page/test/package SHA-256 prefixes are58368c74c937,
  132280e05a98,2f951426452d,e0119610cb56; the CAD aggregate is recorded above.
  Runtime code remained frozen through the final combined checks.
- BLOCKED: browser file-picker upload through the complete UI. The actual Qolip
  picker accept attribute included .gem,.gemx, but automated file selection refused
  because Edge extension file access is disabled. A native fallback stopped when
  Computer Use could not establish the browser URL for policy enforcement. No
  security setting was changed or gate waived. API success does not replace this
  missing complete browser upload/download check or genuine Gemini-file acceptance.

The inherited common.noData i18n-check failure and extension-injected
bis_skin_checked/bis_register hydration warnings remain as recorded by the earlier
task. No zero-console-error or whole-system/i18n completion claim is made.

## Closing state and remaining acceptance

Both production hosts were rechecked at close and still resolve current to
20261105_065721. Fresh fetch found origin/main1a067b01 and clone_mainc5a0d2e4;
the owner-requested production-based candidate remains separate for later reviewed
integration. No production database or business data was touched. Only disposable
QA data was created; no application migration, push, merge or deployment occurred.

The owned loopback frontend/API were stopped, and the identity-checked
milana-qolip-qa-20261105 PostgreSQL container plus its anonymous volume were removed.
Automatic command review rejected both recursive temporary-folder cleanup and the
narrower removal of its three private JSON configuration files, stating only
blocked by policy. Those task-owned TEMP files remain; no cleanup success is
claimed and no alternate deletion mechanism was used. Their database is removed.
Screenshots and non-secret build/readback evidence remain under ignored outputs.

Inventory source/automated/visual checks pass; the complete Qolip browser upload
gate remains BLOCKED. Human design/file acceptance, clone_main integration and
release authorization remain pending. The final commit is in the task handoff;
the prior four fixes remain in parent ac3d6e041.
