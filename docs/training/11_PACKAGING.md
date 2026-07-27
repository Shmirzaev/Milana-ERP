# Packaging Training Manual

Version: 1.0
Date: 2026-07-02
Department code: PKG
Default role: Packaging

## Purpose

Packaging records packed goods, creates package labels, controls package contents, and prepares packages for Ready Product Storage.

## Main Pages

- Packaging Floor
- Packaging Work Order
- Packages
- Scan Package
- Process Tracking
- Traceability

## Key Permissions

- `packaging.records`
- `packaging.packages`
- `payroll.scan`
- `traceability.view`

## Daily Workflow

1. Open Packaging Floor.
2. Review work ready from Sewing.
3. Open the Packaging Work Order.
4. Select batch if required.
5. Record input, packed quantity, damaged quantity, packaging material, and notes.
6. Create packages.
7. Review package contents, capacity, weights, and copies.
8. Print package labels.
9. Attach labels to physical packages.
10. Hand packages to Ready Product Storage for scanning.

## Recording Packaging Output

Fields:

1. Production batch, if batched.
2. Input quantity.
3. Packed/output quantity.
4. Damaged quantity.
5. Packaging material used.
6. Notes.

Save the packaging record before creating package labels if this is the team's procedure.

## Creating Packages

The package creator supports:

1. Color.
2. Package capacity.
3. Default weight.
4. Package copies.
5. Size quantities inside each package.
6. Individual package weights.
7. Full-package-only option.
8. Merge across batches when enabled for batched orders.

Default package capacity is 60 pieces unless changed. Over-capacity or mixed-model exceptions require appropriate approval/override.

## Full And Partial Packages

The preview shows:

1. Full packages.
2. Not-full packages.
3. Package capacity.
4. Pending leftovers when full-package-only is enabled.

If full-package-only is enabled, partial packages are not created. Communicate leftovers to the supervisor.

## Batch Packaging

For batched orders:

1. Select the correct batch before saving packaging output.
2. Review batch progress.
3. Use merge-across-batches only when supervisor approves packaging one full package from multiple batch leftovers.
4. Confirm package allocations before printing labels.

## Label Rules

1. Print labels immediately after package creation.
2. Attach label to the correct package.
3. Reprint only from the existing package record if label is damaged.
4. Do not create duplicate packages to replace missing labels.

## Handing To Ready Product Storage

1. Package must have label.
2. Package status should be packed.
3. Physical package count should match ERP package count.
4. Ready Product Storage scans package into a cell/shelf.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Cannot create package | Package contents invalid, no packageable quantity, or capacity issue | Review preview and package items. |
| Package count too high | Copies or capacity set wrong | Correct before creating labels. |
| Ready Storage cannot receive | Package not packed or wrong status | Check package detail and scan history. |
| Damaged goods not reflected | Damaged quantity not recorded | Save packaging record with damaged quantity. |
