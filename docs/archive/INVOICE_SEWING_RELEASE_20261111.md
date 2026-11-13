# Invoice/report polish and Sewing pagination — 11 November 2026

Final outcome: **deployed as blue20261111_115200**, retaining green20261111_052632
rollback. The initial rollback and owner's first Keep previous release decision
remain recorded below; the owner's later explicit immediate-deploy instruction
superseded that decision and accepted the disclosed specific latency exception.

## Owner-authorized redeployment

After the failed p95 and rollback were explained, the owner instructed immediate
deployment. The agent explicitly stated that this accepts the named Cutting-passport
p95 exception (+23.94%,150.85->186.97ms, limit15%), then promoted the same reviewed
commit46ddd5c78 and exact scanned images. No source/config change, new CI build,
replacement timing epoch or observer was introduced. Original failed reports remain
unchanged; this is an accepted exception, not a performance pass.

Both hosts were freshly reconciled against active source/Git/slots/controller/images;
disk remained below80%. Both owned locks were reacquired. A fresh0600 custom backup
verified1,400 objects:122,097,119 bytes, SHA256
`bdb8709afb2d31a4feb27c4266efb072080a0c003977cfb171e9586d6b8c5e83`;
restore list101,509 bytes, SHA256
`fa11ab3671206c43778f0eb423a97e928c020351913c9efbfcc4de3f4fcf8b15`.
Existing source/images were verified instead of recopied/rebuilt. The original
reviewed stage adapter was byte-verified and reused. Independent review of the
derived fresh-CAS phase bodies found no issue. Default commands, strict0156 schema,
disabled seeding and original routing/controller were retained.

Backend activated12:46:18 UTC /17:46:18 Tashkent, frontend12:46:24 UTC /17:46:24.
Both current symlinks now name115200; rollback is healthy green052632. Fresh staged
and public GETs verified complete ordered facts for the original ten protected
paths plus invoice/report. Sewing returned81 unique MIL batches; source invoice
remained identical and print10px/23.1pt was verified. This was functional QA only,
not a new timing epoch. Actual connected Edge on the public domain confirmed10px,
30.796875px rows, zero clipping, Today/This month controls and Today516 PJ1263 pieces.
The public invoice screenshot is retained privately under outputs/invoice-deploy.
Final four health endpoints, stable readiness, both source/image/slot identities,
router validity, two workers each, zero restarts/OOM, clean deployment-window logs,
database headroom and zero invalid indexes passed. No task-initiated business-data
writes or schema changes occurred. Locks released; no timed monitor ran.
Production baseline/context/Obsidian were updated after successful closing.

## Source and scope

Worktree: `C:\ERP\.codex-work\sewing-receive-load-more-20261111`.
Branch: `codex/sewing-receive-load-more-20261111`, pushed, not merged into
`clone_main` or `main`. Reviewed candidate: `46ddd5c7864f0a68bd9a3c884d835a2a5dbf9bfb`.
Source archive: 2,495 files, all bytes verified against canonical Git blobs.
Candidate release `20261111_115200`, source manifest
`db9df64cbcf57e4ab93ac83ef677d7d394b07652a1a4cf3fe1815abc92adac28`, archive SHA256
`1012591a8b22d37033746f9d6ff08798272a65d6cf45cdbb92159e5769e31730`.

| Candidate image | Immutable digest |
| --- | --- |
| Backend | `sha256:dd92999c50d53047168f2643610aafd25d6296976680567a5bcb41fa54d9aacf` |
| Frontend | `sha256:a2af00dc27bcdbca246c2a88fb9a058b2747b94d4dd047627bf71c90b082a6a8` |

The existing invoice and warehouse model/customer shipment report were inspected
before implementation. No replacement invoice/report screen was introduced.
Size text now uses one naturally sorted `size × quantity` convention; aggregate
lists show their total without inventing per-size quantities. Print and Excel
share the formatter. Table/totals/signatures use 10px (7.5pt Excel); the owner
explicitly retained the existing 23.1pt body-row minimum. Today/This month use
Tashkent calendar boundaries and existing report/export filters. Sewing uses
20-row append pagination with deterministic offset ordering and scoped receipt
refresh. No new business vocabulary, permission, persistence or migration change.

Domain engineer Mirshoir/reviewer Ismail remain recorded. Independent AI review
passed; no human domain/QA-master acceptance is inferred. Task packets:
[invoice/report](../INVOICE_REPORT_POLISH_20261111.md),
[Sewing](../SEWING_RECEIVE_LOAD_MORE_20261111.md).

## Verification

- Baseline formatting reproduction: 13 failures / one pass. Combined focused
  regressions: 176 passes; final invoice subset73; independent follow-up49.
