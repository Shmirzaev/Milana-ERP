# CEO dashboard access and presentation — 20 November 2026

The owner requested superadmin access, then explicitly requested removal of
Waiting for handoff, working day/week/month controls, a clearer Material stock
section, and deployment "directly without any tests". This latest instruction
overrides further tests, browser QA, benchmarks, scans, QA-master review and timed
observation for this release. Skipped gates are not passes or human acceptance.
Immutable builds and operational source/health checks remain necessary.

Worktree `C:\ERP\.codex-work\ceo-superadmin-20261120`, branch
`codex/ceo-superadmin-20261120`, base `a362d5e273eb2c11a82b15bcf54c6673a48808dd`.
Both hosts freshly reconciled to green `20261119_122457_44523647780_1`, source
`65c861c8369d3f966bac69d1b9980aff796744c5`, manifest
`fd7428c089dba546e4b89db784614f9bf8ac44b80bc9a7b1491a7445ce7c8917`.
Schema `0159_ceo_balance_snapshots` is unchanged. This initial record describes
an uncommitted candidate; deployment is pending.

Named shared-auth/frontend owners: Dilmurod engineer / Mirshoir reviewer;
Shavkat business acceptance. Actual implementer root Codex agent; independent
source reviewer `review_ceo_rollout`. No teammate messages sent.

GET `/api/dashboard/ceo` uses a shared persisted-identity dependency and unchanged
dashboard services, DTO and queries. Auth/session `/me` adds server-derived
`can_view_ceo_dashboard: bool`, default false, using exactly the same CEO OR
canonical superadmin predicate. Primary-factory `admin.super` denial wins;
wildcard alone and forged token role cannot grant access. CEO operational-session
restrictions remain CEO-only. No writable user DTO or database field is added.
AuthGate, report entry, Sidebar and CeoShell consume the capability. Superadmins
see the link in MIL/BST/ECO and can return to ERP; CEOs remain report-only.

The report removes handoff summary/waiting presentation, retaining the API and
snapshot data. Buttons replace transparent radio overlays. Week/month expand
narrow one-day presets; custom date ranges retain their boundaries. Materials
use separate unit totals, searchable names/SKUs, a unit filter and 25-row increments;
warehouse detail remains collapsed. EN/RU/UZ supported. Configurable roles/factory
records and canonical report enums remain unchanged; no new fixed vocabulary,
migration or business-data write. Department handoffs and quantities are unchanged.

Before the latest no-tests instruction, access-only changes passed 32 Linux/SQLite
API/report regressions (cookie/bearer factory switch and same-token revocation),
21-context actual-component frontend access checks, existing access/Besttex/customer
checks, strict type checking, lint (8 existing warnings), and focused Ruff.
These do not validate subsequent presentation edits. One initial lifecycle fixture
failed because superadmin revocation also removed ECO scope; the corrected fixture
covers both retained and removed ECO access. No fresh PostgreSQL claim is made.

Local visual setup failed on legacy dependencies; the isolated locked-dependency
preview encountered full local disk and interrupted/corrupted npm installation.
No browser pass is claimed. Automatic approval review rejected removing the owned
`.next` cache as "blocked by policy"; the cache remains. Production was untouched.
Further tests/CI validation, browser QA, scan, performance and observation are
skipped by the owner's latest instruction. Independent review is source-only.

Later human checklist: superadmin menu/report in all factories and Back to ERP;
Week/Month expansion and custom date aggregation; absence of waiting section;
material search/unit/load-more; ordinary-role denial and CEO isolation. This is
retained for later acceptance, not a new permission request.

Next: build-only immutable artifacts; stage blue with current green as rollback,
then backend/frontend activation and all four operational health checks. Automatic
deployment stays disabled. Exact commit/images/manifests and actual cutover will
be recorded after deployment. This candidate is not yet live or source-merged.
