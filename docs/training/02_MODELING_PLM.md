# Modeling / PLM Training Manual

Version: 1.0
Date: 2026-07-02
Department code: MOD
Default role: Modeling

## Purpose

Modeling / PLM maintains the product catalog. Planning, Sales, Inventory, Forecasting, Costing, Packaging, and Traceability all depend on clean model data.

## Main Pages

- Models
- Model Detail
- Brands
- Collections
- Traceability, when permission is granted

## Key Permissions

- `modeling.models`
- `modeling.bom`
- `modeling.brands`
- `modeling.collections`
- `modeling.approve`

## Daily Workflow

1. Create or update model records.
2. Add model code, name, category, type, description, and image.
3. Maintain model sizes and colors.
4. Maintain BOM rows with item, quantity per piece, unit, and waste percent.
5. Link models to brands and collections.
6. Upload pattern/image files where the model detail page supports them.
7. Submit or mark models ready for approval according to local process.
8. Fix BOM gaps reported by Planning or Finance.

## Model Creation Checklist

Every model should have:

1. Unique model code.
2. Clear product name.
3. Category/type.
4. Product image or reference.
5. Valid size range.
6. Valid colors.
7. BOM material rows.
8. Packaging/accessory rows if used for costing and reservation.
9. SAM minutes when used for payroll/capacity.
10. Approval status before branded production.

## BOM Rules

The BOM is used for material requirements, shortage checks, reservations, and cost estimates.

For each BOM row:

1. Select the correct inventory item.
2. Enter quantity per piece.
3. Use the same unit as inventory where possible.
4. Enter waste percent realistically.
5. Do not leave old or duplicate rows after style changes.

If Planning reports `no BOM` or material reservations show empty rows, check the model BOM first.

## Brands And Collections

Use Brands and Collections when producing or selling branded stock.

1. Create the brand.
2. Create the collection with season/year/status.
3. Link approved models to the collection.
4. Keep naming consistent so Sales and Forecasting can filter correctly.

## Approval Rules

Approved models can be used for branded-stock production. Do not approve a model until size, color, image, and BOM are ready.

If a model must be corrected after approval:

1. Review whether any Sales Orders or Production Orders already use it.
2. Coordinate with Planning and Management.
3. Update BOM carefully because future costing and reservation may change.
4. Use notes or audit logs to explain significant corrections.

## Data Quality Checklist

1. Model code has no typo.
2. Model name matches the physical product.
3. Image matches the model.
4. Sizes and colors match what Sales can sell.
5. BOM rows use active inventory items.
6. Waste percentages are realistic.
7. No duplicate BOM item unless intentionally required.
8. Brand/collection links are correct.

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Planning cannot calculate requirements | BOM missing or invalid | Add BOM rows and save. |
| Branded production cannot be created | Model not approved | Complete model and request approval. |
| Wrong material reserved | BOM item is wrong | Correct BOM and ask Planning to refresh reservations. |
| Sales cannot find model | Model code/name/status issue | Check model list, approval status, and spelling. |
