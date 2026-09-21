# Milana ERP workflow documentation

Created 21 September 2026 from production source release `20260920_030043` and Git snapshot `fb3c3d582b0bda9c94cd6a951c432a7a4383820f`.

## Start here

1. [Business requirements and workflow](BUSINESS_REQUIREMENTS.md): actors, objects, 18 workflow areas, 28 numbered requirements, state/exception rules and end-to-end review scenarios.
2. [Page and button navigation guide](NAVIGATION_GUIDE.md): which actions open a page, dialog, file or local result; critical factory/query variants.
3. [Complete page and button reference](PAGE_AND_BUTTON_REFERENCE.md): route-by-route source evidence for 102 page templates and discovered controls.
4. [Interactive Figma prototype](figma/README.md): 147 separate application screens with fictional records, shared navigation, dialogs and button connections in the native Figma design.

The printable manual is generated at `output/pdf/Milana-ERP-Business-Workflow-and-Navigation.pdf` in this worktree. It combines the business guide and readable navigation guide; the detailed 948-control appendix stays in searchable Markdown/CSV/JSON. The distribution ZIP bundles the manual, all registers, source tools and Figma assets.

## Registers

| File | Coverage |
|---|---|
| `page-register.csv` | 102 route templates and their source files |
| `button-register.csv` | 948 button, link, form and other click-handler definitions; labels, effects, destinations, disabled conditions, handler and source |
| `sidebar-register.csv` | 96 configured sidebar entries with permission/audience evidence |
| `source-inventory.json` | AST inventory including shared components, re-exported pages, configured link arrays, 34 navigation calls and 221 API calls |
| `coverage.json` | Generated map counts, target resolution and unresolved destination list |
| `figma/map-data.json` | 147 route/variant frames and attributable controls |

Use CSV as a searchable evidence register; it is not a list of 948 separate business requirements. Repeated rows share one definition, imported views share their controls, and dynamically rendered menus can expand one definition into multiple links. Thirty-five definitions have no resolved page owner and remain in the shared-control reference. Forty-nine screen/control instances have unresolved/file/anchor destinations; these are explicitly annotated rather than converted into invented page links.

## Verification boundary

Both production source trees and their manifests were verified read-only against `deploy/production-base.json`. Both current symlinks identify `20260920_030043`. The manifest hash is `6e0fe7e13abf717b544995c5e06a7628636ecd8919236cc89f08117660b391e2`. Current Git application code matches the deployed application commit; only documentation/base records differ. The legacy dirty checkout was preserved.

No business data, database schema, application code, permissions, production configuration or release was changed. Runtime slot files were not readable with the available non-elevated session; their last recorded state is documented as recorded, not freshly verified. No live mutation or comprehensive permission/security retest was performed.

The accompanying Figma prototype is a source-informed application mockup with fictional records, not a pixel-identical UI export or a running ERP. Conditional states, callbacks from outside a component and response-dependent transitions require runtime review. Source evidence is authoritative over a heuristic action category. Historical high-risk findings remain open unless current implementation and regression evidence establish closure.

## Reproduce

Run from this clean worktree with Node and Python available. The inventory and map builder take an explicit path to an installed TypeScript library if it is not resolvable as `typescript`.

```powershell
node docs/workflow/tools/inventory.cjs <path-to-typescript/lib/typescript.js>
node docs/workflow/tools/build-map.cjs <path-to-typescript/lib/typescript.js>
node --check docs/workflow/figma/code.js
node docs/workflow/tools/check-figma.cjs
python docs/workflow/tools/build-pdf.py
python docs/workflow/tools/check-svg.py
git diff --check
```

PDF/SVG verification tools require ReportLab, PyMuPDF and Pillow plus Windows Arial fonts. They write previews under ignored `tmp/`; the PDF is under ignored `output/`. Figma requires its own installed Inter fonts, loaded through its API. The importer needs no npm package or external network at runtime.

## Handoff

- Worktree: `C:/ERP/.codex-work/workflow-documentation-20260921`
- Branch: `codex/workflow-documentation-20260921`
- Scope: documentation, source inventory, local artifact generators and a native Figma prototype
- Deployment: none; production source remains verified release `20260920_030043`
- Figma: use the 01 · Interactive ERP page and Present to explore the prototype
- Commit/push status: see the final task handoff and branch log; no merge to main is authorized by this request
