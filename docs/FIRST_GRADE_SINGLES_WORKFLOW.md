# Proposed First Grade singles workflow

Status: proposal only; not included in the deployment of items 1–7.

First Grade means a quality-approved product that cannot complete the required size assortment. It is not a defect grade. Label it “1st Grade — singles” so warehouse and sales staff do not confuse it with damaged or second-quality stock.

1. After Sewing acceptance, Packaging counts good pieces by order, production batch, model, variant, colour and exact size. Keep defects and rework in their existing separate flow.
2. Show two allocations: complete-assortment packs and First Grade singles. Suggest the maximum complete packs from the required size ratio; let the operator review remaining sizes before confirming. Do not reclassify all Sewing output automatically.
3. Confirmation must move quantities from unallocated good output into one allocation only. Use a locked transaction and idempotent request; total normal-packed + singles-packed + remaining good pieces cannot exceed accepted Sewing output, for each size and batch. The same pieces cannot be both pack stock and single stock.
4. Receive singles into a separate “1st Grade — singles” warehouse section/bin. Retain the existing Packaging/warehouse receipt evidence and source order/batch. Store exact size quantities. A small bag may hold multiple same-size pieces, but inventory and sales use pieces rather than complete-pack counts. Give the container its own QR label including grade, model, variant, size and count.
5. Add a separate Ready Products tab/filter and separate sales selection for these pieces. Sales can choose individual sizes and a per-piece price. Reserve, pick, ship and return exact quantities; incomplete assortments must never be offered as full packs.
6. Permit recombining matching singles into a full pack later through an audited repacking operation: consume the singles and create one validated full pack atomically. Require the configured size ratio, identical model/variant/colour, and no active reservation. Preserve all source batch links.
7. Returns retain their singles/full-pack classification. Reclassification needs a reason and warehouse permission. Reporting shows normal packs, singles by size, allocated/reserved pieces and age separately.

Example: a full pack requires one each of sizes 46, 48, 50, 52 and 54. Accepted quantities are 10, 10, 8, 10 and 10. Allocate 8 full packs (40 pieces) and 8 First Grade singles (two each of 46, 48, 52 and 54). Total remains 48; no inventory is created beyond the actual receipt.

Implementation should extend existing packaging allocation and finished-goods reservation rules with an explicit sale/assortment classification. It should not use the defect field or create stock directly from a Sewing button. Test concurrent allocations, partial receipt, duplicate confirmation, per-size sales/returns, permissions, factory isolation and repacking before deployment.


## Implementation — September 19 follow-up

The initial operational workflow now uses `Package.stock_kind=first_grade`. Each single is one piece, one exact size/color and one QR. Packaging selects leftover good output by size after full packs. Normal and single packages share the same locked production/batch quantity budget. Once singles exist, normal packages also enforce the accepted Sewing size balance. Repeated requests replay the same print run.

First Grade requires recorded accepted Sewing quantities by size, validated Packaging output, and a single verified production color. Historical mixed-batch bags without per-size evidence require reconciliation. Customer-owned and Usluga production cannot be diverted into free stock. Existing production/stock is not automatically reclassified.

Receive the singles' print run using any member QR. Finished Goods links to a separate **1st Grade — singles** warehouse tab. Model links open individual package information in a new browser tab. **Sell singles** accepts exact sizes and per-piece prices, reserving only received singles. Normal ready-pack selection and normal piece reservation exclude this stock. Existing scanned-package return preserves classification. Warehouse quantity correction cannot enlarge a single.

Recombining singles into full assortments and post-delivery commercial returns are separate future operations; this release does not expose an unaudited reclassification or repacking shortcut. The proposal above describes those possible extensions, not operations available in this release.

Migration `0132_first_grade_singles` defaults all existing packages to standard and adds shipment deletion timestamps. Mistaken manual shipments can be deleted only before dispatch, releasing scan links atomically and preserving audit history. Shipped/delivered or sales-linked shipments are protected. Deleted creation requests cannot recreate the shipment.

Rollback to an older application must first verify that no First Grade packages and no deleted manual shipments have been created: older applications do not understand their classification/tombstones. If either exists, use a forward repair or reconcile those records under a controlled maintenance procedure; never silently deploy the old stock-selection behavior. Schema downgrade is blocked while First Grade inventory exists.
