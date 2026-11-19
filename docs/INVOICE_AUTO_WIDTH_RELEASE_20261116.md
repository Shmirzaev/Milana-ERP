# Adaptive invoice description width release — 16 November 2026

Production is `20261116_092917`, blue, exact reviewed runtime commit
`db8d8d64953eb4f9dadc22bb8218942cd0999ac7` on `codex/factory-workflows-20261113`.
Both source manifests are `54acee32ab64f7696a2cef52ad47c23f4f0aa7e8ebd45dafb3f5a3c3e71f96c3`.
Backend activated09:29:45UTC, frontend09:29:46UTC. Running rollback is
`20261116_090442`, green, manifest `a4e7bd89f2b4cc091c9d8b5db57d2f4d0694b382f038d056b945b11d680a9231`.

## Scope and explicit owner instruction

Only Excel description sizing changes: measured longest description/header line
plus padding, independent of unrelated size text/page whitespace.10pt font,
24pt item rows, no shrinking, compact trailing columns, values/formats/merges,
HTML and business behavior are preserved. Width is bounded by Excel255units;
font measurement uses existing Pillow/installed fonts, with no new dependency.
The owner saw the preview and instructed "deploy without any test".
No additional test/CI suites, scans, benchmark, browser QA, separate human review
or timed observation were run. They are skipped, not marked passed. Existing81
passing invoice tests and native Excel/Linux visual evidence predate deployment.

## Immutable artifacts and source identity

Build-only Actions run[43839778882](https://github.com/Shmirzaev/Milana-ERP/actions/runs/43839778882)
used helper commit396106f11b6d4955319591096bfc591ff2e46309 in separate clean
`C:\ERP\.codex-work\invoice-publish-20261116`, branchcodex/invoice-publish-20261116.
It checked out exact runtimedb8d8d64953eb4f9dadc22bb8218942cd0999ac7 and published derived images
on the currently live pinned090442bases. Backend replaces only the exact Git
invoice generator. Frontend filesystem and both default commands/dependencies
remain unchanged; revision labels identify the reviewed runtime. No production
VM build/install occurred. The helper workflow is not deployed or merged to main.

- Backend: `ghcr.io/shmirzaev/milana-erp-backend@sha256:645ac85e2254f39ffe01a58dbd79f5a1c406ccf82165ee9d5b7ed4ae37f2baa9`.
- Frontend: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:4a3059b78404ee49b33b2887f1286c28dcbcd5bb37e97b092b609782de71cbfe`.
- Archive SHA256: `a56853b80cc949fff249b8949a6b8270fdf3e9cb327ab71bae29b1f3444ed100`, 6622098bytes.
- Runtime generator SHA256: `a29d12e0cda293f55dc7c1c1d5eb482859bacae547cadc1ffac637ded5ab0c17`.

Initial release092633staged but did not activate. Its identity guard found the
archive used Windows CRLF while the image contained Git LF bytes; normalized
content was equal. The original failed journal and sources remain unchanged.
Final092917archive was rebuilt directly from raw Git blobs using cat-file,
verifying each Git blob identity and generating a fresh manifest. Images were
reused by exact immutable digest because they already contained the correct Git
bytes; no rebuild, tag substitution or in-place source edit occurred. Published
image tags contain092633but source/release identity is the separately pinned
092917manifest and controller-provided RELEASE_ID. This is intentional, recorded
artifact reuse for the same exact reviewed application commit.

## Activation and closing

Fresh live/source/slot capture agreed with recorded090442baseline and origin was
fetched. Owned locks on both VMs serialized preparation/staging/cutover. Sources
and digests verified; active green remained untouched until blue was healthy.
Installed controller stayed hash13a9e19d5b266c87d138cb2866a185fedf45a089b85534d26fb28667eb95c3f3.
Existing backend staging adapter injected only RELEASE_ID into the exact expected
run command. Default commands, disabled seeding, loopback ports, source hash and
reported release were verified. Backend activated before frontend; bounded router
release convergence preceded source-link updates. Both owned leases released.

All four operational endpoints returned200: internal backend health, internal
frontend login, public health and public login. Both manifest/link/blue-slot
identities agree; routers active/HAProxy valid. Containers have zero restart/OOM.
Disk was79.52%backend/78.38%frontend.
Schema remains0157, no explicit migration/backfill/backup/business-data mutation
or operator pause. Unchanged startup uses the same migration history.
Prior public-latency risks remain unresolved; no fresh performance claim is made.

Evidence: `outputs/invoice-auto-deploy-20261116` preserves the original stopped
attempt. `outputs/invoice-auto-deploy-final-20261116` contains exact frozen plan,
source archive, phase receipts, live journal and released leases. Development:
`outputs/invoice-auto-width-20261116/VERIFICATION.md`. No main/clone_main merge.
