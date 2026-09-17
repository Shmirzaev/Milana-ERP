# Security remediation — 18 September 2026

Source review and synthetic local regression testing against base commit
`80f4831e8b9e514f1a3ee16558ad45a782e0e29a`. No production testing or deployment.
Each application defect was assigned to a separate agent/worktree; dependency
issues were handled in subsequent batches, one package family per assignment.

## Reproduced application defects

| Finding | Corrected behavior | Regression coverage |
|---|---|---|
| SEC01 legacy grant bypass | Validate known permission identifiers and factory wrappers before privilege checks; reject scoped grants in global roles. | `test_security_sec01_grants.py` |
| SEC10 privileged deletion | Super Admin accounts require a Super Admin actor even if the target has no wildcard. | `test_privileged_user_delete.py` |
| API06 mutable identity privilege | Name/email cannot grant pricing access; frontend uses resolved permissions. | `test_security_pricing_identity.py`, frontend pricing contract |
| SEC07 assignment deletion | Authorize the associated flow's selected factory before deletion. | `test_assignment_delete_scope.py` |
| WF01 mass assignment | Planning PATCH accepts only explicit editable fields; rejects status, creator and other internal fields. UI status is read-only. | `test_production_patch_security.py` |
| SEC05 sibling reset links | Lock the account, refresh the token, and revoke outstanding links in the password-change transaction. | `test_reset_token_revocation.py`, including real PostgreSQL concurrency |
| SEC04 stale file sessions | Model originals and thumbnails check active account and credential revocation; release the authentication connection before image work. | `test_static_file_auth.py` |
| SEC07 flow utilization | Apply the same selected-factory guard as flow detail before returning utilization. | `test_flow_utilization_scope.py` |
| SEC07 passport detail | Check the linked cutting order's factory; retain MIL ownership for unlinked legacy records. | `test_passport_read_scope.py` |
| SEC02 audit retention | Reject account deletion before detaching references when audit history exists; offer deactivation. | `test_audit_user_retention.py` |

Tests are part of the normal backend suite. CI provisions a disposable PostgreSQL
service so the concurrent reset regression runs instead of skipping. The local
`scripts/run_isolated_postgres_tests.py` launcher creates a separate loopback
cluster and never uses an existing database or application `.env`.

## Dependency remediation

Next.js and eslint-config-next are upgraded together to 16.3.5, which also updates
sharp to 0.35.4. Pillow is upgraded to 12.3.0. Vulnerable CSS, browser-data, YAML,
identifier and glob-expansion dependencies are pinned to compatible patched
releases in the npm manifest and lockfile. These are advisory remediations, not
claims that remote code execution was demonstrated in the ERP. Build-time
exposure and runtime reachability differ by package and deployment.

The regenerated lockfile resolves PostCSS 8.5.28, Browserslist 4.29.0,
baseline-browser-mapping 2.11.25, brace-expansion 1.1.18/5.0.12, js-yaml 4.3.2,
nanoid 3.3.19 and postcss-selector-parser 6.1.4. The final npm lockfile audit on
18 September returned zero known advisories. Pillow 12.3.0 returned no advisory
records from PyPI, and 67 image/upload/QR regressions passed with that version.
This is not an audit of every transitive Python or operating-system package.

## Rollout and limits

- Before deployment, independently verify the legitimate purchaser's immutable
  account identity and grant `price_calculation.purchasing` as documented in
  [pricing rollout](SECURITY_PRICING_ACCESS_ROLLOUT.md). No migration guesses an
  account from its editable name or email.
- Existing malformed/unknown legacy grants are not rewritten automatically.
  Correct them through reviewed administration before resubmitting affected
  access configurations. Valid custom roles remain database entities; JSON
  storage itself is not the authorization defect.
- Clients may no longer change lifecycle/provenance fields through generic
  production PATCH. Use existing authorized workflow operations.
- Accounts with audit history return 409 on deletion and must be deactivated.
  Historical damaged hashes are not repaired or silently rehashed.
- Same-factory read policies are preserved. This is not a redesign of every
  department's read permissions. Super Admin sessions still select one factory.
- Independent historical stock, billing, payroll and audit-append concurrency
  risks require their own reproductions and fixes. Infrastructure, container/OS
  vulnerabilities, live load and exhaustive penetration testing are outside
  this local source task. Passing checks cannot establish zero vulnerabilities.
- No migration, production business data change, merge or deployment occurred.
  Reconcile the live baseline and follow `DEPLOYMENT.md` before later deployment.
