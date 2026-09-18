# Department test accounts

Created on 2026-09-18 in production. Each account copies its source user role, department, factory, extra permissions and access policy. All use the shared password supplied by the user, without a backslash; the password is intentionally omitted here.

| Source user | Test account | Factory |
|---|---|---|
| System Admin | admin-test@milanapremium.uz | MIL |
| Planning | planning-test@milanapremium.uz | MIL |
| Cutting | cutting-test@milanapremium.uz | MIL |
| Payroll | payroll-test@milanapremium.uz | MIL |
| AI Monitor | admin-ai-monitor-test@milanapremium.uz | MIL |
| Muxriddin | packaging-test@milanapremium.uz | MIL |
| Storage | ready-storage-test@milanapremium.uz | MIL |
| zynbin | fabric-storage-test@milanapremium.uz | MIL |
| Padval | milana-sewing-padval-test@milanapremium.uz | MIL |
| 1qavat | milana-sewing-1qavat-test@milanapremium.uz | MIL |
| 2qavat | milana-sewing-2qavat-test@milanapremium.uz | MIL |
| 3qavat | milana-sewing-3qavat-test@milanapremium.uz | MIL |
| Muborak | planning-muborak-test@milanapremium.uz | MIL |
| Bahodirjon | admin-bahodirjon-test@milanapremium.uz | MIL |
| Model | modeling-test@milanapremium.uz | MIL |
| agentic-os | admin-agentic-os-test@milanapremium.uz | MIL |
| Model2 | modeling-model2-test@milanapremium.uz | MIL |
| Abbosbek | planning-abbosbek-test@milanapremium.uz | MIL |
| Dildora | modeling-dildora-test@milanapremium.uz | MIL |
| Oyatullo | eco-cutting-test@milanapremium.uz | ECO |
| eco sewing | eco-sewing-test@milanapremium.uz | ECO |
| Besttex Tikuv | besttex-sewing-test@milanapremium.uz | BST |
| kroy | besttex-cutting-test@milanapremium.uz | BST |
| Jasurbek | sales-test@milanapremium.uz | MIL |
| Eco Cotton Admin | eco-admin-test@milanapremium.uz | ECO |

Existing users and the pre-existing Test User were preserved. The Abbosbek display-name prefix was retained for legacy purchasing access.

Verification: 25/25 HTTPS logins passed. Frontend session access fields and backend effective permissions matched the original account in every allowed factory. Unassigned factory switches returned 403. All verification sessions logged out. Source review covered frontend navigation rules, including identity-based purchasing access; no visual browser QA was performed.

Active release: `20260917_100146` (blue). Rollback: `20260917_091524` (green). No deployment or schema change.

Backup: `/opt/milana-erp/shared/backups/pre_department_test_users_20260918.dump`; 54,766,079 bytes; 1,202 restore objects; mode 0600; SHA-256 `2133474932a7e53bd075c3bd17ddd6b41ad363235f44b521edd37730edfdb17f`.

Operational scripts and per-account evidence: `outputs/test-users/` in the worktree. Created exactly 25 users (27-51) and 25 audit entries; login checks updated only test-account activity timestamps. Existing accounts and role definitions were unchanged.

Worktree: `C:/ERP/.codex-work/department-test-users-20260918`.
Branch: `codex/department-test-users-20260918`. Documentation pushed on this branch; not merged. No deployment occurred.
