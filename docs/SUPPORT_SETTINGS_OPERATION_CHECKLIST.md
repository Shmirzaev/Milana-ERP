# SUP-01 settings-section verification checklist

This operation's source extraction is not an acceptance claim. The stored-value
audit for persisted `default_language` values remains required before deployment;
the new DTO intentionally accepts only `en`, `ru`, and `uz`, and does not rewrite
unknown stored values.

## Automated verification still required

- Run `backend/app/tests/test_settings_patch_integrity.py` against the normal
  isolated test fixture, including rollback/retry and preference-reader cases.
- Run `backend/app/tests/test_support_settings_postgres.py` through the existing
  approved `customer_pg_sessions` fixture. It provisions and finalizes a
  disposable target database through the shared allowlisted harness. Never
  substitute a default application DSN or the legacy stabilization fixture.
- Run the existing material-reservation contract tests covering the value read
  by `app.models.inventory_service.require_material_reservation_before_cutting`.
- Review the generated OpenAPI request schemas for all three PATCH routes and
  confirm the enum values and extra-field rejection are deliberate.

## Human browser/readback checklist

- Before testing, inspect the approved isolated fixture's three setting rows and
  audit boundary; avoid non-fixture accounts or persisted production data.
- In Settings, open Company, Finance, and Preferences. Confirm the rendered
  values match GET and that Save on one section preserves omitted fields and the
  other two sections.
- Try a valid language (`en`, `ru`, or `uz`) and confirm the response, refreshed
  page, and readback agree. Confirm an unsupported language and unknown request
  field are refused without row or audit changes.
- Change `require_material_reservation_before_cutting` and verify the existing
  Cutting/reservation flow observes the saved boolean; do not claim a broader
  Cutting UI pass from settings-page evidence alone.
- Confirm one audit update is committed with each successful PATCH and none on
  rejected or rolled-back requests. Record the exact isolated fixture and
  source revision with any result.
- Treat company-logo upload as a separate file-lifecycle operation: this
  extraction does not validate upload cleanup, replacement, or its two-commit
  boundary.
