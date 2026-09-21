# Milana ERP page and button navigation guide

Read this with `BUSINESS_REQUIREMENTS.md`. This guide explains where users go and which actions stay on the current page. The generated `PAGE_AND_BUTTON_REFERENCE.md` and CSV/JSON registers preserve the full source inventory, including dynamic/conditional controls.

## How to read the map

- **Page:** a link or successful action opens another route.
- **New tab:** the browser opens a separate detail/image/document tab. The prototype uses an ordinary internal transition with a visible new-tab note; it does not reproduce browser tab management.
- **Dialog:** opens or closes an editor/confirmation on the current page.
- **Save or scan:** changes or resolves business data; it may stay on the page. A prototype annotation explains the action but never calls the ERP.
- **Filter or tab:** changes visible rows, selection or query context.
- **Print or download:** generates a document/image/output; not a business handoff.
- **Dynamic:** the destination/label depends on record data, factory, permissions or a helper. The map exposes the condition instead of inventing a particular customer, employee, order or package.

`[id]` is a route parameter, not a user-facing database field. The operator clicks the business number/name. Repeated table-row buttons share one source definition. The inventory counts definitions, not the number of buttons visible in a populated screen. Disabled/hidden controls depend on permission, status, selected row and factory.

## Application shell and login

| Origin | Control | Result | Important condition |
|---|---|---|---|
| Login | Sign in | Effective-permission/factory landing page | Not always Dashboard; Sewing and Packaging can have a factory home |
| Login | Open presentation page | `/presentation` | Public introduction |
| Reset password | Back to sign in | `/login` | Reset action remains separate from sign-in |
| Sidebar | Module label | Configured route in `sidebar-register.csv` | Permission, audience, super-admin and factory filters apply |
| Topbar | Search / Enter | `/search` with query | Result link then opens the selected entity |
| Topbar | Settings | `/settings` | Current session/access applies |
| Topbar | Notifications / tasks | Shared panel or drawer | Some records contain their own destination; no dedicated page assumed |
| Public presentation | Explore | `#flow` anchor | Scrolls within the presentation |
| Public presentation | Login | `/login` | Does not create an ERP account |

## Main page-to-page controls

Labels below are readable English descriptions of the control's purpose; exact translated labels and data expressions are preserved by control ID in the full register.

