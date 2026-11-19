# CEO dashboard

The ERP opens `/ceo-dashboard` for accounts assigned the reserved CEO role. The role has read-only access to dashboard reporting across the three factories. Assign it through the Super Admin user workflow.

| Section | Definition |
| --- | --- |
| Production output | Approved cutting pieces on the approval date, or record date for approvals with no timestamp. Passed printing and sewing pieces and recorded packaging pieces use their record dates. Each department is counted separately. |
| Factory comparison | Production attributed to the department that did the work. Unknown departments are kept separate, including when a factory is selected for the other panels. |
| Work waiting | Current transfer queues and identifiable remaining pieces, with age where the ERP records when the wait started. |
| Finished goods received | Physically received packs and pieces by receipt date. Imported legacy stock is shown separately. |
| Warehouse stock | Physical packs and remaining pieces by location, split into reserved and available. Shared stock is included in the company view. |
| Shipments | A pack counts once per dispatch that includes it. The pieces total uses quantities from the dispatch record, including partial packs. |
| Materials | Current quantity grouped by unit, with active batch and variety counts. Kilograms and other units are reported separately. Material transfers use the source debit and the destination on-hand balance. |

Dates use Asia/Tashkent and weeks start on Monday. Activity totals are over the selected range. Stock and waiting work are reported at the end of each period, using a live balance for today and a recorded closing sample for past dates. Past balances without a recorded sample display as unavailable.

After the dashboard migrations and review pass, configure one invocation of `python -m scripts.capture_ceo_closing_balances` from the backend runtime at **23:59 Asia/Tashkent**. Run it in the approved deployment environment using the existing PostgreSQL configuration. The capture stores all four factory views together, with the actual capture time. A missed run leaves a gap. Capture does not backfill historical dates. Check the first recorded sample against the live warehouse and materials totals near the time it was taken.
