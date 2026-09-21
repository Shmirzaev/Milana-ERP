# Milana ERP interactive prototype

[Open the native Figma design](https://www.figma.com/design/N28GP08RtekAjQuSsgpcPr/Milana-ERP-Business-Workflow-and-Navigation?node-id=2-161). Select **01 · Interactive ERP** and use **Present** to explore the screens.

The prototype contains 147 separate application screens: 102 route templates and 45 factory/query variants. They use editable Figma frames, text, reusable sidebar/topbar/button components, color variables, the ERP brand mark and Inter typography. Tables, forms, dashboards, department boards, scanner views and reports contain fictional sample records.

Use the sidebar for the main workspaces. **All workspaces** opens the module selector; **All … pages** opens every screen in that module. **More** exposes page actions. Rows and primary buttons open details, forms and dialogs. Starting flows: **Explore Milana ERP**, **Sign in to the demo**, and **Sales order to shipment**.

## Sample workflow

Sales & customers → New order → Create order → Send to planning → Production order → Cutting → Printing when required → Sewing → Packaging → Warehouse & shipments → Shipments.

The prototype uses prefilled example inputs and simulated save/scan confirmations. It does not connect to the ERP, persist business records, authenticate users, calculate actual payroll, send email, or export operational documents. Filters, pagination and language choices illustrate controls rather than implementing a data engine or complete localization. Real production behavior is specified in the business requirements and source register.

## Files

- `prototype-spec.json`: source-derived titles, fields, controls, routes, module membership, colors and fictional-data declaration.
- `prototype-state.json`: actual Figma node IDs and creation/link results gathered from the editor.
- `prototype-verification.json`: final native screen, dialog, reaction and destination checks.
- `../tools/build-prototype-spec.cjs`: derives the specification from repository source and English translations.
- `../tools/figma-prototype-runtime.js`: creates variables, components and native application screens.
- `../tools/figma-prototype-overlays.js`: creates menus and simulated action dialogs.
- `../tools/figma-prototype-wire.js`: connects controls and validates destination nodes.

These scripts were executed through the official Figma Community Scripter plugin because the Figma connector write tools were not exposed in this session. Scripts contain no credentials or live records and make no network calls.

## Supporting source map

The earlier `map-data.json`, `code.js`, `manifest.json`, `structural-check.json`, and `svg/` files document the source navigation inventory. That generator produces a functional control map; it is distinct from the application prototype. Its dry-run counts do not describe the native prototype. The older source-map page in Figma is a reference and is not the recommended presentation entry point.

All 147 screens are separate top-level frames on one Figma page so presentation links connect them. This fits the current file's three-page limit. No business data, application code, permissions or production release was changed.

## Native validation

The editor check found 147 populated screens, 1,476 dialogs and 6,460 assigned interactions, with zero missing destinations, blank screens or reaction errors. The 41 obsolete link records belong to earlier layout revisions and were safely skipped. The native node check also counts inherited component reactions, so that total is larger than the assigned interaction count.

Presentation checks covered dashboard → sales → new order → save confirmation → planning → production detail → cutting → printing → sewing → packaging → warehouse → shipments, plus the workspace selector → HR employee screen. Follow-up checks corrected detail-card stacking, source-expression labels, button padding and selected sample quantities. See the additional prototype check JSON files and polish scripts for those refinements.

The builder accepts SPEC from prototype-spec.json and a JOB describing init, render or overlays. The final refinement order is labels, data-polish, layout-fix, handoff-polish, finalize and sample-values, followed by the wire check. The polish script checks button-label fit. Use small batches in Scripter and collect each printed result before starting the next batch. Final playback evidence is in prototype-playback-check.json. All scripts only target the created prototype page.