| Source page | Button or link | Opens | Evidence |
|---|---|---|---|
| Dashboard `/` | New Order | `/sales-orders/new` | Dashboard page/shared dashboard |
| Dashboard | View all sales orders | `/sales-orders` | Dashboard page |
| Dashboard | Order number | `/sales-orders/[id]` | Data-dependent order link |
| Dashboard | Process Tracking | `/processes` | Dashboard page |
| Dashboard | Sewing Floor shortcut | `/sewing/flows` | Dashboard page |
| Customers | Customer name | `/customers/[id]` | Customer list |
| Customer detail | Order reference | `/sales-orders/[id]` | Customer order/payment rows |
| Sales Orders | New Order | `/sales-orders/new` | Sales list |
| Sales Orders | Order number | `/sales-orders/[id]` | Desktop/mobile/detail selection |
| First Grade sale | Save sale successfully | `/sales-orders/[id]` | New sale response; no fixed ID |
| Planning | Forecasting | `/forecasting` | Planning page |
| Planning | Suggested stock-production row | `/planning/branded-stock` with model/color/size/qty query | Suggestion prefill, not automatic production |
| Planning | View created production | `/production-orders/[id]` | Available after successful creation |
| Production list / process tracking | Production reference / View | `/production-orders/[id]` | Selected production record |
| Department floor | Production number | `/production-orders/[id]` | Department rows |
| Cutting department | Open cutting work | `/work-orders/[id]/cutting` | Cutting-order component |
| Department work | Open | Operation-specific work-order route | Helper/operation controls destination; completed work can open production detail |
| Finished Goods department | Open / Create shipment | `/shipments` with relevant query | Creation can occur before navigation; permission and stock checks apply |
| Work Orders | Cutting | `/work-orders/[id]/cutting` | Matching operation |
| Work Orders | Printing | `/work-orders/[id]/printing` | Matching operation |
| Work Orders | Sewing | `/work-orders/[id]/sewing` | Matching operation |
| Work Orders | Packaging | `/work-orders/[id]/packaging` | Matching operation |
| Work Orders | Production reference | `/production-orders/[id]` | Parent order |
| Cutting work | Cutting Passports | `/cutting-passports?production_order_id=...` | Preserve production filter |
| Cutting Inventory | Scan | `/bundles/scan/cutting` | Preserve relevant department scope where supplied |
| Cutting Inventory | Bundle number | `/bundles/[id]` | Exact bundle |
| Bundles | Scan | `/bundles/scan` | Generic scan entry |
| Bundles | View | `/bundles/[id]` | Exact bundle |
| Packaging Queue | Packing | `/work-orders/[id]/packaging` | Eligible work row |
| Packages | Receive from Sewing | `/packaging/receive?packaging_department=...` | Factory-aware packaging department |
| Packages | View | `/packages/[id]` | Exact package |
| Packages | Passport | `/traceability?package=...` | Package number/barcode reference |
| Package detail | Traceability | `/traceability?package=...` | Current package |
| Packaging work | View package | `/packages/[id]` | Created/linked package |
| Packaging work | Download QR | QR image/file | Download, not a new ERP route |
| Finished Goods | First Grade singles | `/warehouse-stock?stock_kind=first_grade` | Separate classification |
| Finished Goods / Warehouse Stock | Stocktake | `/warehouse-stock/count` | Warehouse permission |
| Warehouse Stock | Sell singles | `/sales-orders/first-grade` | Received First Grade quantities only |
| Warehouse Stock | Model code or picture | `/warehouse-stock/models/[id]?stock_kind=...` in new tab | Keep standard/singles classification |
| Warehouse model detail | Package number | `/packages/[id]` | Barcode/contents detail |
| Warehouse model detail | Warehouse stock | `/warehouse-stock?stock_kind=...` | Keep classification |
| Warehouse Stock | Package number | `/packages/[id]` | Selected package |
| Warehouse Stock | Passport | `/traceability?package=...` | Selected package |
| Warehouse Map | History | `/packages/[id]` | Selected package placement |
| Warehouse count | Warehouse stock | `/warehouse-stock` | Returns to stock list |
| Warehouse count | Download count | CSV endpoint/file | Export; does not approve a correction |
| Shipment list/history | Shipment Traceability | `/traceability?shipment=...` | Selected shipment |
| Shipment list/history | Invoice print | Shipment print endpoint | Output document, not the Finance workspace |
| Traceability | Package | `/packages/[id]` | Resolved trace entity |
| Traceability | Production No | `/production-orders/[id]` | Resolved parent |
| Traceability | Shipment | `/shipments?shipment_id=...` | Selects shipment in shared page |
| Order History | Order reference | Sales or production detail | Determined by record type |
| Order History | Package number | `/packages/[id]` | Linked package |
| Models | Model or variant | `/models/[id]` | The `new` sentinel also uses this dynamic route |
| Model detail | Create / clone / variant save | Model detail, possibly `?mode=edit` | Destination depends on created model and normal/Usluga catalog |
| Model detail | Delete successfully | `/models` | Narrow deletion guards must pass |
| Process QR | Open model | `/models/[id]` | Selected model |
| Process QR | Open order | `/production-orders/[id]` | Selected operation's order |
| Usluga planning | Model catalog | `/usluga/models` | Separate customer-work catalog |
| Usluga planning | New Usluga model | `/usluga/models/new?mode=edit` | Dynamic model route |
| Usluga planning | View / order number | `/usluga/orders/[id]` | Selected customer work |
| Usluga planning | Edit | `/usluga/orders/[id]/edit` | Edit guard applies |
| Usluga order | Back to planning | `/usluga` | Preserves separate workflow |
| Usluga order | Open model | `/usluga/models/[id]` | Customer-work model |
| Usluga order | Stage tile | `/work-orders/[id]/[operation]` | Only implemented stage routes; operation determines destination |
| Usluga edit | Cancel / Save successfully | `/usluga/orders/[id]` | Cancel does not save |
| Image thumbnail | Preview | `/image-preview` with image/title data | Often new tab; original image identity retained |
| Image preview | Download | Source image file | No business mutation |

