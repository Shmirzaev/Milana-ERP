# Milana ERP Figma import package

This package prepares an editable **functional navigation model** in Figma Design. It is not a native `.fig` file and has not yet been run in a signed-in Figma editor. The cloud file remains pending connection/sign-in.

## What the generator creates

- One new Figma page, without deleting or editing existing pages.
- 147 screen frames: every one of the 102 route templates and 45 concrete sidebar/query/factory variants.
- A full screen index, configured ERP sidebar, business handoff overview and shared-control reference.
- Native editable text and frames, using the ERP's Inter font and restrained cream/charcoal palette.
- The 948 discovered source control definitions expanded where screens share components or menus render configured links.
- Prototype connections to known routes; conditional choices and explanatory overlays for saves, scans, local dialogs, downloads and unresolved destinations.

The current structural dry run produces 465 direct control links and 1,779 explanatory overlays. It includes no real customer, employee, order, payroll or stock records. It makes no network requests and never connects to the ERP.

Screens are inventories of possible controls, including conditional states. They do not claim that every listed control is visible simultaneously for a particular role or department. A new-tab link is noted as such; prototype playback navigates to its corresponding frame. No database save, scan receipt or file download is simulated as a successful transaction.

## Create the actual Figma file

1. Sign in to Figma and open a new **Figma Design** file named **Milana ERP Business Workflow and Navigation**.
2. In the desktop editor, use **Plugins → Development → Import plugin from manifest** and select this folder's `manifest.json`.
3. If Figma requires a development-plugin ID, use **Create new plugin**, choose a Figma Design plugin, and copy the ID Figma assigns into this manifest. Do not substitute a guessed published-plugin ID.
4. Run **Milana ERP workflow and navigation**. The generator adds one page. A second run adds another page; it does not replace the first one.
5. Wait for the completion notification. Check the frame count, select **Read me**, then run the prototype. Open the index and test Sales Orders → New Order, Packages → View, Packaging Queue → Packing, Warehouse Stock → model packages, and the HR menu.
6. Inspect conditional annotations and the factory-specific variants. Verify actual font wrapping and prototype behavior; the local dry run cannot prove Figma rendering.
7. After successful review, save the file in your Figma workspace. Use Figma's **Save local copy** command if a downloadable `.fig` is needed.

A Figma connection alone does not prove file creation. Record the resulting file URL and import/playback checks only after they succeed.

## Files

| File | Purpose |
|---|---|
| `manifest.json` and `code.js` | Self-contained local development importer |
| `map-data.json` | Route, scope, control and destination data |
| `structural-check.json` | Local mock validation result, explicitly not live Figma verification |
| `svg/` | Sixteen vector sheets showing module navigation; may be imported into Figma independently |

SVG import provides editable vector artwork, but does not create prototype wires. Run the generator to create the connected native model. The Markdown/CSV registers remain the exact source reference.

## Validation and maintenance

Local checks cover route coverage, all sidebar destinations, existing connection targets, JavaScript syntax, selected read-only Figma API properties, conservative text-box geometry, SVG text bounds and PDF rendering. The generated assets were reviewed locally. Actual Figma import/playback remains pending.

API implementation follows Figma's official [plugin manifest](https://developers.figma.com/docs/plugins/manifest/), [reactions](https://developers.figma.com/docs/plugins/api/Reaction/), [node actions](https://developers.figma.com/docs/plugins/api/Action/) and [page flow starting points](https://developers.figma.com/docs/plugins/api/properties/PageNode-flowstartingpoints/) documentation. The importer uses asynchronous reaction updates and adds only a new page.

To regenerate after source changes, run the inventory tool, build-map tool, JavaScript syntax check and structural check described in the parent README. Review unresolved dynamic destinations before presenting the result as a verified runtime specification.