- Full exact-source [CI43014831416](https://github.com/Shmirzaev/Milana-ERP/actions/runs/43014831416):
  6,756 backend passes / 1,589 reported skips / 36 subtests, PostgreSQL supplementary
  gates, frontend lint/strict types/browser contracts/default optimized build,
  image/dependency security and publication of the same scanned images.
- Exact-source [PG43018076254](https://github.com/Shmirzaev/Milana-ERP/actions/runs/43018076254):
  all649 mandatory cases, 17 supplements and 84 shared contracts passed.
- Disposable full-browser tests cover all three factories, final/partial pages,
  retry, search/reset, selection preservation and actual receipt/persisted refresh.
  Bounded 16-GET local stress passed, max4 concurrent, no source-document change.
- Exact staged images: existing invoice282 used 10px, row30.796875px, zero clipping;
  six EN/RU/UZ price-on/off XLSX exports retain 7.5pt/23.1pt and quantity516 with
  price-visible total4,282.80. Source-document JSON readback remained identical.
  PJ1263 Today516/month996; matching dates/search used by export, phone layout passed.
  MIL list reached20/40/60/80/81 unique batches. MIL-session BST/ECO403 remains
  the existing factory boundary. No production receipt or other write was submitted.
- Connected Edge verified the actual staged invoice, Today/November results,
  preserved model search and Sewing20->40. No ERP page errors in browser harness.
- Initial test-harness assumptions (factory session scope, loading row and SWR
  revalidation-response matching) were corrected before declaring UI success.
  These were harness corrections, not production source changes or timing retries.
  The temporary preview recorded five ConnectionAbortedError transport events;
  final browser assertions passed with zero ERP page errors and clean server logs.

## Release and performance result

Original verified production: green `20261111_052632`, commit
`519c9fa36f3d90905f935caf08fe781417cf7e24`, source manifest
`55d0edc9b7893df95987102cc6d9ccbe5b59a89f3c369eb5ea1f46a9868d4520`.
GitHub integration remained `3053788f2e17bd5585bccf8cd4547a62cc297516`;
stale main and legacy dirty checkout were preserved.

Both owned host locks were held across mutations. The installed controller
SHA256 `13a9e19d5b266c87d138cb2866a185fedf45a089b85534d26fb28667eb95c3f3`
was retained to avoid unrelated routing changes. Independently reviewed backend
adapter SHA256 `13c8ef3b5bde39d613f09b90890b009f9f19c424434d5ae4f5ec1037faa98c49`
pins the entire installed-version command and adds only the release environment
variable. Startup seed/schema bootstrap stays disabled; default commands retained.
An absent optional Docker image Entrypoint field was normalized to null in the
metadata checker after preparation, followed by explicit verified readback.
This did not change image/source/runtime configuration.

Protected retention archived/removed only three verified old source releases per
host:20261107_043754,20261109_035740,20261109_111519. Active, rollback and newest
five were protected; unsafe/unverified directories were skipped. No broad prune.
Final disk remains below80% but above70% alert, approximately78%; routine protected
retention/storage follow-up remains needed.

Fresh custom PostgreSQL backup:122,089,476 bytes, mode0600,1,400 restore objects.
Dump SHA256 `112c2dcf722b5565fa273a7ce0ebb7eef39161219993603f7cb889f8e1a74c8b`;
restore list101,509 bytes, SHA256
`b2d356c3900e1189401abf8c414d5c54382d3ba70fcedb82392aa4ad9f3407ba`.
Schema checks/upgrade were no-op at `0156_variant_price_workflow`.

One frozen epoch, signed GET only, complete ordered JSON facts and per-path hashes:
public baseline280 requests; staged paired550 requests passed every fact/latency/
payload limit. Post-cutover public280 requests preserved all facts, median and
payload limits but failed the following single p95 limit:

| Path | Baseline median | Candidate median | Baseline p95 | Candidate p95 | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Cutting passports |147.02ms|145.67ms|150.85ms|186.97ms|+23.94%, limit+15%: FAIL |

All other public endpoint p95 metrics passed. Latency cause is unproven; no causal
claim about this display/pagination patch or infrastructure is made. Failed evidence
and thresholds remain intact. No replacement timing epoch or blanket pass.

Backend activated12:29:45 UTC, frontend12:29:49. Fresh four health endpoints,
stable readiness, source/slot/image/router checks, two workers each, zero restart/OOM,
PostgreSQL headroom and zero invalid indexes passed. The public p95 failure required
rollback despite these passes. Backend reverted12:32:06 UTC, frontend12:32:11.
Both current symlinks then reverted; fresh rollback checks passed. Owner explicitly
declined the latency exception and selected Keep previous release.

## State after the initial rollback (superseded by redeployment above)

Both hosts again serve green `20261111_052632` with its original active container
identities, source and routing. Original standby blue `20261110_135430`, source
`cfe03885e03e4310e9b7c86ec9649ff350565d65`, manifest
`1abc90b9e4b87f3e16ef0e255fe1829d15e9b510d6f61f1b2c030baf33fa89a3`, was restored
from original inspected repository digests: backend `sha256:2be0b5f7b9f5db5cb91675aa9b230d6b501b22bfb9d76f7dff38915ae69da09d`,
frontend `sha256:b97c033079ca064fec2efaedbc13d3d1094c4ef0e02a839ea03f1998bdd7b8e9`.
The restoration helper differs only in its original release constant, SHA256
`95819a78f0a96ee37ef45a62d347e5ef55cf9c7128983b5bda989c2a7e93dec6`.
Only rollback metadata was compare-and-set after original standby health/default
command/worker/schema verification. Feature images/source remain retained artifacts.
At that rollback the Git production baseline stayed unchanged because active source
was unchanged. It was updated only after the later successful redeployment.

An existing green shipment-traceability failure at10:37:16 UTC (13 error markers)
predates candidate startup12:24:14.713 UTC. It is preserved as an unresolved prior
issue. Candidate full-start logs and both slots' deployment-window logs were clean;
complete startup/schema worker proof was checked separately. No historical all-log
clean claim. Production business data/schema was not changed by this task.

Owner explicitly waived timed observation; no observer or substitute monitor ran.
Final checks are immediate release/recovery gates, not a monitoring window.
Both deployment locks were released and owned local preview/fixture services stopped.
Detailed private HTTP facts, screenshots, logs and phase evidence remain ignored
under the task worktree's `outputs/invoice-deploy`; credentials are excluded.