## Actions that normally do not open another page

| Area | Controls | Result to represent in the prototype |
|---|---|---|
| Lists | Search, filters, pagination, Load more, tabs | Updates the displayed result set or selected view |
| Customers and master data | Create, Edit, Save, Cancel | Local editor/dialog and mutation/error state as implemented |
| Planning | Choose model/material/factory, allocate, create | Updates form and creates linked production after validation |
| Purchasing | Approve, Reject, Convert, Receive | Changes the selected entity/status; may refresh the same workspace |
| Inventory | Edit batch, upload image, reserve, receive, archive | Batch-scoped editor or validated stock action |
| Cutting | Save passport, record output, create bundles, print | Saves stage evidence or prints labels |
| Scan pages | Scan/Enter, receive, resolve barcode | Shows resolved item, validation or successful receipt |
| Sewing | Assign line, record accepted/failed quantity, correct | Changes scoped assignment/output under guards |
| Daily Sewing Report | Add section, two-part garment, Save, Export | Local report editing and output; no automatic production advance |
| Packaging | Receive, record packed quantity, create packages/singles | Validated allocation and label result |
| Shipment | X/Return to inventory | Removes an eligible scanned package link before dispatch |
| Shipment | Delete manual shipment | Guarded pre-dispatch deletion with confirmation/history |
| Payroll | Scan employee/work, return/reverse, summary filters | Ledger result or correction, not page handoff |
| HR | Create/edit candidate or employee, attendance filter | Current workspace form/detail state |
| Admin | Edit permissions, save account, inspect audit | Guarded administrative action; not equivalent to clicking a menu |
| Shared shell | Notifications and Tasks | Panel/drawer with its own controls and possible entity links |

## Factory and query variants

| Scope | Sewing entry examples | Packaging entry | Cutting entry |
|---|---|---|---|
| Milana | `/sewing/flows?factory=MIL`, `/departments/MIL` | `/departments/PKG`, `packaging_department=PKG` | `/departments/CUT`, `cutting_department=CUT` |
| Besttex | `/sewing/flows?factory=BST`, `/departments/BST` | `/departments/BPK`, `packaging_department=BPK` | Follow the planned cutting route |
| Eco Cotton | `/sewing/flows?factory=ECO`, `/departments/ECO` | `/departments/ECP`, `packaging_department=ECP` | `/departments/ECT`, `cutting_department=ECT` |

Other significant query state: `group=materials|accessories`, `stock_kind=first_grade`, production/order/model selection, search text, dates and pagination. An explicit query is not permission. The server must still enforce the signed-in user's scope.

## Figma structure

The prepared import package creates one new Figma page containing:

1. A reading guide and source/release statement.
2. A business handoff diagram; its arrows represent workflow, not UI navigation.
3. A full index of every route template, plus concrete sidebar query/factory variants.
4. A wireframe frame for each screen/variant, with all attributable discovered controls and their evidence IDs.
5. Clickable connections for destinations that resolve to known screens.
6. Explanatory overlays for local, data-changing, external-file and unresolved actions. These are clearly marked annotations; they do not pretend to save ERP data.
7. A shared-control reference for controls outside resolved page imports, so coverage gaps remain inspectable.

These are functional navigation wireframes, not screenshots of current populated pages. Conditional destinations and source labels remain explicit; no employee/customer/order records are uploaded. The importer performs no network requests and does not call production. Cross-page browser new-tab behavior is described in the annotation, with a prototype transition only where the destination is known.

The cloud Figma file still requires sign-in/connection and a successful actual import. A generator ZIP, SVG or JSON must not be mislabeled as a native `.fig` file. After verified creation in Figma, the user can save a local `.fig` copy through Figma's own file export.
