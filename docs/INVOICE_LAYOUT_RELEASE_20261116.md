# Invoice Excel layout production release — 16 November 2026

Production is release `20261116_090442`, green, exact application source
`4adaa45d0f3d8268c0940110cfc20053d3e98193` from
`codex/factory-workflows-20261113`. Both source manifests are
`a4e7bd89f2b4cc091c9d8b5db57d2f4d0694b382f038d056b945b11d680a9231`.
Backend activated09:09:49UTC, frontend09:09:50UTC. Running rollback is
`20261116_061924`, blue, manifest
`cd22477f24b62858d893ed4990d872ca8ca25dbed838b37314f06f0fbff3270b`.
Earlier recovery release053002 source/images remain retained.

## Scope and owner exception

Excel shipment item rows stay24pt with their original10pt font. Shrinking is
disabled; the description gains the exact width saved by narrowing columnsE–K.
Total sheet width, all values, numeric formats and package merges are preserved.
The size column remains content-aware. Extremely long unwrapped text may clip;
full cell values remain available. HTML output is unchanged.

The owner saw the native Excel preview and then explicitly requested:
"deploy without anything any test just deploy to production".
This instruction overrides the ordinary additional test/CI/security-scan,
performance, separate human review and observation gates for this deployment.
They were skipped, not reported as passed. The existing80passing invoice tests,
Ruff and independent review/native Excel visual evidence belong to the prior
development phase; no tests were rerun for deployment. No timed monitor ran.

## Immutable publication and activation

The candidate was reconciled against both active manifests and fresh
origin/clone_main3053788. Only one application runtime file differs from8fb52df54:
`backend/app/models/shipment_invoice_excel_service.py`; other changes are invoice
tests and documentation/baseline metadata. No dependencies, schema, startup,
permissions or business rules changed.

Local registry publication failed because the PC credential lacked write scope;
the failure is preserved. A separate clean build worktree
`C:\ERP\.codex-work\invoice-publish-20261116`, branch
`codex/invoice-publish-20261116`, helper commit
`ce3f8451deed78439c241110348ccf27d86f03ed`, published through build-only Actions
run[43836735590](https://github.com/Shmirzaev/Milana-ERP/actions/runs/43836735590).
It checked out exact runtime4adaa45d0 and ran no tests/application execution.
The helper workflow is not part of the deployed source or merged into main.

Images derive from the exact live pinned immutable bases, preserving dependencies,
user and default command. Backend replaces only the Git-byte invoice generator;
frontend changes only the source-revision image label, with identical filesystem.
This explicit owner exception used derived artifact builds instead of the normal
all-gates release workflow; no production VM built or installed dependencies.

- Backend: `ghcr.io/shmirzaev/milana-erp-backend@sha256:08e4541a65f5d34e83290c7b907e4cb0a97e3e682efa03cecd07164700497729`.
- Frontend: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:8033f22e3b00798306dc45bc284ece1adcbf57506d6c7f705879fceceed32b64`.
- Source archive SHA256: `f98536433cc2e5ef8563e6498bcf1de03800cb992d4902eac168a5edd90314db`,6649794bytes, generated directly from Git4adaa45d0.

Both deployment leases were held exclusively during source/image preparation,
inactive staging and activation. Installed controller hash remained
13a9e19d5b266c87d138cb2866a185fedf45a089b85534d26fb28667eb95c3f3.
The existing backend staging adapter pattern injected only RELEASE_ID into the
exact expected command; controller/routing code and shared environment were not
edited. Candidate default command, source hash, image revision, release identity
and disabled startup seeding were verified. Backend and frontend retained their
loopback slot ports. Old blue remained running throughout and remains rollback.

The first immediate stable-release check after router reload failed, triggering
automatic restoration to blue. It is preserved as FAILED. The already healthy
green slots were reused under fresh owned leases; bounded release-ID convergence
then confirmed backend before frontend cutover. Both current links were switched
only after activation. No candidate rebuild or source substitution occurred.

## Closing state and limitations

All four operational endpoints returned200: internal backend health, internal
frontend login, public health and public login. Backend health reported090442.
Both manifests/source links/green slot states agree; routers are active and HAProxy
configurations valid. New containers have zero restarts/OOM. Disk was79.54% backend
and78.28% frontend. Both owned leases were released.

Database remains0157; no explicit migration, backfill, backup or business-data
mutation was performed. The unchanged default startup schema command found the
same migration history. No operator pause was needed. Functional/browser/real-PG
QA, fresh scans, performance gates and timed observation were not performed under
the owner instruction. Earlier public-latency risks remain unresolved; no claim
of new-release performance acceptance is made.

Local evidence: `outputs/invoice-deploy-20261116/plan.json`, initial
`journal.json` and rollback receipt, then `resume/journal.json`, both final
postflight receipts and released-lease records. Development visual/test evidence:
`outputs/invoice-compact-rows-20261116/VERIFICATION-WIDE-DESCRIPTION.md`.
