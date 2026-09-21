# Page and button reference

Baseline `fb3c3d582b0bda9c94cd6a951c432a7a4383820f`; production source release `20260920_030043`. This is a static source inventory, not a record of live clicks. Dynamic labels remain expressions when no literal label exists. One control definition may render many rows. Destination queries are significant. Classification is inferred from handlers; see source for conditional behavior.

102 route templates; 96 configured sidebar entries; 948 control definitions; 34 navigation calls. Shared controls may appear on several routes.

## Global navigation

| Label | Destination | Permission candidates |
|---|---|---|
| Process Tracking | /processes?factory=ECO | Additional role/factory rules |
| Fabric to Eco Cotton | /eco-fabric-transfers | ["inventory.eco_transfers"] |
| Fabric scan register | /fabric-scans | ["cutting.records", "cutting.bundles", "storage.receive", "storage.items", "planning.production", "management.view"] |
| Dashboard | / | Additional role/factory rules |
| Process Tracking | /processes | Additional role/factory rules |
| Traceability | /traceability | ["traceability.view", "*"] |
| nav.hrDashboard | /hr | ["hr.employees", "*"] |
| Price requests | /sales/price-requests | ["sales.orders"] |
| Sales Orders | /sales-orders | ["sales.orders"] |
| Order History | /order-history | ["sales.orders"] |
| Customers | /customers | ["sales.customers"] |
| Models | /models | ["modeling.models"] |
| Brands | /brands | ["modeling.brands"] |
| Collections | /collections | ["modeling.collections"] |
| Planning Dashboard | /planning | ["planning.view", "planning.production"] |
| Branded Stock Orders | /planning/branded-stock | ["planning.production"] |
| Forecasting | /forecasting | ["forecasting.view", "*"] |
| Production Orders | /production-orders | ["planning.production"] |
| Price requests | /purchasing/price-calculation | Additional role/factory rules |
| Purchase Requests | /purchasing | ["purchasing.view", "purchasing.request", "purchasing.approve", "purchasing.order", "*"] |
| Active Purchase Orders | /purchasing/receiving | ["purchasing.receive", "*"] |
| Accessory pricing | /inventory/accessory-pricing | Additional role/factory rules |
| Material Inventory | /inventory?group=materials | ["storage.items", "storage.receive"] |
| Cutting fabric usage | /inventory/cutting-fabric-usage | ["storage.items", "storage.receive", "cutting.records", "planning.production"] |
| Accessory Inventory | /inventory?group=accessories | ["storage.items", "storage.receive"] |
| Master Data | /inventory/master-data | ["storage.items", "storage.suppliers", "*"] |
| Receive Fabric | /inventory/receive?group=materials | ["storage.receive"] |
| Receive Accessories | /inventory/receive?group=accessories | ["storage.receive"] |
| Batches | /inventory/batches | ["storage.items"] |
| Price requests | /cutting/price-calculation | ["cutting.records", "cutting.bundles", "admin.super"] |
| Cutting Floor | /departments/CUT | ["cutting.records", "cutting.bundles", "planning.production"] |
| Cutting Passports | /cutting-passports?cutting_department=CUT | ["cutting.records", "cutting.bundles", "planning.production"] |
| Bundle Inventory | /cutting-inventory?cutting_department=CUT | ["cutting.records", "cutting.bundles", "planning.production"] |
| Bundles | /bundles?cutting_department=CUT | ["cutting.bundles", "cutting.records", "planning.production"] |
| Scan Bundle | /bundles/scan/cutting | ["cutting.bundles", "cutting.records"] |
| Printing Floor | /departments/PRT | ["printing.records", "printing.bundles", "planning.production"] |
| Scan Bundle | /bundles/scan/printing | ["printing.bundles", "printing.records"] |
| Sewing Flows | /sewing/flows?factory=MIL | ["sewing.workspace", "sewing.flows"] |
| Daily Sewing Report | /sewing/daily-report?factory=MIL | ["sewing.workspace", "sewing.daily_reports.view"] |
| Sewing Floor | /departments/SEW | ["sewing.workspace"] |
| Milana Sewing | /departments/MIL | ["sewing.records", "sewing.bundles", "planning.production"] |
| Scan Bundle | /bundles/scan/sewing?factory=MIL | ["sewing.bundles", "sewing.records"] |
| Besttex Sewing | /departments/BST | ["sewing.records", "sewing.bundles", "planning.production"] |
| Sewing Flows | /sewing/flows?factory=BST | ["sewing.workspace", "sewing.flows"] |
| Daily Sewing Report | /sewing/daily-report?factory=BST | ["sewing.workspace", "sewing.daily_reports.view"] |
| Scan Bundle | /bundles/scan/sewing?factory=BST | ["sewing.bundles", "sewing.records"] |
| Besttex Packaging | /departments/BPK | ["packaging.records", "packaging.packages", "planning.production"] |
| Packages | /packages?packaging_department=BPK | ["packaging.packages", "packaging.records"] |
| Packing Queue | /packaging/queue?packaging_department=BPK | ["packaging.records", "planning.production"] |
| Receive from Sewing | /packaging/receive?packaging_department=BPK | ["packaging.records", "planning.production"] |
| Packaging reports | /packaging/reports?packaging_department=BPK | ["packaging.records", "packaging.packages", "planning.production"] |
| Eco Cotton Cutting | /departments/ECT | ["cutting.records", "cutting.bundles", "planning.production"] |
| Cutting fabric usage | /inventory/cutting-fabric-usage | ["storage.items", "storage.receive", "cutting.records", "planning.production"] |
| Cutting Passports | /cutting-passports?cutting_department=ECT | ["cutting.records", "cutting.bundles", "planning.production"] |
| Bundle Inventory | /cutting-inventory?cutting_department=ECT | ["cutting.records", "cutting.bundles", "planning.production"] |
| Bundles | /bundles?cutting_department=ECT | ["cutting.bundles", "cutting.records", "planning.production"] |
| Scan Bundle | /bundles/scan/cutting?cutting_department=ECT | ["cutting.bundles", "cutting.records"] |
| Eco Cotton Sewing | /departments/ECO | ["sewing.records", "sewing.bundles", "planning.production"] |
| Sewing Flows | /sewing/flows?factory=ECO | ["sewing.workspace", "sewing.flows"] |
| Daily Sewing Report | /sewing/daily-report?factory=ECO | ["sewing.workspace", "sewing.daily_reports.view"] |
| Scan Bundle | /bundles/scan/sewing?factory=ECO | ["sewing.bundles", "sewing.records"] |
| Eco Cotton Packaging | /departments/ECP | ["packaging.records", "packaging.packages", "planning.production"] |
| Packages | /packages?packaging_department=ECP | ["packaging.packages", "packaging.records"] |
| Packing Queue | /packaging/queue?packaging_department=ECP | ["packaging.records", "planning.production"] |
| Receive from Sewing | /packaging/receive?packaging_department=ECP | ["packaging.records", "planning.production"] |
| Packaging reports | /packaging/reports?packaging_department=ECP | ["packaging.records", "packaging.packages", "planning.production"] |
| Usluga planning | /usluga | ["usluga.view", "usluga.manage", "usluga.handover", "*"] |
| Usluga models | /usluga/models | ["usluga.view", "usluga.manage", "*"] |
| Packaging Floor | /departments/PKG | ["packaging.records", "packaging.packages", "planning.production"] |
| Packages | /packages?packaging_department=PKG | ["packaging.packages", "packaging.records"] |
| Packing Queue | /packaging/queue?packaging_department=PKG | ["packaging.records", "planning.production"] |
| Receive from Sewing | /packaging/receive?packaging_department=PKG | ["packaging.records", "planning.production"] |
| Packaging reports | /packaging/reports?packaging_department=PKG | ["packaging.records", "packaging.packages", "planning.production"] |
| Payroll Summary | /payroll | ["payroll.view", "payroll.manage", "payroll.pay"] |
| Sewing production report | /payroll/reports/sewing-production | ["payroll.view", "payroll.manage", "payroll.pay", "*"] |
| Order QR status | /payroll/reports/order-qr-status | ["payroll.view", "payroll.manage", "payroll.pay", "*"] |
| Process QR | /process-qr | ["payroll.scan", "*"] |
| Payroll Scan | /payroll/scan | ["payroll.scan", "*"] |
| QR Control | /payroll/qr-control | ["payroll.view", "payroll.manage", "*"] |
| Turnstile attendance | /attendance | ["attendance.view", "attendance.manage", "*"] |
| Finished Goods | /departments/FGS | Additional role/factory rules |
| Warehouse Stock | /warehouse-stock | ["storage.packages", "storage.shipment"] |
| Inventory count | /warehouse-stock/count | ["storage.packages", "storage.shipment"] |
| Scan Package | /packages/scan | ["storage.packages"] |
| Warehouse Map | /warehouse-map | ["storage.packages", "storage.shipment"] |
| Shipments | /shipments | ["storage.shipment"] |
| Shipment history | /shipments/history | ["storage.shipment"] |
| Waste Dashboard | /waste | Additional role/factory rules |
| Price calculation | /finance/price-calculation | ["finance.view"] |
| Finance Dashboard | /finance | ["finance.view"] |
| Users | /admin/users | ["admin.users"] |
| Departments | /admin/departments | ["*"] |
| Audit Logs | /admin/audit-logs | ["admin.audit"] |
| Employees | /admin/employees | ["hr.employees"] |
| MCP Access | /admin/mcp | Additional role/factory rules |
| Data Console | /admin/data | Additional role/factory rules |

## P001 /admin/audit-logs

Source: [page](../../frontend/src/app/(app)/admin/audit-logs/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0001 | Clear | filter/select/expand | {resetFilters} | frontend/src/app/(app)/admin/audit-logs/page.tsx:159 |
| C0002 | Hide details / Show details | open/close dialog | {() => setOpenId(isOpen ? null : row.id)} | frontend/src/app/(app)/admin/audit-logs/page.tsx:243 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P002 /admin/data

Source: [page](../../frontend/src/app/(app)/admin/data/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0003 | Refresh | local state / inspect handler | {refreshAll} | frontend/src/app/(app)/admin/data/page.tsx:205 |
| C0004 | table.label table.name table.row_count | filter/select/expand | {() => setSelectedTable(table.name)} | frontend/src/app/(app)/admin/data/page.tsx:236 |
| C0005 | Form submission | filter/select/expand | {submitSearch} | frontend/src/app/(app)/admin/data/page.tsx:272 |
| C0006 | Search | submit form | Local form behavior | frontend/src/app/(app)/admin/data/page.tsx:279 |
| C0007 | Edit | local state / inspect handler | {() => openEdit(row)} | frontend/src/app/(app)/admin/data/page.tsx:312 |
| C0008 | Delete | local state / inspect handler | {() => setDeleting(row)} | frontend/src/app/(app)/admin/data/page.tsx:315 |
| C0009 | Previous | filter/select/expand | {() => setPage((current) => Math.max(1, current - 1))} | frontend/src/app/(app)/admin/data/page.tsx:339 |
| C0010 | Next | filter/select/expand | {() => setPage((current) => current + 1)} | frontend/src/app/(app)/admin/data/page.tsx:343 |
| C0011 | Form submission | save/change data | {saveEdit} | frontend/src/app/(app)/admin/data/page.tsx:352 |
| C0012 | NULL | local state / inspect handler | {() => setDraft((current) => ({ ...current, [column.name]: null }))} | frontend/src/app/(app)/admin/data/page.tsx:364 |
| C0013 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/admin/data/page.tsx:402 |
| C0014 | Save | submit form | Local form behavior | frontend/src/app/(app)/admin/data/page.tsx:403 |
| C0757 | cancelText ?? Cancel | local state / inspect handler | {onCancel} | frontend/src/components/ConfirmDialog.tsx:30 |
| C0758 | confirmText ?? Confirm | local state / inspect handler | {onConfirm} | frontend/src/components/ConfirmDialog.tsx:31 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P003 /admin/departments

Source: [page](../../frontend/src/app/(app)/admin/departments/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0015 | Form submission | save/change data | {submit} | frontend/src/app/(app)/admin/departments/page.tsx:82 |
| C0016 | Add | local state / inspect handler | Local form behavior | frontend/src/app/(app)/admin/departments/page.tsx:97 |
| C0017 | Save | save/change data | {() => saveEdit(d.id)} | frontend/src/app/(app)/admin/departments/page.tsx:136 |
| C0018 | Cancel | local state / inspect handler | {() => setEditingId(null)} | frontend/src/app/(app)/admin/departments/page.tsx:137 |
| C0019 | Edit | local state / inspect handler | {() => startEdit(d)} | frontend/src/app/(app)/admin/departments/page.tsx:141 |
| C0020 | Delete | local state / inspect handler | {() => removeDepartment(d)} | frontend/src/app/(app)/admin/departments/page.tsx:142 |
| C0757 | cancelText ?? Cancel | local state / inspect handler | {onCancel} | frontend/src/components/ConfirmDialog.tsx:30 |
| C0758 | confirmText ?? Confirm | local state / inspect handler | {onConfirm} | frontend/src/components/ConfirmDialog.tsx:31 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P004 /admin/employees

Source: [page](../../frontend/src/app/(app)/admin/employees/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0142 | Add employee | local state / inspect handler | {() => open()} | frontend/src/app/(app)/hr/employees/page.tsx:98 |
| C0143 | Open profile | local state / inspect handler | {() => open(employee)} | frontend/src/app/(app)/hr/employees/page.tsx:111 |
| C0144 | Form submission | save/change data | {save} | frontend/src/app/(app)/hr/employees/page.tsx:117 |
| C0145 | name | local state / inspect handler | {() => setSection(name)} | frontend/src/app/(app)/hr/employees/page.tsx:131 |
| C0146 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/hr/employees/page.tsx:135 |
| C0147 | "Saving…" / "Save employee profile" | local state / inspect handler | Local form behavior | frontend/src/app/(app)/hr/employees/page.tsx:135 |
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P005 /admin/mcp

Source: [page](../../frontend/src/app/(app)/admin/mcp/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0021 | Copied / Copy | local state / inspect handler | {onCopy} | frontend/src/app/(app)/admin/mcp/page.tsx:48 |
| C0022 | Refresh | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/admin/mcp/page.tsx:108 |

## P006 /admin/users

Source: [page](../../frontend/src/app/(app)/admin/users/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0023 | Form submission | save/change data | {create} | frontend/src/app/(app)/admin/users/page.tsx:248 |
| C0024 | Create | local state / inspect handler | Local form behavior | frontend/src/app/(app)/admin/users/page.tsx:273 |
| C0025 | restrictedAdminAccount ? Super Admin only : undefined | local state / inspect handler | {() => openEdit(u)} | frontend/src/app/(app)/admin/users/page.tsx:336 |
| C0026 | adminAccount && !canManageAdmins ? Super Admin only : undefined | local state / inspect handler | {() => deleteUser(u)} | frontend/src/app/(app)/admin/users/page.tsx:344 |
| C0027 | Form submission | save/change data | {saveEdit} | frontend/src/app/(app)/admin/users/page.tsx:361 |
| C0028 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/admin/users/page.tsx:411 |
| C0029 | Save changes | submit form | Local form behavior | frontend/src/app/(app)/admin/users/page.tsx:412 |
| C0757 | cancelText ?? Cancel | local state / inspect handler | {onCancel} | frontend/src/components/ConfirmDialog.tsx:30 |
| C0758 | confirmText ?? Confirm | local state / inspect handler | {onConfirm} | frontend/src/components/ConfirmDialog.tsx:31 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P007 /attendance

Source: [page](../../frontend/src/app/(app)/attendance/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0030 | Add attendance device | open/close dialog | {() => { setDeviceError(""); setDeviceOpen(true); }} | frontend/src/app/(app)/attendance/page.tsx:272 |
| C0031 | Loading... / Excel report | download/export | {() => void downloadDailyReport()} | frontend/src/app/(app)/attendance/page.tsx:276 |
| C0032 | Refresh | local state / inspect handler | {() => void mutate()} | frontend/src/app/(app)/attendance/page.tsx:280 |
| C0033 | Previous | filter/select/expand | {() => setPage((value) => Math.max(1, value - 1))} | frontend/src/app/(app)/attendance/page.tsx:389 |
| C0034 | Next | filter/select/expand | {() => setPage((value) => value + 1)} | frontend/src/app/(app)/attendance/page.tsx:391 |
| C0035 | Cancel | open/close dialog | {() => setDeviceOpen(false)} | frontend/src/app/(app)/attendance/page.tsx:413 |
| C0036 | Saving... / Save and download setup | download/export | {() => void addManagedDevice()} | frontend/src/app/(app)/attendance/page.tsx:414 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P008 /brands

Source: [page](../../frontend/src/app/(app)/brands/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0037 | Form submission | save/change data | {submit} | frontend/src/app/(app)/brands/page.tsx:57 |
| C0038 | Create | local state / inspect handler | Local form behavior | frontend/src/app/(app)/brands/page.tsx:60 |
| C0039 | Edit | local state / inspect handler | {() => openEdit(b)} | frontend/src/app/(app)/brands/page.tsx:77 |
| C0040 | Form submission | save/change data | {saveEdit} | frontend/src/app/(app)/brands/page.tsx:86 |
| C0041 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/brands/page.tsx:94 |
| C0042 | Save changes | submit form | Local form behavior | frontend/src/app/(app)/brands/page.tsx:95 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P009 /bundles/[id]

Source: [page](../../frontend/src/app/(app)/bundles/[id]/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0048 | Print label | local state / inspect handler | {() => api.openLabel(`/api/bundles/${b.id}/label`)} | frontend/src/app/(app)/bundles/[id]/page.tsx:22 |

## P010 /bundles

Source: [page](../../frontend/src/app/(app)/bundles/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0043 | Scan | open page/link | /bundles/scan | frontend/src/app/(app)/bundles/page.tsx:80 |
| C0044 | "[-]" / "[+]" Order No : g.orderNo \| Batch : g.batchLabel ` \| ${Tracking passport}: ${g.trackingPassportNo}` / "" " \| " Total : g.items.length Bundle \| Qty : g.totalQty | open/close dialog | {() => toggleGroup(g.key)} | frontend/src/app/(app)/bundles/page.tsx:105 |
| C0045 | Print all labels | local state / inspect handler | {() => printGroupLabels(g)} | frontend/src/app/(app)/bundles/page.tsx:116 |
| C0046 | View | open page/link | `/bundles/${b.id}` | frontend/src/app/(app)/bundles/page.tsx:141 |
| C0047 | Label | local state / inspect handler | {() => api.openLabel(`/api/bundles/${b.id}/label`)} | frontend/src/app/(app)/bundles/page.tsx:142 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P011 /bundles/scan/cutting

Source: [page](../../frontend/src/app/(app)/bundles/scan/cutting/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0742 | New scan | open/close dialog | {resetScan} | frontend/src/components/BundleScanPanel.tsx:427 |
| C0743 | Form submission | submit form | {(event) => { event.preventDefault(); void lookup(); }} | frontend/src/components/BundleScanPanel.tsx:434 |
| C0744 | {(event) => event.currentTarget.select()} | local state / inspect handler | {(event) => event.currentTarget.select()} | frontend/src/components/BundleScanPanel.tsx:446 |
| C0745 | <Loader2 className="animate-spin" /> / <Search /> Looking up bundle / Lookup | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:467 |
| C0746 | Select sewing line | open/close dialog | {() => setLinePickerOpen(true)} | frontend/src/components/BundleScanPanel.tsx:525 |
| C0747 | <Loader2 className="animate-spin" /> / <ArrowRight /> Updating... / action.label | save/change data | {() => void act(action.key)} | frontend/src/components/BundleScanPanel.tsx:586 |
| C0748 | Print label | local state / inspect handler | {() => api.openLabel(`/api/bundles/${bundle.id}/label`)} | frontend/src/components/BundleScanPanel.tsx:598 |
| C0749 | Clear | local state / inspect handler | {() => setRecentScans([])} | frontend/src/components/BundleScanPanel.tsx:624 |
| C0750 | Refresh | local state / inspect handler | {() => mutateManualOptions()} | frontend/src/components/BundleScanPanel.tsx:650 |
| C0751 | Form submission | filter/select/expand | {submitManualSearch} | frontend/src/components/BundleScanPanel.tsx:656 |
| C0752 | Search | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:666 |
| C0753 | Receiving... / Receive batch | local state / inspect handler | {() => manualReceive(option)} | frontend/src/components/BundleScanPanel.tsx:721 |
| C0754 | Form submission | open/close dialog | {(event) => { event.preventDefault(); void acceptSewingBatch(); }} | frontend/src/components/BundleScanPanel.tsx:752 |
| C0755 | Cancel | open/close dialog | {() => { setLinePickerOpen(false); setLinePickerError(""); focusScanInput(true); }} | frontend/src/components/BundleScanPanel.tsx:816 |
| C0756 | <Loader2 className="animate-spin" /> / <CheckCircle2 /> Updating... / Accept and assign batch | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:828 |
| C0784 | Material picture | open new tab | imagePreviewHref(imageUrl, alt) | frontend/src/components/FabricThumbnail.tsx:35 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P012 /bundles/scan

Source: [page](../../frontend/src/app/(app)/bundles/scan/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0742 | New scan | open/close dialog | {resetScan} | frontend/src/components/BundleScanPanel.tsx:427 |
| C0743 | Form submission | submit form | {(event) => { event.preventDefault(); void lookup(); }} | frontend/src/components/BundleScanPanel.tsx:434 |
| C0744 | {(event) => event.currentTarget.select()} | local state / inspect handler | {(event) => event.currentTarget.select()} | frontend/src/components/BundleScanPanel.tsx:446 |
| C0745 | <Loader2 className="animate-spin" /> / <Search /> Looking up bundle / Lookup | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:467 |
| C0746 | Select sewing line | open/close dialog | {() => setLinePickerOpen(true)} | frontend/src/components/BundleScanPanel.tsx:525 |
| C0747 | <Loader2 className="animate-spin" /> / <ArrowRight /> Updating... / action.label | save/change data | {() => void act(action.key)} | frontend/src/components/BundleScanPanel.tsx:586 |
| C0748 | Print label | local state / inspect handler | {() => api.openLabel(`/api/bundles/${bundle.id}/label`)} | frontend/src/components/BundleScanPanel.tsx:598 |
| C0749 | Clear | local state / inspect handler | {() => setRecentScans([])} | frontend/src/components/BundleScanPanel.tsx:624 |
| C0750 | Refresh | local state / inspect handler | {() => mutateManualOptions()} | frontend/src/components/BundleScanPanel.tsx:650 |
| C0751 | Form submission | filter/select/expand | {submitManualSearch} | frontend/src/components/BundleScanPanel.tsx:656 |
| C0752 | Search | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:666 |
| C0753 | Receiving... / Receive batch | local state / inspect handler | {() => manualReceive(option)} | frontend/src/components/BundleScanPanel.tsx:721 |
| C0754 | Form submission | open/close dialog | {(event) => { event.preventDefault(); void acceptSewingBatch(); }} | frontend/src/components/BundleScanPanel.tsx:752 |
| C0755 | Cancel | open/close dialog | {() => { setLinePickerOpen(false); setLinePickerError(""); focusScanInput(true); }} | frontend/src/components/BundleScanPanel.tsx:816 |
| C0756 | <Loader2 className="animate-spin" /> / <CheckCircle2 /> Updating... / Accept and assign batch | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:828 |
| C0784 | Material picture | open new tab | imagePreviewHref(imageUrl, alt) | frontend/src/components/FabricThumbnail.tsx:35 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P013 /bundles/scan/printing

Source: [page](../../frontend/src/app/(app)/bundles/scan/printing/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0742 | New scan | open/close dialog | {resetScan} | frontend/src/components/BundleScanPanel.tsx:427 |
| C0743 | Form submission | submit form | {(event) => { event.preventDefault(); void lookup(); }} | frontend/src/components/BundleScanPanel.tsx:434 |
| C0744 | {(event) => event.currentTarget.select()} | local state / inspect handler | {(event) => event.currentTarget.select()} | frontend/src/components/BundleScanPanel.tsx:446 |
| C0745 | <Loader2 className="animate-spin" /> / <Search /> Looking up bundle / Lookup | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:467 |
| C0746 | Select sewing line | open/close dialog | {() => setLinePickerOpen(true)} | frontend/src/components/BundleScanPanel.tsx:525 |
| C0747 | <Loader2 className="animate-spin" /> / <ArrowRight /> Updating... / action.label | save/change data | {() => void act(action.key)} | frontend/src/components/BundleScanPanel.tsx:586 |
| C0748 | Print label | local state / inspect handler | {() => api.openLabel(`/api/bundles/${bundle.id}/label`)} | frontend/src/components/BundleScanPanel.tsx:598 |
| C0749 | Clear | local state / inspect handler | {() => setRecentScans([])} | frontend/src/components/BundleScanPanel.tsx:624 |
| C0750 | Refresh | local state / inspect handler | {() => mutateManualOptions()} | frontend/src/components/BundleScanPanel.tsx:650 |
| C0751 | Form submission | filter/select/expand | {submitManualSearch} | frontend/src/components/BundleScanPanel.tsx:656 |
| C0752 | Search | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:666 |
| C0753 | Receiving... / Receive batch | local state / inspect handler | {() => manualReceive(option)} | frontend/src/components/BundleScanPanel.tsx:721 |
| C0754 | Form submission | open/close dialog | {(event) => { event.preventDefault(); void acceptSewingBatch(); }} | frontend/src/components/BundleScanPanel.tsx:752 |
| C0755 | Cancel | open/close dialog | {() => { setLinePickerOpen(false); setLinePickerError(""); focusScanInput(true); }} | frontend/src/components/BundleScanPanel.tsx:816 |
| C0756 | <Loader2 className="animate-spin" /> / <CheckCircle2 /> Updating... / Accept and assign batch | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:828 |
| C0784 | Material picture | open new tab | imagePreviewHref(imageUrl, alt) | frontend/src/components/FabricThumbnail.tsx:35 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P014 /bundles/scan/sewing

Source: [page](../../frontend/src/app/(app)/bundles/scan/sewing/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0742 | New scan | open/close dialog | {resetScan} | frontend/src/components/BundleScanPanel.tsx:427 |
| C0743 | Form submission | submit form | {(event) => { event.preventDefault(); void lookup(); }} | frontend/src/components/BundleScanPanel.tsx:434 |
| C0744 | {(event) => event.currentTarget.select()} | local state / inspect handler | {(event) => event.currentTarget.select()} | frontend/src/components/BundleScanPanel.tsx:446 |
| C0745 | <Loader2 className="animate-spin" /> / <Search /> Looking up bundle / Lookup | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:467 |
| C0746 | Select sewing line | open/close dialog | {() => setLinePickerOpen(true)} | frontend/src/components/BundleScanPanel.tsx:525 |
| C0747 | <Loader2 className="animate-spin" /> / <ArrowRight /> Updating... / action.label | save/change data | {() => void act(action.key)} | frontend/src/components/BundleScanPanel.tsx:586 |
| C0748 | Print label | local state / inspect handler | {() => api.openLabel(`/api/bundles/${bundle.id}/label`)} | frontend/src/components/BundleScanPanel.tsx:598 |
| C0749 | Clear | local state / inspect handler | {() => setRecentScans([])} | frontend/src/components/BundleScanPanel.tsx:624 |
| C0750 | Refresh | local state / inspect handler | {() => mutateManualOptions()} | frontend/src/components/BundleScanPanel.tsx:650 |
| C0751 | Form submission | filter/select/expand | {submitManualSearch} | frontend/src/components/BundleScanPanel.tsx:656 |
| C0752 | Search | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:666 |
| C0753 | Receiving... / Receive batch | local state / inspect handler | {() => manualReceive(option)} | frontend/src/components/BundleScanPanel.tsx:721 |
| C0754 | Form submission | open/close dialog | {(event) => { event.preventDefault(); void acceptSewingBatch(); }} | frontend/src/components/BundleScanPanel.tsx:752 |
| C0755 | Cancel | open/close dialog | {() => { setLinePickerOpen(false); setLinePickerError(""); focusScanInput(true); }} | frontend/src/components/BundleScanPanel.tsx:816 |
| C0756 | <Loader2 className="animate-spin" /> / <CheckCircle2 /> Updating... / Accept and assign batch | submit form | Local form behavior | frontend/src/components/BundleScanPanel.tsx:828 |
| C0784 | Material picture | open new tab | imagePreviewHref(imageUrl, alt) | frontend/src/components/FabricThumbnail.tsx:35 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P015 /collections

Source: [page](../../frontend/src/app/(app)/collections/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0049 | Form submission | save/change data | {submit} | frontend/src/app/(app)/collections/page.tsx:73 |
| C0050 | Create | local state / inspect handler | Local form behavior | frontend/src/app/(app)/collections/page.tsx:81 |
| C0051 | Edit | local state / inspect handler | {() => openEdit(c)} | frontend/src/app/(app)/collections/page.tsx:99 |
| C0052 | Form submission | save/change data | {saveEdit} | frontend/src/app/(app)/collections/page.tsx:108 |
| C0053 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/collections/page.tsx:136 |
| C0054 | Save changes | submit form | Local form behavior | frontend/src/app/(app)/collections/page.tsx:137 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P016 /customers/[id]

Source: [page](../../frontend/src/app/(app)/customers/[id]/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0063 | Form submission | save/change data | {save} | frontend/src/app/(app)/customers/[id]/page.tsx:361 |
| C0064 | Save | local state / inspect handler | Local form behavior | frontend/src/app/(app)/customers/[id]/page.tsx:370 |
| C0065 | formatOrderReference(o.order_no) | open page/link | `/sales-orders/${o.id}` | frontend/src/app/(app)/customers/[id]/page.tsx:424 |
| C0066 | Add payment | open/close dialog | {() => openPayment(o)} | frontend/src/app/(app)/customers/[id]/page.tsx:452 |
| C0067 | Add payment | open/close dialog | {() => openPayment()} | frontend/src/app/(app)/customers/[id]/page.tsx:468 |
| C0068 | formatOrderReference(payment.order_no) | open page/link | `/sales-orders/${payment.order_id}` | frontend/src/app/(app)/customers/[id]/page.tsx:493 |
| C0069 | Add payment | open/close dialog | {() => openPayment()} | frontend/src/app/(app)/customers/[id]/page.tsx:508 |
| C0070 | Form submission | open/close dialog | {recordPayment} | frontend/src/app/(app)/customers/[id]/page.tsx:523 |
| C0071 | Cancel | open/close dialog | {() => setPaymentOpen(false)} | frontend/src/app/(app)/customers/[id]/page.tsx:588 |
| C0072 | Saving... / Save payment | local state / inspect handler | Local form behavior | frontend/src/app/(app)/customers/[id]/page.tsx:589 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P017 /customers

Source: [page](../../frontend/src/app/(app)/customers/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0055 | Form submission | save/change data | {submit} | frontend/src/app/(app)/customers/page.tsx:89 |
| C0056 | Add | local state / inspect handler | Local form behavior | frontend/src/app/(app)/customers/page.tsx:94 |
| C0057 | c.name | open page/link | `/customers/${c.id}` | frontend/src/app/(app)/customers/page.tsx:119 |
| C0058 | Edit | local state / inspect handler | {() => openEdit(c)} | frontend/src/app/(app)/customers/page.tsx:122 |
| C0059 | Delete | local state / inspect handler | {() => deleteCustomer(c)} | frontend/src/app/(app)/customers/page.tsx:123 |
| C0060 | Form submission | save/change data | {saveEdit} | frontend/src/app/(app)/customers/page.tsx:141 |
| C0061 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/customers/page.tsx:151 |
| C0062 | Save changes | submit form | Local form behavior | frontend/src/app/(app)/customers/page.tsx:152 |
| C0757 | cancelText ?? Cancel | local state / inspect handler | {onCancel} | frontend/src/components/ConfirmDialog.tsx:30 |
| C0758 | confirmText ?? Confirm | local state / inspect handler | {onConfirm} | frontend/src/components/ConfirmDialog.tsx:31 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P018 /cutting-inventory

Source: [page](../../frontend/src/app/(app)/cutting-inventory/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0075 | Refresh | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/cutting-inventory/page.tsx:187 |
| C0076 | Scan | open page/link | /bundles/scan/cutting | frontend/src/app/(app)/cutting-inventory/page.tsx:191 |
| C0077 | Form submission | filter/select/expand | {submitSearch} | frontend/src/app/(app)/cutting-inventory/page.tsx:216 |
| C0078 | Search | submit form | Local form behavior | frontend/src/app/(app)/cutting-inventory/page.tsx:226 |
| C0079 | Clear | filter/select/expand | {clearSearch} | frontend/src/app/(app)/cutting-inventory/page.tsx:228 |
| C0080 | <ChevronDown className="h-4 w-4 shrink-0" /> / <ChevronRight className="h-4 w-4 shrink-0" /> group.orderNo | open/close dialog | {() => toggleGroup(group.key)} | frontend/src/app/(app)/cutting-inventory/page.tsx:266 |
| C0081 | Print all labels | local state / inspect handler | {() => printGroupLabels(group)} | frontend/src/app/(app)/cutting-inventory/page.tsx:301 |
| C0082 | row.bundle_no | open page/link | `/bundles/${row.id}` | frontend/src/app/(app)/cutting-inventory/page.tsx:309 |
| C0083 | Label | local state / inspect handler | {() => api.openLabel(`/api/bundles/${row.id}/label`)} | frontend/src/app/(app)/cutting-inventory/page.tsx:333 |
| C0784 | Material picture | open new tab | imagePreviewHref(imageUrl, alt) | frontend/src/components/FabricThumbnail.tsx:35 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P019 /cutting-passports

Source: [page](../../frontend/src/app/(app)/cutting-passports/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0084 | New passport | open/close dialog | {openCreate} | frontend/src/app/(app)/cutting-passports/page.tsx:599 |
| C0085 | Add batch | open/close dialog | {() => openNewBatch(p)} | frontend/src/app/(app)/cutting-passports/page.tsx:731 |
| C0086 | {() => openEdit(passports.find((item) => item.id === p.id) \|\| p)} | open/close dialog | {() => openEdit(passports.find((item) => item.id === p.id) \|\| p)} | frontend/src/app/(app)/cutting-passports/page.tsx:732 |
| C0087 | {() => del(p)} | local state / inspect handler | {() => del(p)} | frontend/src/app/(app)/cutting-passports/page.tsx:735 |
| C0088 | Form submission | save/change data | {save} | frontend/src/app/(app)/cutting-passports/page.tsx:755 |
| C0089 | Load Excel example (passport 6770) | open/close dialog | {() => { orderRequest.current += 1; resetMaterialPicker(); setMaterialForms([]); setForm({ ...EXCEL_EXAMPLE }); }} | frontend/src/app/(app)/cutting-passports/page.tsx:762 |
| C0090 | Add material | open/close dialog | {openMaterialPicker} | frontend/src/app/(app)/cutting-passports/page.tsx:831 |
| C0091 | Add material | open/close dialog | {addMaterial} | frontend/src/app/(app)/cutting-passports/page.tsx:845 |
| C0092 | Cancel | open/close dialog | {() => setMaterialPickerOpen(false)} | frontend/src/app/(app)/cutting-passports/page.tsx:845 |
| C0093 | Remove | local state / inspect handler | {() => { setMaterialForms((rows) => rows.filter((row) => row.stock_batch_id !== material.stock_batch_id)); setAdditionalMaterials((rows) => rows.filter((row) => row.stock_batch_id !== material.stock_batch_id)); }} | frontend/src/app/(app)/cutting-passports/page.tsx:859 |
| C0094 | Cancel | local state / inspect handler | {() => setShowForm(false)} | frontend/src/app/(app)/cutting-passports/page.tsx:978 |
| C0095 | Save / Create | submit form | Local form behavior | frontend/src/app/(app)/cutting-passports/page.tsx:979 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P020 /cutting/price-calculation

Source: [page](../../frontend/src/app/(app)/cutting/price-calculation/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0073 | Edit | local state / inspect handler | {() => beginEdit(request)} | frontend/src/app/(app)/cutting/price-calculation/page.tsx:211 |
| C0074 | Saving… / Save | save/change data | {() => save(request)} | frontend/src/app/(app)/cutting/price-calculation/page.tsx:212 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |

## P021 /departments/[code]

Source: [page](../../frontend/src/app/(app)/departments/[code]/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0096 | Icon control at line 41 | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/app/(app)/departments/[code]/page.tsx:41 |
| C0097 | r.production_no \|\| "-" | open page/link | `/production-orders/${r.production_order_id}` | frontend/src/app/(app)/departments/[code]/page.tsx:308 |
| C0098 | Close / Open | filter/select/expand | {() => setExpandedPackageGroups((prev) => ({ ...prev, [g.key]: !prev[g.key] }))} | frontend/src/app/(app)/departments/[code]/page.tsx:337 |
| C0099 | Open | navigate after action | `/shipments${qs.toString() ? `?${qs.toString()}` : ""}` | frontend/src/app/(app)/departments/[code]/page.tsx:422 |
| C0100 | Loading... / Create shipment | navigate after action | `/shipments${qs.toString() ? `?${qs.toString()}` : ""}` | frontend/src/app/(app)/departments/[code]/page.tsx:429 |
| C0762 | Form submission | filter/select/expand | {event => { event.preventDefault(); setSearch(query); }} | frontend/src/components/CuttingOrderList.tsx:133 |
| C0763 | Search | submit form | Local form behavior | frontend/src/components/CuttingOrderList.tsx:135 |
| C0764 | Loading... / Move to in progress | local state / inspect handler | {() => onMoveToInProgress(Number(row.id))} | frontend/src/components/CuttingOrderList.tsx:213 |
| C0765 | Open | open page/link | `/work-orders/${row.id}/cutting` | frontend/src/components/CuttingOrderList.tsx:222 |
| C0778 | orderReference(row) | open page/link | `/production-orders/${row.production_order_id}` | frontend/src/components/DepartmentOrderList.tsx:159 |
| C0779 | Loading... / Move to in progress | local state / inspect handler | {() => onMoveToInProgress(row.id!)} | frontend/src/components/DepartmentOrderList.tsx:185 |
| C0780 | View order / Open | open page/link | kind === "completed" ? `/production-orders/${row.production_order_id}` : actionHref(row) | frontend/src/components/DepartmentOrderList.tsx:186 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |
| C0911 | stocktakeText[lang].title | open page/link | /warehouse-stock/count | frontend/src/components/StocktakeLink.tsx:12 |

## P022 /eco-fabric-transfers

Source: [page](../../frontend/src/app/(app)/eco-fabric-transfers/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0101 | Remove from dispatch | local state / inspect handler | {() => setDraft((rows) => rows.filter((r) => r.code !== row.code))} | frontend/src/app/(app)/eco-fabric-transfers/page.tsx:104 |
| C0102 | Form submission | save/change data | {(event) => { event.preventDefault(); void scan(code); }} | frontend/src/app/(app)/eco-fabric-transfers/page.tsx:115 |
| C0103 | Scan | submit form | Local form behavior | frontend/src/app/(app)/eco-fabric-transfers/page.tsx:119 |
| C0104 | Camera | local state / inspect handler | {() => setCamera(true)} | frontend/src/app/(app)/eco-fabric-transfers/page.tsx:120 |
| C0105 | t(sending ? "fabricScans.saving" : frozen ? "ecoTransfers.retrySend" : "ecoTransfers.markSent") | download/export | {() => void send()} | frontend/src/app/(app)/eco-fabric-transfers/page.tsx:125 |
| C0106 | Retry this return | save/change data | {async () => { if (!returnAttempt.current) return; setBusy(true); try { await completeReturn(returnAttempt.current); setFailure(""); } catch (err) { fail(err); } finally { setBusy(false); } }} | frontend/src/app/(app)/eco-fabric-transfers/page.tsx:129 |
| C0107 | lastDispatch.number · PDF | download/export | {() => void download(lastDispatch)} | frontend/src/app/(app)/eco-fabric-transfers/page.tsx:130 |
| C0108 | PDF | download/export | {() => void download(dispatch)} | frontend/src/app/(app)/eco-fabric-transfers/page.tsx:139 |
| C0109 | Previous | filter/select/expand | {() => setPage(page-1)} | frontend/src/app/(app)/eco-fabric-transfers/page.tsx:141 |
| C0110 | Next | filter/select/expand | {() => setPage(page+1)} | frontend/src/app/(app)/eco-fabric-transfers/page.tsx:141 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0783 | Close camera | local state / inspect handler | {onClose} | frontend/src/components/FabricRollCamera.tsx:55 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P023 /employees

Source: [page](../../frontend/src/app/(app)/employees/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|

No direct control definitions found; inspect route redirects and imported view composition.

## P024 /fabric-scans

Source: [page](../../frontend/src/app/(app)/fabric-scans/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0111 | Form submission | filter/select/expand | {submit} | frontend/src/app/(app)/fabric-scans/page.tsx:89 |
| C0112 | Camera | local state / inspect handler | {() => { clearTimeout(scanTimer.current); setCode(""); setCamera(true); }} | frontend/src/app/(app)/fabric-scans/page.tsx:100 |
| C0113 | Retry | filter/select/expand | {() => void save(row.code, row.direction)} | frontend/src/app/(app)/fabric-scans/page.tsx:110 |
| C0114 | Refresh | local state / inspect handler | {() => void mutate()} | frontend/src/app/(app)/fabric-scans/page.tsx:119 |
| C0115 | Export CSV | download/export | {() => data && downloadFabricReport(data, t)} | frontend/src/app/(app)/fabric-scans/page.tsx:120 |
| C0783 | Close camera | local state / inspect handler | {onClose} | frontend/src/components/FabricRollCamera.tsx:55 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P025 /finance

Source: [page](../../frontend/src/app/(app)/finance/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0116 | Record Payment | local state / inspect handler | {() => openPayment(inv)} | frontend/src/app/(app)/finance/page.tsx:147 |
| C0117 | Form submission | save/change data | {recordPayment} | frontend/src/app/(app)/finance/page.tsx:158 |
| C0118 | Cancel | local state / inspect handler | {() => setPaying(null)} | frontend/src/app/(app)/finance/page.tsx:174 |
| C0119 | Save | local state / inspect handler | Local form behavior | frontend/src/app/(app)/finance/page.tsx:175 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P026 /finance/price-calculation

Source: [page](../../frontend/src/app/(app)/finance/price-calculation/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0120 | Edit | local state / inspect handler | {() => beginFinanceEdit(request)} | frontend/src/app/(app)/finance/price-calculation/page.tsx:178 |
| C0121 | Saving… / Save | save/change data | {() => saveFinance(request, row)} | frontend/src/app/(app)/finance/price-calculation/page.tsx:179 |
| C0122 | detailsOpen ? Hide additional details : Show additional details | filter/select/expand | {() => toggleDetails(row.id)} | frontend/src/app/(app)/finance/price-calculation/page.tsx:197 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P027 /finished-goods

Source: [page](../../frontend/src/app/(app)/finished-goods/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0123 | firstGradeText[lang].title | open page/link | /warehouse-stock?stock_kind=first_grade | frontend/src/app/(app)/finished-goods/page.tsx:32 |
| C0124 | warehouseExitLabel[lang] | open page/link | /shipments?mode=warehouse_exit | frontend/src/app/(app)/finished-goods/page.tsx:33 |
| C0125 | row.shipment_no | open page/link | `/shipments?so_id=${soId}&shipment_id=${row.shipment_id}` | frontend/src/app/(app)/finished-goods/page.tsx:83 |
| C0126 | Not created | open page/link | `/shipments?so_id=${soId}` | frontend/src/app/(app)/finished-goods/page.tsx:85 |
| C0911 | stocktakeText[lang].title | open page/link | /warehouse-stock/count | frontend/src/components/StocktakeLink.tsx:12 |

## P028 /forecasting

Source: [page](../../frontend/src/app/(app)/forecasting/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0127 | Refresh | local state / inspect handler | {() => runAction(() => Promise.all([mutate(), mutateRecommendations()]))} | frontend/src/app/(app)/forecasting/page.tsx:97 |
| C0128 | Create plan | open page/link | `/planning?model_id=${row.model_id}&color=${encodeURIComponent(row.color \|\| "")}&size=${encodeURIComponent(row.size \|\| "")}&qty=${row.suggested_quantity}&brand_id=${row.brand_id \|\| ""}` | frontend/src/app/(app)/forecasting/page.tsx:166 |
| C0129 | Save recommendation | save/change data | {() => saveSuggestion(row)} | frontend/src/app/(app)/forecasting/page.tsx:169 |
| C0130 | Open inventory | open page/link | `/inventory?group=${["fabric", "semi_finished"].includes(row.category) ? "materials" : "accessories"}&q=${encodeURIComponent(row.item_sku \|\| "")}` | frontend/src/app/(app)/forecasting/page.tsx:209 |
| C0131 | Save recommendation | save/change data | {() => saveSuggestion(row)} | frontend/src/app/(app)/forecasting/page.tsx:212 |
| C0132 | Accept | save/change data | {() => setRecommendationStatus(row.id, "accepted")} | frontend/src/app/(app)/forecasting/page.tsx:255 |
| C0133 | Dismiss | save/change data | {() => setRecommendationStatus(row.id, "dismissed")} | frontend/src/app/(app)/forecasting/page.tsx:256 |

## P029 /hr/analytics

Source: [page](../../frontend/src/app/(app)/hr/analytics/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |

## P030 /hr/attendance

Source: [page](../../frontend/src/app/(app)/hr/attendance/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0134 | Refresh | local state / inspect handler | {() => void mutate()} | frontend/src/app/(app)/hr/attendance/page.tsx:10 |
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |

## P031 /hr/calendar

Source: [page](../../frontend/src/app/(app)/hr/calendar/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0135 | Add event | open/close dialog | {() => setOpen(true)} | frontend/src/app/(app)/hr/calendar/page.tsx:14 |
| C0136 | Form submission | save/change data | {create} | frontend/src/app/(app)/hr/calendar/page.tsx:14 |
| C0137 | Add event | local state / inspect handler | Local form behavior | frontend/src/app/(app)/hr/calendar/page.tsx:14 |
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P032 /hr/documents

Source: [page](../../frontend/src/app/(app)/hr/documents/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0138 | Upload document | open/close dialog | {() => setOpen(true)} | frontend/src/app/(app)/hr/documents/page.tsx:14 |
| C0139 | Download | open page/link | row.download_url | frontend/src/app/(app)/hr/documents/page.tsx:14 |
| C0140 | Form submission | open/close dialog | {upload} | frontend/src/app/(app)/hr/documents/page.tsx:14 |
| C0141 | "Uploading…" / "Upload securely" | local state / inspect handler | Local form behavior | frontend/src/app/(app)/hr/documents/page.tsx:14 |
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P033 /hr/employees

Source: [page](../../frontend/src/app/(app)/hr/employees/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0142 | Add employee | local state / inspect handler | {() => open()} | frontend/src/app/(app)/hr/employees/page.tsx:98 |
| C0143 | Open profile | local state / inspect handler | {() => open(employee)} | frontend/src/app/(app)/hr/employees/page.tsx:111 |
| C0144 | Form submission | save/change data | {save} | frontend/src/app/(app)/hr/employees/page.tsx:117 |
| C0145 | name | local state / inspect handler | {() => setSection(name)} | frontend/src/app/(app)/hr/employees/page.tsx:131 |
| C0146 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/hr/employees/page.tsx:135 |
| C0147 | "Saving…" / "Save employee profile" | local state / inspect handler | Local form behavior | frontend/src/app/(app)/hr/employees/page.tsx:135 |
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P034 /hr/organization

Source: [page](../../frontend/src/app/(app)/hr/organization/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0148 | Add organization unit | open/close dialog | {() => setOpen(true)} | frontend/src/app/(app)/hr/organization/page.tsx:19 |
| C0149 | Form submission | save/change data | {create} | frontend/src/app/(app)/hr/organization/page.tsx:20 |
| C0150 | Cancel | open/close dialog | {() => setOpen(false)} | frontend/src/app/(app)/hr/organization/page.tsx:20 |
| C0151 | Add unit | local state / inspect handler | Local form behavior | frontend/src/app/(app)/hr/organization/page.tsx:20 |
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P035 /hr

Source: [page](../../frontend/src/app/(app)/hr/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |

## P036 /hr/positions

Source: [page](../../frontend/src/app/(app)/hr/positions/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0152 | Add position | local state / inspect handler | {() => open()} | frontend/src/app/(app)/hr/positions/page.tsx:20 |
| C0153 | Edit | local state / inspect handler | {() => open(row)} | frontend/src/app/(app)/hr/positions/page.tsx:22 |
| C0154 | Form submission | save/change data | {save} | frontend/src/app/(app)/hr/positions/page.tsx:23 |
| C0155 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/hr/positions/page.tsx:23 |
| C0156 | Save | local state / inspect handler | Local form behavior | frontend/src/app/(app)/hr/positions/page.tsx:23 |
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P037 /hr/recruitment

Source: [page](../../frontend/src/app/(app)/hr/recruitment/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0157 | hrT("Add candidate") | local state / inspect handler | {() => openCandidate()} | frontend/src/app/(app)/hr/recruitment/page.tsx:217 |
| C0158 | hrT("View / edit") | local state / inspect handler | {() => openCandidate(candidate)} | frontend/src/app/(app)/hr/recruitment/page.tsx:261 |
| C0159 | Form submission | save/change data | {saveCandidate} | frontend/src/app/(app)/hr/recruitment/page.tsx:277 |
| C0160 | hrT("Cancel") | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/hr/recruitment/page.tsx:328 |
| C0161 | `${hrT("Saving")}…` / hrT("Save candidate") | local state / inspect handler | Local form behavior | frontend/src/app/(app)/hr/recruitment/page.tsx:329 |
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P038 /hr/settings

Source: [page](../../frontend/src/app/(app)/hr/settings/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0162 | Form submission | save/change data | {save} | frontend/src/app/(app)/hr/settings/page.tsx:8 |
| C0163 | Save HR settings | local state / inspect handler | Local form behavior | frontend/src/app/(app)/hr/settings/page.tsx:8 |
| C0789 | label | open page/link | href | frontend/src/components/hr/HrUi.tsx:166 |

## P039 /inventory/accessory-pricing

Source: [page](../../frontend/src/app/(app)/inventory/accessory-pricing/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0164 | Remove accessory | local state / inspect handler | {() => removeRow(request, index)} | frontend/src/app/(app)/inventory/accessory-pricing/page.tsx:149 |
| C0165 | Edit | local state / inspect handler | {() => beginEdit(request)} | frontend/src/app/(app)/inventory/accessory-pricing/page.tsx:156 |
| C0166 | Saving… / Save | save/change data | {() => save(request)} | frontend/src/app/(app)/inventory/accessory-pricing/page.tsx:157 |
| C0167 | Add accessory | local state / inspect handler | {() => addRow(request)} | frontend/src/app/(app)/inventory/accessory-pricing/page.tsx:161 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |

## P040 /inventory/archive

Source: [page](../../frontend/src/app/(app)/inventory/archive/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0168 | Return to inventory | local state / inspect handler | {() => openRestore(batch)} | frontend/src/app/(app)/inventory/archive/page.tsx:137 |
| C0169 | Back to fabric inventory | open page/link | /inventory?group=materials | frontend/src/app/(app)/inventory/archive/page.tsx:155 |
| C0170 | Form submission | filter/select/expand | {submitSearch} | frontend/src/app/(app)/inventory/archive/page.tsx:164 |
| C0171 | Clear | filter/select/expand | {clearSearch} | frontend/src/app/(app)/inventory/archive/page.tsx:174 |
| C0172 | Search | submit form | Local form behavior | frontend/src/app/(app)/inventory/archive/page.tsx:179 |
| C0173 | Form submission | save/change data | {restoreBatch} | frontend/src/app/(app)/inventory/archive/page.tsx:220 |
| C0174 | Cancel | local state / inspect handler | {() => setRestoring(null)} | frontend/src/app/(app)/inventory/archive/page.tsx:233 |
| C0175 | Loading... / Return to inventory | submit form | Local form behavior | frontend/src/app/(app)/inventory/archive/page.tsx:234 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P041 /inventory/batches

Source: [page](../../frontend/src/app/(app)/inventory/batches/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0176 | reservation.reservation_no - Number(reservation.remaining_quantity \|\| 0).toFixed(2) reservation.unit | open page/link | `/production-orders/${reservation.production_order_id}` | frontend/src/app/(app)/inventory/batches/page.tsx:87 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P042 /inventory/cutting-fabric-usage

Source: [page](../../frontend/src/app/(app)/inventory/cutting-fabric-usage/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0177 | Form submission | filter/select/expand | {apply} | frontend/src/app/(app)/inventory/cutting-fabric-usage/page.tsx:79 |
| C0178 | Apply | submit form | Local form behavior | frontend/src/app/(app)/inventory/cutting-fabric-usage/page.tsx:95 |
| C0179 | Clear filters | filter/select/expand | {clear} | frontend/src/app/(app)/inventory/cutting-fabric-usage/page.tsx:98 |
| C0180 | Refresh | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/inventory/cutting-fabric-usage/page.tsx:99 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P043 /inventory/master-data

Source: [page](../../frontend/src/app/(app)/inventory/master-data/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0181 | Materials / key === "accessories" ? Accessories : Suppliers | filter/select/expand | {() => switchTab(key)} | frontend/src/app/(app)/inventory/master-data/page.tsx:350 |
| C0182 | Clear | local state / inspect handler | {() => setQuery("")} | frontend/src/app/(app)/inventory/master-data/page.tsx:383 |
| C0183 | Edit | local state / inspect handler | {() => setSupplierForm(supplierToForm(supplier))} | frontend/src/app/(app)/inventory/master-data/page.tsx:413 |
| C0184 | Delete | local state / inspect handler | {() => deleteSupplier(supplier)} | frontend/src/app/(app)/inventory/master-data/page.tsx:416 |
| C0185 | Edit | local state / inspect handler | {() => setItemForm(itemToForm(item))} | frontend/src/app/(app)/inventory/master-data/page.tsx:450 |
| C0186 | Delete | local state / inspect handler | {() => deleteItem(item)} | frontend/src/app/(app)/inventory/master-data/page.tsx:453 |
| C0187 | Form submission | save/change data | {submitSupplier} | frontend/src/app/(app)/inventory/master-data/page.tsx:472 |
| C0188 | Clear | local state / inspect handler | {() => setSupplierForm(EMPTY_SUPPLIER)} | frontend/src/app/(app)/inventory/master-data/page.tsx:476 |
| C0189 | Saving... / supplierForm.id ? Save : Create | local state / inspect handler | Local form behavior | frontend/src/app/(app)/inventory/master-data/page.tsx:501 |
| C0190 | Form submission | save/change data | {submitItem} | frontend/src/app/(app)/inventory/master-data/page.tsx:507 |
| C0191 | Clear | local state / inspect handler | {resetItemForm} | frontend/src/app/(app)/inventory/master-data/page.tsx:511 |
| C0192 | Add row | local state / inspect handler | {addCompositionRow} | frontend/src/app/(app)/inventory/master-data/page.tsx:529 |
| C0193 | Remove | local state / inspect handler | {() => removeCompositionRow(index)} | frontend/src/app/(app)/inventory/master-data/page.tsx:553 |
| C0194 | Saving... / itemForm.id ? Save : Create | local state / inspect handler | Local form behavior | frontend/src/app/(app)/inventory/master-data/page.tsx:567 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P044 /inventory

Source: [page](../../frontend/src/app/(app)/inventory/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0195 | <img src={storageThumbnailUrl(url, 320)} alt={alt} className="h-full w-full object-cover" /> / Preview | open new tab | isImage ? imagePreviewHref(url, alt) : url | frontend/src/app/(app)/inventory/page.tsx:698 |
| C0196 | Fabric archive | open page/link | /inventory/archive | frontend/src/app/(app)/inventory/page.tsx:1190 |
| C0197 | Loading... / Excel report | download/export | {() => void downloadMaterialReport("xlsx")} | frontend/src/app/(app)/inventory/page.tsx:1194 |
| C0198 | Loading... / PDF report | download/export | {() => void downloadMaterialReport("pdf")} | frontend/src/app/(app)/inventory/page.tsx:1203 |
| C0199 | Form submission | navigate after action | inventoryHref(group, searchDraft) | frontend/src/app/(app)/inventory/page.tsx:1224 |
| C0200 | Clear | navigate after action | inventoryHref(group, "") | frontend/src/app/(app)/inventory/page.tsx:1234 |
| C0201 | Search | navigate after action | inventoryHref(group, searchDraft) | frontend/src/app/(app)/inventory/page.tsx:1239 |
| C0202 | Print QR sticker | local state / inspect handler | {() => openMaterialQrSticker(s, batch)} | frontend/src/app/(app)/inventory/page.tsx:1320 |
| C0203 | Edit | local state / inspect handler | {() => openEditItem(s, batch)} | frontend/src/app/(app)/inventory/page.tsx:1325 |
| C0204 | Delete | local state / inspect handler | {() => deleteBatch(batch)} | frontend/src/app/(app)/inventory/page.tsx:1330 |
| C0205 | Print QR sticker | local state / inspect handler | {() => openMaterialQrSticker(s, batch)} | frontend/src/app/(app)/inventory/page.tsx:1447 |
| C0206 | Edit | local state / inspect handler | {() => openEditItem(s, batch)} | frontend/src/app/(app)/inventory/page.tsx:1452 |
| C0207 | Delete | local state / inspect handler | {() => deleteBatch(batch)} | frontend/src/app/(app)/inventory/page.tsx:1457 |
| C0208 | Load more | local state / inspect handler | {() => setInventoryRenderLimit((current) => ( Math.min(current + INVENTORY_RENDER_PAGE_SIZE, inventoryRows.length) ))} | frontend/src/app/(app)/inventory/page.tsx:1473 |
| C0209 | Form submission | save/change data | {saveItem} | frontend/src/app/(app)/inventory/page.tsx:1509 |
| C0210 | Add row | local state / inspect handler | {addCompositionRow} | frontend/src/app/(app)/inventory/page.tsx:1613 |
| C0211 | Remove | local state / inspect handler | {() => removeCompositionRow(index)} | frontend/src/app/(app)/inventory/page.tsx:1637 |
| C0212 | Cancel | local state / inspect handler | {() => { setEditingItem(null); setEditingBatch(null); setEditingStock(null); setBatchForm(EMPTY_BATCH_FORM); }} | frontend/src/app/(app)/inventory/page.tsx:1763 |
| C0213 | Saving... / Save | local state / inspect handler | Local form behavior | frontend/src/app/(app)/inventory/page.tsx:1766 |
| C0214 | Form submission | save/change data | {submitAccessoryIssue} | frontend/src/app/(app)/inventory/page.tsx:1778 |
| C0215 | Add Accessory.toLowerCase() | local state / inspect handler | {addExtraIssueLine} | frontend/src/app/(app)/inventory/page.tsx:1888 |
| C0216 | Remove | local state / inspect handler | {() => removeExtraIssueLine(line.key)} | frontend/src/app/(app)/inventory/page.tsx:1938 |
| C0217 | Cancel | open/close dialog | {closeIssueModal} | frontend/src/app/(app)/inventory/page.tsx:1947 |
| C0218 | Saving... / Issue accessories | local state / inspect handler | Local form behavior | frontend/src/app/(app)/inventory/page.tsx:1948 |
| C0219 | Manual issue | open/close dialog | {openManualIssueModal} | frontend/src/app/(app)/inventory/page.tsx:1986 |
| C0220 | Issue accessories | open/close dialog | {() => openIssueModal(row)} | frontend/src/app/(app)/inventory/page.tsx:2029 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0801 | Previous | local state / inspect handler | {() => setPreviewRoll((value) => Math.max(1, value - 1))} | frontend/src/components/MaterialQrStickerModal.tsx:147 |
| C0802 | Next | local state / inspect handler | {() => setPreviewRoll((value) => Math.min(rollCount, value + 1))} | frontend/src/components/MaterialQrStickerModal.tsx:149 |
| C0803 | Close | local state / inspect handler | {onClose} | frontend/src/components/MaterialQrStickerModal.tsx:157 |
| C0804 | Print | print | {printLabels} | frontend/src/components/MaterialQrStickerModal.tsx:158 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P045 /inventory/receive

Source: [page](../../frontend/src/app/(app)/inventory/receive/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0221 | <img src={storageThumbnailUrl(url, 320)} alt={alt} className="h-full w-full object-cover" /> / preview | open new tab | isImage ? imagePreviewHref(url, alt) : url | frontend/src/app/(app)/inventory/receive/page.tsx:225 |
| C0222 | Form submission | submit form | {onSubmit} | frontend/src/app/(app)/inventory/receive/page.tsx:283 |
| C0223 | Add color | local state / inspect handler | {() => setShowColorInput(true)} | frontend/src/app/(app)/inventory/receive/page.tsx:355 |
| C0224 | Add | local state / inspect handler | {addColor} | frontend/src/app/(app)/inventory/receive/page.tsx:378 |
| C0225 | Cancel | local state / inspect handler | {() => { setNewColor(""); setShowColorInput(false); }} | frontend/src/app/(app)/inventory/receive/page.tsx:381 |
| C0226 | submitLabel | local state / inspect handler | Local form behavior | frontend/src/app/(app)/inventory/receive/page.tsx:528 |
| C0227 | Form submission | save/change data | {submitAccessoryIssue} | frontend/src/app/(app)/inventory/receive/page.tsx:809 |
| C0228 | Saving... / Issue accessories | local state / inspect handler | Local form behavior | frontend/src/app/(app)/inventory/receive/page.tsx:898 |
| C0805 | Add roll | local state / inspect handler | {() => onChange([...values, ""], [...(lengths \|\| values.map(() => "")), ""])} | frontend/src/components/MaterialRollWeightFields.tsx:40 |
| C0806 | Remove roll | local state / inspect handler | {() => onChange(values.filter((_, valueIndex) => valueIndex !== index), (lengths \|\| []).filter((_, valueIndex) => valueIndex !== index))} | frontend/src/components/MaterialRollWeightFields.tsx:76 |

## P046 /models/[id]

Source: [page](../../frontend/src/app/(app)/models/[id]/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0242 | Retry | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/models/[id]/page.tsx:521 |
| C0243 | label badgeValue | filter/select/expand | {() => setTab(index)} | frontend/src/app/(app)/models/[id]/page.tsx:1001 |
| C0244 | Form submission | save/change data | {(e) => addImage(e, imageType)} | frontend/src/app/(app)/models/[id]/page.tsx:1027 |
| C0245 | Uploading... / uploadOptionTitle(imageType) | local state / inspect handler | Local form behavior | frontend/src/app/(app)/models/[id]/page.tsx:1045 |
| C0246 | Saving... / Generate sizes | save/change data | {generateModelSizeRange} | frontend/src/app/(app)/models/[id]/page.tsx:1074 |
| C0247 | Back to Usluga models / Models | open page/link | modelPageBase | frontend/src/app/(app)/models/[id]/page.tsx:1098 |
| C0248 | Cloning... / Clone | navigate after action | `${modelPageBase}/${cloned.id}?mode=edit` | frontend/src/app/(app)/models/[id]/page.tsx:1101 |
| C0249 | View | open page/link | `${modelPageBase}/${id}` | frontend/src/app/(app)/models/[id]/page.tsx:1105 |
| C0250 | Edit | open page/link | `${modelPageBase}/${id}?mode=edit` | frontend/src/app/(app)/models/[id]/page.tsx:1106 |
| C0251 | Icon control at line 1193 | open new tab | imagePreviewHref(primaryImage.file_url, primaryImage.file_name \|\| modelForm.name \|\| t("field.picture")) | frontend/src/app/(app)/models/[id]/page.tsx:1193 |
| C0252 | Remove | local state / inspect handler | {() => removeModelCompositionRow(index)} | frontend/src/app/(app)/models/[id]/page.tsx:1275 |
| C0253 | Add row | local state / inspect handler | {addModelCompositionRow} | frontend/src/app/(app)/models/[id]/page.tsx:1290 |
| C0254 | + Add to fabrics | local state / inspect handler | {resetBomForm} | frontend/src/app/(app)/models/[id]/page.tsx:1302 |
| C0255 | Edit | local state / inspect handler | {() => editBom(r, "material")} | frontend/src/app/(app)/models/[id]/page.tsx:1320 |
| C0256 | Delete | local state / inspect handler | {() => deleteBom(r)} | frontend/src/app/(app)/models/[id]/page.tsx:1323 |
| C0257 | Form submission | save/change data | {(e) => addBom(e, "material")} | frontend/src/app/(app)/models/[id]/page.tsx:1334 |
| C0258 | Save / Add | submit form | Local form behavior | frontend/src/app/(app)/models/[id]/page.tsx:1369 |
| C0259 | Cancel | local state / inspect handler | {resetBomForm} | frontend/src/app/(app)/models/[id]/page.tsx:1370 |
| C0260 | + Add to accessories | local state / inspect handler | {resetBomForm} | frontend/src/app/(app)/models/[id]/page.tsx:1376 |
| C0261 | Edit | local state / inspect handler | {() => editBom(r, "accessory")} | frontend/src/app/(app)/models/[id]/page.tsx:1393 |
| C0262 | Delete | local state / inspect handler | {() => deleteBom(r)} | frontend/src/app/(app)/models/[id]/page.tsx:1396 |
| C0263 | Form submission | save/change data | {(e) => addBom(e, "accessory")} | frontend/src/app/(app)/models/[id]/page.tsx:1409 |
| C0264 | Save / Add | submit form | Local form behavior | frontend/src/app/(app)/models/[id]/page.tsx:1423 |
| C0265 | Cancel | local state / inspect handler | {resetBomForm} | frontend/src/app/(app)/models/[id]/page.tsx:1424 |
| C0266 | Form submission | navigate after action | `${modelPageBase}/${createdVariantId}?mode=edit` | frontend/src/app/(app)/models/[id]/page.tsx:1461 |
| C0267 | Icon control at line 1498 | open new tab | imagePreviewHref(selectedVariantPictureUrl, variantForm.variant_no \|\| t("field.picture")) | frontend/src/app/(app)/models/[id]/page.tsx:1498 |
| C0268 | Saving... / editingVariantId ? Save variant : Create variant | submit form | Local form behavior | frontend/src/app/(app)/models/[id]/page.tsx:1516 |
| C0269 | Cancel | local state / inspect handler | {resetVariantForm} | frontend/src/app/(app)/models/[id]/page.tsx:1519 |
| C0270 | Loading... / Add variant | filter/select/expand | {openNewVariantForm} | frontend/src/app/(app)/models/[id]/page.tsx:1524 |
| C0271 | Icon control at line 1555 | open new tab | imagePreviewHref(v.picture_url, v.variant_no \|\| v.code \|\| "") | frontend/src/app/(app)/models/[id]/page.tsx:1555 |
| C0272 | v.variant_no \|\| v.code \|\| "-" | open page/link | `${modelPageBase}/${variantId}` | frontend/src/app/(app)/models/[id]/page.tsx:1566 |
| C0273 | Edit | local state / inspect handler | {() => startEditVariant(v)} | frontend/src/app/(app)/models/[id]/page.tsx:1582 |
| C0274 | Delete | navigate after action | /models | frontend/src/app/(app)/models/[id]/page.tsx:1591 |
| C0275 | Loading... / Load more | filter/select/expand | {() => setVariantPageCount(variantPageCount + 1)} | frontend/src/app/(app)/models/[id]/page.tsx:1616 |
| C0276 | Icon control at line 1653 | open new tab | imagePreviewHref(img.file_url, name) | frontend/src/app/(app)/models/[id]/page.tsx:1653 |
| C0277 | Download | open page/link | img.file_url | frontend/src/app/(app)/models/[id]/page.tsx:1664 |
| C0278 | Delete | local state / inspect handler | {() => deleteImage(img.id)} | frontend/src/app/(app)/models/[id]/page.tsx:1665 |
| C0279 | Icon control at line 1689 | open new tab | imagePreviewHref(primaryImage.file_url, translatedName) | frontend/src/app/(app)/models/[id]/page.tsx:1689 |
| C0280 | Form submission | save/change data | {addSize} | frontend/src/app/(app)/models/[id]/page.tsx:1740 |
| C0281 | Add | submit form | Local form behavior | frontend/src/app/(app)/models/[id]/page.tsx:1747 |
| C0282 | Delete | local state / inspect handler | {() => deleteSize(s.id)} | frontend/src/app/(app)/models/[id]/page.tsx:1761 |
| C0283 | Create new model / Save | navigate after action | `${modelPageBase}/${created.id}?mode=edit` | frontend/src/app/(app)/models/[id]/page.tsx:1822 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0837 | Remove operation | local state / inspect handler | {() => onRemove(operation.id)} | frontend/src/components/PaidOperationsEditor.tsx:74 |
| C0838 | copy.add | local state / inspect handler | {() => { setCreating(!creating); setName(query); setMessage(null); }} | frontend/src/components/PaidProcessPicker.tsx:64 |
| C0839 | Saving... / copy.create | local state / inspect handler | {create} | frontend/src/components/PaidProcessPicker.tsx:71 |
| C0840 | copy.cancel | local state / inspect handler | {() => setCreating(false)} | frontend/src/components/PaidProcessPicker.tsx:72 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P047 /models

Source: [page](../../frontend/src/app/(app)/models/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0229 | Create new model | open page/link | `${modelPageBase}/new` | frontend/src/app/(app)/models/page.tsx:180 |
| C0230 | Hide filters / Show filters | filter/select/expand | {() => setShowFilters((open) => !open)} | frontend/src/app/(app)/models/page.tsx:183 |
| C0231 | Create new model | open page/link | `${modelPageBase}/new` | frontend/src/app/(app)/models/page.tsx:186 |
| C0232 | Form submission | submit form | {(e) => e.preventDefault()} | frontend/src/app/(app)/models/page.tsx:188 |
| C0233 | Retry | local state / inspect handler | {() => void mutate()} | frontend/src/app/(app)/models/page.tsx:250 |
| C0234 | ( <VerticalModelPhoto src={imageUrl} alt={modelName} className="w-full border-r border-[#e3dfd3]" loading="lazy" width={240} height={320} adaptiveHeight /> ) / ( <div className="flex aspect-[3/4] w-full flex-col items-ce [dynamic label] | open page/link | `${modelPageBase}/${m.id}` | frontend/src/app/(app)/models/page.tsx:277 |
| C0235 | modelName | open page/link | `${modelPageBase}/${m.id}` | frontend/src/app/(app)/models/page.tsx:301 |
| C0236 | ( <img src={thumb} alt={option.variantNo \|\| option.code} className="h-full w-full object-contain p-1" loading="lazy" /> ) / ( <div className="flex h-full items-center justify-center text-[10px] text-[#8a8472]">{No image} [dynamic label] | open page/link | `${modelPageBase}/${variant.model_id \|\| variant.id}` | frontend/src/app/(app)/models/page.tsx:312 |
| C0237 | View | open page/link | `${modelPageBase}/${m.id}` | frontend/src/app/(app)/models/page.tsx:366 |
| C0238 | Approve | save/change data | {() => approve(m.id)} | frontend/src/app/(app)/models/page.tsx:368 |
| C0239 | Cloning... / Clone | navigate after action | `${modelPageBase}/${cloned.id}?mode=edit` | frontend/src/app/(app)/models/page.tsx:372 |
| C0240 | Edit | open page/link | `${modelPageBase}/${m.id}?mode=edit` | frontend/src/app/(app)/models/page.tsx:380 |
| C0241 | Delete | local state / inspect handler | {() => removeModel(m)} | frontend/src/app/(app)/models/page.tsx:381 |
| C0757 | cancelText ?? Cancel | local state / inspect handler | {onCancel} | frontend/src/components/ConfirmDialog.tsx:30 |
| C0758 | confirmText ?? Confirm | local state / inspect handler | {onConfirm} | frontend/src/components/ConfirmDialog.tsx:31 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P048 /order-history

Source: [page](../../frontend/src/app/(app)/order-history/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0284 | Clear | local state / inspect handler | {() => setQuery("")} | frontend/src/app/(app)/order-history/page.tsx:477 |
| C0285 | formatOrderReference(row.order_no) row.group_order_no \|\| "-" ( <div className="flex items-center gap-3"> {product.picture_url ? ( <Image src={product.picture_url} alt={[product.model_no \|\| product.code, product.variant_n [dynamic label] | filter/select/expand | {() => { setSelectedKey(row.history_key); setDetailTab("overview"); }} | frontend/src/app/(app)/order-history/page.tsx:517 |
| C0286 | formatOrderReference(row.order_no) | filter/select/expand | {(event) => { event.stopPropagation(); setSelectedKey(row.history_key); setDetailTab("overview"); }} | frontend/src/app/(app)/order-history/page.tsx:526 |
| C0287 | label | filter/select/expand | {() => setDetailTab(tab)} | frontend/src/app/(app)/order-history/page.tsx:615 |
| C0288 | formatOrderReference(detail.order_no) | open page/link | detail.record_type === "production_order" ? `/production-orders/${detail.id}` : `/sales-orders/${detail.id}` | frontend/src/app/(app)/order-history/page.tsx:630 |
| C0289 | orderReference(po, po.production_no) | open page/link | `/production-orders/${po.id}` | frontend/src/app/(app)/order-history/page.tsx:760 |
| C0290 | pkg.package_no | open page/link | `/packages/${pkg.id}` | frontend/src/app/(app)/order-history/page.tsx:799 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P049 /packages/[id]

Source: [page](../../frontend/src/app/(app)/packages/[id]/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0317 | Print label | local state / inspect handler | {() => api.openLabel(`/api/packages/${p.id}/label`)} | frontend/src/app/(app)/packages/[id]/page.tsx:29 |
| C0318 | Traceability | open page/link | `/traceability?package=${encodeURIComponent(p.package_no \|\| p.barcode \|\| p.id)}` | frontend/src/app/(app)/packages/[id]/page.tsx:31 |

## P050 /packages

Source: [page](../../frontend/src/app/(app)/packages/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0291 | Receive from Sewing | open page/link | `/packaging/receive?packaging_department=${packagingDepartment}` | frontend/src/app/(app)/packages/page.tsx:301 |
| C0292 | Close / Open | filter/select/expand | {() => setExpandedGroups((prev) => ({ ...prev, [g.key]: !prev[g.key] }))} | frontend/src/app/(app)/packages/page.tsx:360 |
| C0293 | Print | local state / inspect handler | {() => api.openLabel(`/api/packages/label-sheet/by-ids?ids=${encodeURIComponent(packageIds)}`)} | frontend/src/app/(app)/packages/page.tsx:368 |
| C0294 | View | open page/link | `/packages/${p.id}` | frontend/src/app/(app)/packages/page.tsx:402 |
| C0295 | Passport | open page/link | `/traceability?package=${encodeURIComponent(p.package_no \|\| p.barcode \|\| p.id)}` | frontend/src/app/(app)/packages/page.tsx:404 |
| C0296 | Label | local state / inspect handler | {() => api.openLabel(`/api/packages/${p.id}/label`)} | frontend/src/app/(app)/packages/page.tsx:408 |
| C0297 | Edit | local state / inspect handler | {() => openEdit(p)} | frontend/src/app/(app)/packages/page.tsx:409 |
| C0298 | Delete | local state / inspect handler | {() => setDeleting(p)} | frontend/src/app/(app)/packages/page.tsx:410 |
| C0299 | Approve | save/change data | {() => approveRequest(pending)} | frontend/src/app/(app)/packages/page.tsx:413 |
| C0300 | Reject | save/change data | {() => rejectRequest(pending)} | frontend/src/app/(app)/packages/page.tsx:414 |
| C0301 | Form submission | save/change data | {submitEditRequest} | frontend/src/app/(app)/packages/page.tsx:450 |
| C0302 | Add | local state / inspect handler | {addItemRow} | frontend/src/app/(app)/packages/page.tsx:481 |
| C0303 | Remove | local state / inspect handler | {() => removeItemRow(idx)} | frontend/src/app/(app)/packages/page.tsx:488 |
| C0304 | Cancel | local state / inspect handler | {() => { setEditing(null); setEditForm(null); }} | frontend/src/app/(app)/packages/page.tsx:518 |
| C0305 | Saving... / Request approval | submit form | Local form behavior | frontend/src/app/(app)/packages/page.tsx:519 |
| C0757 | cancelText ?? Cancel | local state / inspect handler | {onCancel} | frontend/src/components/ConfirmDialog.tsx:30 |
| C0758 | confirmText ?? Confirm | local state / inspect handler | {onConfirm} | frontend/src/components/ConfirmDialog.tsx:31 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P051 /packages/scan

Source: [page](../../frontend/src/app/(app)/packages/scan/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0306 | copy.printSelected | local state / inspect handler | {async () => { try { await api.openLabel(`/api/packages/label-sheet/by-ids?ids=${selectedIds.join(",")}`); } catch (e: any) { setMsg(e.message); } }} | frontend/src/app/(app)/packages/scan/page.tsx:264 |
| C0307 | Loading... / Lookup | filter/select/expand | {() => lookup()} | frontend/src/app/(app)/packages/scan/page.tsx:290 |
| C0308 | Select packed | filter/select/expand | {selectPackedOnly} | frontend/src/app/(app)/packages/scan/page.tsx:310 |
| C0309 | Select all | filter/select/expand | {selectAllScanned} | frontend/src/app/(app)/packages/scan/page.tsx:314 |
| C0310 | Clear | filter/select/expand | {clearQueue} | frontend/src/app/(app)/packages/scan/page.tsx:317 |
| C0311 | Receiving... / Receive selected | filter/select/expand | {receiveSelected} | frontend/src/app/(app)/packages/scan/page.tsx:336 |
| C0312 | Moving... / Move selected | filter/select/expand | {moveSelected} | frontend/src/app/(app)/packages/scan/page.tsx:345 |
| C0313 | pkg.package_no pkg.barcode \|\| "-" packageOrderLabel(pkg) formatOrderReference(pkg.production_no \|\| "-") ( <img src={imageUrl} alt={pkg.model_name \|\| pkg.model_code \|\| ""} className="h-12 w-12 rounded-md border border-[#e [dynamic label] | local state / inspect handler | {() => setActivePackageId(pkg.id)} | frontend/src/app/(app)/packages/scan/page.tsx:376 |
| C0314 | {(e) => e.stopPropagation()} | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/app/(app)/packages/scan/page.tsx:378 |
| C0315 | {(e) => { e.stopPropagation(); removePackage(pkg.id); }} | filter/select/expand | {(e) => { e.stopPropagation(); removePackage(pkg.id); }} | frontend/src/app/(app)/packages/scan/page.tsx:413 |
| C0316 | Print label | local state / inspect handler | {() => api.openLabel(`/api/packages/${activePackage.id}/label`)} | frontend/src/app/(app)/packages/scan/page.tsx:467 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0796 | c.manual | open/close dialog | {() => { setOpen(true); setResult(null); }} | frontend/src/components/ManualPackageReceipt.tsx:40 |
| C0797 | Form submission | submit form | {async event => { event.preventDefault(); setBusy(true); setError(""); try { const saved = await postPackageWorkflow<{ receipt_no: string; print_run: PackagePrintRun }>("/api/packages/manual-receipt", pendingBody \|\| { model_id: model, color, weight_kg: Number(weight), count: quantities.length, pack_quantities: quantities.map(Number), }, me!.id); setPendingBody(null); setResult(saved); onCreated(); } catch (e: any) { setError(e.message); setPendingBody(pendingPackageWorkflow("/api/packages/manual-receipt", me!.id)?.body \|\| null); } finally { setBusy(false); } }} | frontend/src/components/ManualPackageReceipt.tsx:42 |
| C0798 | c.reprint | local state / inspect handler | {async () => { try { await api.openLabel(`/api/packages/print-runs/${result.print_run.id}/label`); } catch (e: any) { setError(e.message); } }} | frontend/src/components/ManualPackageReceipt.tsx:59 |
| C0799 | c.loading / pendingBody ? c.retry : c.save | submit form | Local form behavior | frontend/src/components/ManualPackageReceipt.tsx:90 |
| C0800 | c.cancel | open/close dialog | {() => setOpen(false)} | frontend/src/components/ManualPackageReceipt.tsx:92 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0816 | copy.reprint | local state / inspect handler | {async () => { setPrintError(""); try { await api.openLabel(`/api/packages/print-runs/${run.id}/label`); } catch (e: any) { setPrintError(e.message); } }} | frontend/src/components/PackagePrintRuns.tsx:33 |
| C0817 | copy.deletePacks | filter/select/expand | {() => { setSelectedRun(run); setSelectedIds([]); }} | frontend/src/components/PackagePrintRuns.tsx:37 |
| C0818 | copy.cancel | filter/select/expand | {() => setSelectedRun(null)} | frontend/src/components/PackagePrintRuns.tsx:44 |
| C0819 | copy.deletePacks ( selectedIds.length ) | filter/select/expand | {async () => { if (!selectedRun \|\| !(await dialogs.ask({ message: `${selectedRun.run_no} · ${selectedIds.length} ${copy.packages}. ${copy.deleteConfirm}` }))) return; setDeleting(selectedRun.id); setPrintError(""); try { const query = new URLSearchParams(selectedIds.map(id => ["package_ids", String(id)])); await api.del(`/api/packages/print-runs/${selectedRun.id}/manual-packages?${query}`); setSelectedRun(null); setSelectedIds([]); await mutate(); await mutateCache(key => typeof key === "string" && (key.startsWith("/api/packages") \|\| key.startsWith("/api/finished-goods"))); } catch (e: any) { setPrintError(e.message); } finally { setDeleting(null); } }} | frontend/src/components/PackagePrintRuns.tsx:44 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |
| C0941 | `${cell.code}${cell.count ? ` - ${cell.count} ${Package}` : ""}` | local state / inspect handler | {() => onSelectCell?.(cell.code)} | frontend/src/components/WarehouseMap.tsx:95 |

## P052 /packaging/queue

Source: [page](../../frontend/src/app/(app)/packaging/queue/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0319 | Refresh | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/packaging/queue/page.tsx:65 |
| C0320 | Form submission | filter/select/expand | {submitSearch} | frontend/src/app/(app)/packaging/queue/page.tsx:73 |
| C0321 | Search | submit form | Local form behavior | frontend/src/app/(app)/packaging/queue/page.tsx:83 |
| C0322 | Packing | open page/link | `/work-orders/${row.work_order_id}/packaging` | frontend/src/app/(app)/packaging/queue/page.tsx:132 |

## P053 /packaging/receive

Source: [page](../../frontend/src/app/(app)/packaging/receive/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0323 | Refresh | local state / inspect handler | {refreshData} | frontend/src/app/(app)/packaging/receive/page.tsx:181 |
| C0324 | Form submission | submit form | {receiveScan} | frontend/src/app/(app)/packaging/receive/page.tsx:193 |
| C0325 | Receiving... / Receive | submit form | Local form behavior | frontend/src/app/(app)/packaging/receive/page.tsx:207 |
| C0326 | Form submission | filter/select/expand | {submitSearch} | frontend/src/app/(app)/packaging/receive/page.tsx:225 |
| C0327 | Search | submit form | Local form behavior | frontend/src/app/(app)/packaging/receive/page.tsx:235 |
| C0328 | Receiving... / Receive | local state / inspect handler | {() => receiveManual(option)} | frontend/src/app/(app)/packaging/receive/page.tsx:282 |

## P054 /packaging/reports

Source: [page](../../frontend/src/app/(app)/packaging/reports/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0329 | Refresh | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/packaging/reports/page.tsx:80 |
| C0330 | t(downloading ? "common.loading" : "packagingReport.excel") | download/export | {download} | frontend/src/app/(app)/packaging/reports/page.tsx:83 |
| C0331 | t(`packagingReport.${key}`) | filter/select/expand | {() => setTab(key)} | frontend/src/app/(app)/packaging/reports/page.tsx:91 |
| C0834 | Show more ( visible / rows.length ) | local state / inspect handler | {() => setVisible((count) => count + 100)} | frontend/src/components/PackagingReportTable.tsx:38 |

## P055 /

Source: [page](../../frontend/src/app/(app)/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0332 | t(formatRangeLabel(datePreset)) | local state / inspect handler | {() => setShowDateMenu((v) => !v)} | frontend/src/app/(app)/page.tsx:234 |
| C0333 | Apply custom range | local state / inspect handler | {applyCustomRange} | frontend/src/app/(app)/page.tsx:275 |
| C0334 | Export | download/export | {exportOrders} | frontend/src/app/(app)/page.tsx:281 |
| C0335 | + New Order.replace("+ ", "") | open page/link | /sales-orders/new | frontend/src/app/(app)/page.tsx:284 |
| C0336 | All | local state / inspect handler | {() => setKind("all")} | frontend/src/app/(app)/page.tsx:305 |
| C0337 | Client order | local state / inspect handler | {() => setKind("client_order")} | frontend/src/app/(app)/page.tsx:306 |
| C0338 | Branded stock sale | local state / inspect handler | {() => setKind("branded_stock_sale")} | frontend/src/app/(app)/page.tsx:307 |
| C0339 | View all -&gt; | open page/link | /sales-orders | frontend/src/app/(app)/page.tsx:309 |
| C0340 | o.order_no | open page/link | `/sales-orders/${o.id}` | frontend/src/app/(app)/page.tsx:325 |
| C0341 | o.order_no | open page/link | `/sales-orders/${o.id}` | frontend/src/app/(app)/page.tsx:375 |
| C0342 | Process Tracking Follow every order across cutting, sewing and packaging. | open page/link | /processes | frontend/src/app/(app)/page.tsx:425 |
| C0343 | Sewing Floor Inspect line load, operators and active bundles. | open page/link | /sewing/flows | frontend/src/app/(app)/page.tsx:431 |
| C0766 | item.label | local state / inspect handler | {() => setHidden(hidden.includes(item.key) ? hidden.filter(key => key !== item.key) : [...hidden, item.key])} | frontend/src/components/dashboard/ActivityLineChart.tsx:47 |
| C0767 | copy.more | local state / inspect handler | {onWiden} | frontend/src/components/dashboard/ActivityLineChart.tsx:71 |
| C0768 | `${point.date}: ${series.map(item => `${item.label} ${point.values[item.key] \|\| 0}`).join(", ")}` | filter/select/expand | {() => setSelected(i)} | frontend/src/components/dashboard/ActivityLineChart.tsx:99 |
| C0769 | `${copy.select}: ${factory.name}` | local state / inspect handler | {() => onSelect(factory.code)} | frontend/src/components/dashboard/FactoryComparison.tsx:37 |
| C0770 | activityCopy.exportReports / copy.export | download/export | {exportOutput} | frontend/src/components/dashboard/ManagementDashboard.tsx:76 |
| C0771 | copy.refresh | local state / inspect handler | {() => { setToday(businessDate()); void mutate(); }} | frontend/src/components/dashboard/ManagementDashboard.tsx:77 |
| C0772 | copy.newOrder | open page/link | /sales-orders/new | frontend/src/components/dashboard/ManagementDashboard.tsx:78 |
| C0773 | factoriesCopy.all / factoryNames[code] | local state / inspect handler | {() => setFactory(code)} | frontend/src/components/dashboard/ManagementDashboard.tsx:83 |
| C0774 | copy.refresh | local state / inspect handler | {() => void mutate()} | frontend/src/components/dashboard/ManagementDashboard.tsx:88 |
| C0775 | activityCopy.reports / activityCopy.stages | local state / inspect handler | {() => setChartSource(source)} | frontend/src/components/dashboard/ManagementDashboard.tsx:105 |
| C0776 | copy.view | open page/link | /production-orders | frontend/src/components/dashboard/ManagementDashboard.tsx:115 |
| C0777 | o.order_no | open page/link | orderHref(o)! | frontend/src/components/dashboard/ManagementDashboard.tsx:118 |

## P056 /payroll

Source: [page](../../frontend/src/app/(app)/payroll/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0344 | Refresh | local state / inspect handler | {refreshAll} | frontend/src/app/(app)/payroll/page.tsx:415 |
| C0345 | Form submission | save/change data | {createPeriod} | frontend/src/app/(app)/payroll/page.tsx:425 |
| C0346 | Create period | local state / inspect handler | Local form behavior | frontend/src/app/(app)/payroll/page.tsx:456 |
| C0347 | open | save/change data | {() => patchPeriod(period, { status: "open" })} | frontend/src/app/(app)/payroll/page.tsx:494 |
| C0348 | Lock | save/change data | {() => periodAction(period, "lock")} | frontend/src/app/(app)/payroll/page.tsx:500 |
| C0349 | Approve | save/change data | {() => periodAction(period, "approve")} | frontend/src/app/(app)/payroll/page.tsx:506 |
| C0350 | Paid | save/change data | {() => periodAction(period, "mark-paid")} | frontend/src/app/(app)/payroll/page.tsx:512 |
| C0351 | Form submission | save/change data | {createAdjustment} | frontend/src/app/(app)/payroll/page.tsx:597 |
| C0352 | Add adjustment | local state / inspect handler | Local form behavior | frontend/src/app/(app)/payroll/page.tsx:662 |
| C0353 | Delete | local state / inspect handler | {() => deleteAdjustment(adjustment)} | frontend/src/app/(app)/payroll/page.tsx:712 |
| C0354 | Form submission | save/change data | {createReversal} | frontend/src/app/(app)/payroll/page.tsx:810 |
| C0355 | Cancel | local state / inspect handler | {() => setReversalForm({ record: null, target_period_id: "", reason: "" })} | frontend/src/app/(app)/payroll/page.tsx:822 |
| C0356 | Post reversal | submit form | Local form behavior | frontend/src/app/(app)/payroll/page.tsx:860 |
| C0357 | Void | save/change data | {() => voidRecord(record)} | frontend/src/app/(app)/payroll/page.tsx:927 |
| C0358 | Reverse as adjustment | local state / inspect handler | {() => startReversal(record)} | frontend/src/app/(app)/payroll/page.tsx:932 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P057 /payroll/qr-control

Source: [page](../../frontend/src/app/(app)/payroll/qr-control/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0359 | Refresh | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/payroll/qr-control/page.tsx:230 |
| C0360 | <ChevronDown size={18} /> / <ChevronRight size={18} /> formatOrderReference(group.orderNo) | filter/select/expand | {() => setExpanded((current) => ({ ...current, [group.orderNo]: !current[group.orderNo] }))} | frontend/src/app/(app)/payroll/qr-control/page.tsx:296 |
| C0361 | Preparing... / Reprint labels | print | {() => reprintOrder(group.orderNo)} | frontend/src/app/(app)/payroll/qr-control/page.tsx:308 |
| C0362 | Return QR | save/change data | {() => returnLabel(row)} | frontend/src/app/(app)/payroll/qr-control/page.tsx:351 |
| C0363 | Previous | filter/select/expand | {() => setPage((current) => Math.max(0, current - 1))} | frontend/src/app/(app)/payroll/qr-control/page.tsx:380 |
| C0364 | Next | filter/select/expand | {() => setPage((current) => current + 1)} | frontend/src/app/(app)/payroll/qr-control/page.tsx:383 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P058 /payroll/reports/order-qr-status

Source: [page](../../frontend/src/app/(app)/payroll/reports/order-qr-status/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0365 | Form submission | filter/select/expand | {chooseOrder} | frontend/src/app/(app)/payroll/reports/order-qr-status/page.tsx:118 |
| C0366 | View order | submit form | Local form behavior | frontend/src/app/(app)/payroll/reports/order-qr-status/page.tsx:142 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P059 /payroll/reports/sewing-production

Source: [page](../../frontend/src/app/(app)/payroll/reports/sewing-production/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0367 | Exporting… / "Excel" | download/export | {exportExcel} | frontend/src/app/(app)/payroll/reports/sewing-production/page.tsx:257 |
| C0368 | Preparing… / Print | print | {printReport} | frontend/src/app/(app)/payroll/reports/sewing-production/page.tsx:261 |
| C0369 | t(view === "salary" ? "page.sewingReport.salarySummary" : "page.sewingReport.scanDetails") | filter/select/expand | {() => { setReportView(view); setPage(1); setActionError(""); }} | frontend/src/app/(app)/payroll/reports/sewing-production/page.tsx:272 |
| C0370 | Form submission | filter/select/expand | {applyFilters} | frontend/src/app/(app)/payroll/reports/sewing-production/page.tsx:280 |
| C0371 | Reset | filter/select/expand | {resetFilters} | frontend/src/app/(app)/payroll/reports/sewing-production/page.tsx:393 |
| C0372 | Build report | submit form | Local form behavior | frontend/src/app/(app)/payroll/reports/sewing-production/page.tsx:397 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P060 /payroll/scan

Source: [page](../../frontend/src/app/(app)/payroll/scan/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0373 | Focus scanner | local state / inspect handler | {() => inputRef.current?.focus()} | frontend/src/app/(app)/payroll/scan/page.tsx:1160 |
| C0374 | CSV | download/export | {exportCsv} | frontend/src/app/(app)/payroll/scan/page.tsx:1164 |
| C0375 | Clear | local state / inspect handler | {clearRecords} | frontend/src/app/(app)/payroll/scan/page.tsx:1168 |
| C0376 | Form submission | submit form | {submitScan} | frontend/src/app/(app)/payroll/scan/page.tsx:1188 |
| C0377 | Scan | submit form | Local form behavior | frontend/src/app/(app)/payroll/scan/page.tsx:1207 |
| C0378 | Show latest / Show all | local state / inspect handler | {() => setShowAllHistory((current) => !current)} | frontend/src/app/(app)/payroll/scan/page.tsx:1323 |
| C0379 | Undo last | local state / inspect handler | {() => { if (latestRemovableRecord) removeRecord(latestRemovableRecord.id); }} | frontend/src/app/(app)/payroll/scan/page.tsx:1331 |
| C0380 | canSavePayroll ? Save this scan : No payroll save permission | local state / inspect handler | {() => saveRecordsToPayroll([record])} | frontend/src/app/(app)/payroll/scan/page.tsx:1419 |
| C0381 | Remove local scan | local state / inspect handler | {() => removeRecord(record.id)} | frontend/src/app/(app)/payroll/scan/page.tsx:1431 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0841 | text.saving / text.confirm | local state / inspect handler | {onConfirm} | frontend/src/components/payroll/ControlScanReview.tsx:72 |
| C0842 | text.cancel | local state / inspect handler | {onCancel} | frontend/src/components/payroll/ControlScanReview.tsx:73 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P061 /planning/branded-stock

Source: [page](../../frontend/src/app/(app)/planning/branded-stock/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0382 | Forecasting | open page/link | /forecasting | frontend/src/app/(app)/planning/page.tsx:1021 |
| C0383 | row.model_code \|\| row.model_id - row.color \|\| "-" / row.size \|\| "-" Suggested : fmtQty(row.suggested_quantity) row.unit \|\| "pcs" | open page/link | `/planning/branded-stock?model_id=${row.model_id}&color=${encodeURIComponent(row.color \|\| "")}&size=${encodeURIComponent(row.size \|\| "")}&qty=${row.suggested_quantity}` | frontend/src/app/(app)/planning/page.tsx:1025 |
| C0384 | Saving... / Auto Reserve | save/change data | {() => autoReserveMaterials(activeReservationPoId)} | frontend/src/app/(app)/planning/page.tsx:1047 |
| C0385 | formatOrderReference(po.order_no \|\| po.production_no) statusLabel(po.status, t) # po.id | filter/select/expand | {() => setSelectedReservationPoId(Number(po.id))} | frontend/src/app/(app)/planning/page.tsx:1064 |
| C0386 | Reserve by Batch | save/change data | {() => reserveSuggestedBatch(row, batch)} | frontend/src/app/(app)/planning/page.tsx:1149 |
| C0387 | Release reservation | save/change data | {() => releaseReservation(reservation.id)} | frontend/src/app/(app)/planning/page.tsx:1197 |
| C0388 | Creating... / Create Production Order | local state / inspect handler | {() => openMaterialEstimateForSO(o)} | frontend/src/app/(app)/planning/page.tsx:1240 |
| C0389 | Plan batches | local state / inspect handler | {() => openBatchPlannerForSO(o.id)} | frontend/src/app/(app)/planning/page.tsx:1243 |
| C0390 | Add Brand | local state / inspect handler | {() => openNewBrand("batch")} | frontend/src/app/(app)/planning/page.tsx:1311 |
| C0391 | Auto split | local state / inspect handler | {() => setBatchPlan((prev) => prev ? { ...prev, rows: autoSplitBatchRows(prev.totalQty, numberOrFallback(prev.maxPerBatch, 1)) } : prev)} | frontend/src/app/(app)/planning/page.tsx:1348 |
| C0392 | Add batch | local state / inspect handler | {addBatchPlanRow} | frontend/src/app/(app)/planning/page.tsx:1355 |
| C0393 | Remove | local state / inspect handler | {() => removeBatchPlanRow(index)} | frontend/src/app/(app)/planning/page.tsx:1413 |
| C0394 | Cancel | local state / inspect handler | {() => { setBatchPlan(null); setBatchPlanErr(""); }} | frontend/src/app/(app)/planning/page.tsx:1427 |
| C0395 | Creating... / Create production with batches | navigate after action | `/production-orders/${po.id}` | frontend/src/app/(app)/planning/page.tsx:1438 |
| C0396 | Add Brand | local state / inspect handler | {() => openNewBrand("material")} | frontend/src/app/(app)/planning/page.tsx:1506 |
| C0397 | Cancel | local state / inspect handler | {() => { setMaterialEstimate(null); setMaterialEstimateErr(""); }} | frontend/src/app/(app)/planning/page.tsx:1532 |
| C0398 | Creating... / Create Production Order | navigate after action | `/production-orders/${po.id}` | frontend/src/app/(app)/planning/page.tsx:1543 |
| C0399 | Form submission | save/change data | {createBranded} | frontend/src/app/(app)/planning/page.tsx:1575 |
| C0400 | Add Brand | local state / inspect handler | {() => openNewBrand("branded")} | frontend/src/app/(app)/planning/page.tsx:1599 |
| C0401 | Add fabric | local state / inspect handler | {addBrandedMaterial} | frontend/src/app/(app)/planning/page.tsx:1653 |
| C0402 | Remove | local state / inspect handler | {() => removeBrandedMaterial(index)} | frontend/src/app/(app)/planning/page.tsx:1719 |
| C0403 | Cancel | local state / inspect handler | {restoreBrandedModelSizes} | frontend/src/app/(app)/planning/page.tsx:1746 |
| C0404 | Add line | local state / inspect handler | {addBrandedLine} | frontend/src/app/(app)/planning/page.tsx:1750 |
| C0405 | Edit | local state / inspect handler | {() => setBrandedLinesEditing(true)} | frontend/src/app/(app)/planning/page.tsx:1753 |
| C0406 | Distribute equally | local state / inspect handler | {distributeBrandedBySizeRange} | frontend/src/app/(app)/planning/page.tsx:1786 |
| C0407 | Remove | local state / inspect handler | {() => removeBrandedLine(i)} | frontend/src/app/(app)/planning/page.tsx:1834 |
| C0408 | file.file_name \|\| file.file_url | open new tab | file.file_url | frontend/src/app/(app)/planning/page.tsx:1885 |
| C0409 | Remove | local state / inspect handler | {() => setBrandedPrintingAttachments((prev) => prev.filter((_, j) => j !== idx))} | frontend/src/app/(app)/planning/page.tsx:1888 |
| C0410 | View | open page/link | `/production-orders/${brandedSuccess.id}` | frontend/src/app/(app)/planning/page.tsx:1946 |
| C0411 | Creating... / Add production | local state / inspect handler | Local form behavior | frontend/src/app/(app)/planning/page.tsx:1950 |
| C0412 | Form submission | submit form | {createNewBrand} | frontend/src/app/(app)/planning/page.tsx:1966 |
| C0413 | Cancel | local state / inspect handler | {closeNewBrand} | frontend/src/app/(app)/planning/page.tsx:1988 |
| C0414 | Creating... / Create | submit form | Local form behavior | frontend/src/app/(app)/planning/page.tsx:1991 |
| C0735 | label | open new tab | imagePreviewHref(url, label) | frontend/src/components/BrandedModelVariantSelect.tsx:65 |
| C0736 | Creating... / New order | local state / inspect handler | {onNewOrder} | frontend/src/components/BrandedOrderHistory.tsx:107 |
| C0737 | Form submission | submit form | {submitSearch} | frontend/src/components/BrandedOrderHistory.tsx:115 |
| C0738 | Search | submit form | Local form behavior | frontend/src/components/BrandedOrderHistory.tsx:126 |
| C0739 | Clear | filter/select/expand | {clearSearch} | frontend/src/components/BrandedOrderHistory.tsx:131 |
| C0740 | formatOrderReference(production.order_no \|\| production.production_no) | open page/link | `/production-orders/${production.id}` | frontend/src/components/BrandedOrderHistory.tsx:179 |
| C0741 | Add production to this order | local state / inspect handler | {() => onAddProduction(order.id)} | frontend/src/components/BrandedOrderHistory.tsx:229 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P062 /planning

Source: [page](../../frontend/src/app/(app)/planning/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0382 | Forecasting | open page/link | /forecasting | frontend/src/app/(app)/planning/page.tsx:1021 |
| C0383 | row.model_code \|\| row.model_id - row.color \|\| "-" / row.size \|\| "-" Suggested : fmtQty(row.suggested_quantity) row.unit \|\| "pcs" | open page/link | `/planning/branded-stock?model_id=${row.model_id}&color=${encodeURIComponent(row.color \|\| "")}&size=${encodeURIComponent(row.size \|\| "")}&qty=${row.suggested_quantity}` | frontend/src/app/(app)/planning/page.tsx:1025 |
| C0384 | Saving... / Auto Reserve | save/change data | {() => autoReserveMaterials(activeReservationPoId)} | frontend/src/app/(app)/planning/page.tsx:1047 |
| C0385 | formatOrderReference(po.order_no \|\| po.production_no) statusLabel(po.status, t) # po.id | filter/select/expand | {() => setSelectedReservationPoId(Number(po.id))} | frontend/src/app/(app)/planning/page.tsx:1064 |
| C0386 | Reserve by Batch | save/change data | {() => reserveSuggestedBatch(row, batch)} | frontend/src/app/(app)/planning/page.tsx:1149 |
| C0387 | Release reservation | save/change data | {() => releaseReservation(reservation.id)} | frontend/src/app/(app)/planning/page.tsx:1197 |
| C0388 | Creating... / Create Production Order | local state / inspect handler | {() => openMaterialEstimateForSO(o)} | frontend/src/app/(app)/planning/page.tsx:1240 |
| C0389 | Plan batches | local state / inspect handler | {() => openBatchPlannerForSO(o.id)} | frontend/src/app/(app)/planning/page.tsx:1243 |
| C0390 | Add Brand | local state / inspect handler | {() => openNewBrand("batch")} | frontend/src/app/(app)/planning/page.tsx:1311 |
| C0391 | Auto split | local state / inspect handler | {() => setBatchPlan((prev) => prev ? { ...prev, rows: autoSplitBatchRows(prev.totalQty, numberOrFallback(prev.maxPerBatch, 1)) } : prev)} | frontend/src/app/(app)/planning/page.tsx:1348 |
| C0392 | Add batch | local state / inspect handler | {addBatchPlanRow} | frontend/src/app/(app)/planning/page.tsx:1355 |
| C0393 | Remove | local state / inspect handler | {() => removeBatchPlanRow(index)} | frontend/src/app/(app)/planning/page.tsx:1413 |
| C0394 | Cancel | local state / inspect handler | {() => { setBatchPlan(null); setBatchPlanErr(""); }} | frontend/src/app/(app)/planning/page.tsx:1427 |
| C0395 | Creating... / Create production with batches | navigate after action | `/production-orders/${po.id}` | frontend/src/app/(app)/planning/page.tsx:1438 |
| C0396 | Add Brand | local state / inspect handler | {() => openNewBrand("material")} | frontend/src/app/(app)/planning/page.tsx:1506 |
| C0397 | Cancel | local state / inspect handler | {() => { setMaterialEstimate(null); setMaterialEstimateErr(""); }} | frontend/src/app/(app)/planning/page.tsx:1532 |
| C0398 | Creating... / Create Production Order | navigate after action | `/production-orders/${po.id}` | frontend/src/app/(app)/planning/page.tsx:1543 |
| C0399 | Form submission | save/change data | {createBranded} | frontend/src/app/(app)/planning/page.tsx:1575 |
| C0400 | Add Brand | local state / inspect handler | {() => openNewBrand("branded")} | frontend/src/app/(app)/planning/page.tsx:1599 |
| C0401 | Add fabric | local state / inspect handler | {addBrandedMaterial} | frontend/src/app/(app)/planning/page.tsx:1653 |
| C0402 | Remove | local state / inspect handler | {() => removeBrandedMaterial(index)} | frontend/src/app/(app)/planning/page.tsx:1719 |
| C0403 | Cancel | local state / inspect handler | {restoreBrandedModelSizes} | frontend/src/app/(app)/planning/page.tsx:1746 |
| C0404 | Add line | local state / inspect handler | {addBrandedLine} | frontend/src/app/(app)/planning/page.tsx:1750 |
| C0405 | Edit | local state / inspect handler | {() => setBrandedLinesEditing(true)} | frontend/src/app/(app)/planning/page.tsx:1753 |
| C0406 | Distribute equally | local state / inspect handler | {distributeBrandedBySizeRange} | frontend/src/app/(app)/planning/page.tsx:1786 |
| C0407 | Remove | local state / inspect handler | {() => removeBrandedLine(i)} | frontend/src/app/(app)/planning/page.tsx:1834 |
| C0408 | file.file_name \|\| file.file_url | open new tab | file.file_url | frontend/src/app/(app)/planning/page.tsx:1885 |
| C0409 | Remove | local state / inspect handler | {() => setBrandedPrintingAttachments((prev) => prev.filter((_, j) => j !== idx))} | frontend/src/app/(app)/planning/page.tsx:1888 |
| C0410 | View | open page/link | `/production-orders/${brandedSuccess.id}` | frontend/src/app/(app)/planning/page.tsx:1946 |
| C0411 | Creating... / Add production | local state / inspect handler | Local form behavior | frontend/src/app/(app)/planning/page.tsx:1950 |
| C0412 | Form submission | submit form | {createNewBrand} | frontend/src/app/(app)/planning/page.tsx:1966 |
| C0413 | Cancel | local state / inspect handler | {closeNewBrand} | frontend/src/app/(app)/planning/page.tsx:1988 |
| C0414 | Creating... / Create | submit form | Local form behavior | frontend/src/app/(app)/planning/page.tsx:1991 |
| C0735 | label | open new tab | imagePreviewHref(url, label) | frontend/src/components/BrandedModelVariantSelect.tsx:65 |
| C0736 | Creating... / New order | local state / inspect handler | {onNewOrder} | frontend/src/components/BrandedOrderHistory.tsx:107 |
| C0737 | Form submission | submit form | {submitSearch} | frontend/src/components/BrandedOrderHistory.tsx:115 |
| C0738 | Search | submit form | Local form behavior | frontend/src/components/BrandedOrderHistory.tsx:126 |
| C0739 | Clear | filter/select/expand | {clearSearch} | frontend/src/components/BrandedOrderHistory.tsx:131 |
| C0740 | formatOrderReference(production.order_no \|\| production.production_no) | open page/link | `/production-orders/${production.id}` | frontend/src/components/BrandedOrderHistory.tsx:179 |
| C0741 | Add production to this order | local state / inspect handler | {() => onAddProduction(order.id)} | frontend/src/components/BrandedOrderHistory.tsx:229 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P063 /process-qr

Source: [page](../../frontend/src/app/(app)/process-qr/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0415 | t(collapsed ? "nav.expandMenu" : "nav.collapseMenu") | local state / inspect handler | {() => setCollapsedSections((current) => ({ ...current, [section]: !current[section] }))} | frontend/src/app/(app)/process-qr/page.tsx:1551 |
| C0416 | Refresh data | local state / inspect handler | {() => { mutate(); mutateEmployees(); mutateManualModels(); mutateSelectedModel(); mutateFamilySizes(); }} | frontend/src/app/(app)/process-qr/page.tsx:1571 |
| C0417 | Print employees | print | {printEmployeeBadges} | frontend/src/app/(app)/process-qr/page.tsx:1575 |
| C0418 | <RefreshCw className="animate-spin" /> / <Printer /> t(issuingLabels ? "page.processQr.issuingLabels" : "page.processQr.issueLabels") | local state / inspect handler | {issueLabels} | frontend/src/app/(app)/process-qr/page.tsx:1579 |
| C0419 | ERP order | local state / inspect handler | {() => setSourceMode("erp")} | frontend/src/app/(app)/process-qr/page.tsx:1631 |
| C0420 | Manual order | local state / inspect handler | {() => setSourceMode("manual")} | frontend/src/app/(app)/process-qr/page.tsx:1638 |
| C0421 | One batch | local state / inspect handler | {() => setBatchMode("selected")} | frontend/src/app/(app)/process-qr/page.tsx:1679 |
| C0422 | All batches | local state / inspect handler | {() => setBatchMode("all")} | frontend/src/app/(app)/process-qr/page.tsx:1686 |
| C0423 | Open model | open page/link | `/models/${selectedModelId}` | frontend/src/app/(app)/process-qr/page.tsx:1822 |
| C0424 | Open order | open page/link | `/production-orders/${selectedProcess.production_order_id}` | frontend/src/app/(app)/process-qr/page.tsx:1844 |
| C0425 | Same for all sizes | local state / inspect handler | {() => setSizeQuantityMode("same")} | frontend/src/app/(app)/process-qr/page.tsx:1881 |
| C0426 | Custom by size | local state / inspect handler | {() => setSizeQuantityMode("custom")} | frontend/src/app/(app)/process-qr/page.tsx:1888 |
| C0427 | Load saved operations from selected model | local state / inspect handler | {loadOperationsFromSelectedModel} | frontend/src/app/(app)/process-qr/page.tsx:1982 |
| C0428 | Save these operations to selected model | save/change data | {saveOperationsToModel} | frontend/src/app/(app)/process-qr/page.tsx:1992 |
| C0429 | Move operation up | local state / inspect handler | {() => moveOperation(operation.id, -1)} | frontend/src/app/(app)/process-qr/page.tsx:2138 |
| C0430 | Move operation down | local state / inspect handler | {() => moveOperation(operation.id, 1)} | frontend/src/app/(app)/process-qr/page.tsx:2148 |
| C0431 | Remove operation | local state / inspect handler | {() => removeOperation(operation.id)} | frontend/src/app/(app)/process-qr/page.tsx:2158 |
| C0432 | Select visible | filter/select/expand | {selectVisibleEmployees} | frontend/src/app/(app)/process-qr/page.tsx:2241 |
| C0433 | Clear visible | filter/select/expand | {clearVisibleEmployees} | frontend/src/app/(app)/process-qr/page.tsx:2244 |
| C0434 | Print employees | print | {printEmployeeBadges} | frontend/src/app/(app)/process-qr/page.tsx:2247 |
| C0435 | Active | local state / inspect handler | {() => setEmployeeStatus("active")} | frontend/src/app/(app)/process-qr/page.tsx:2272 |
| C0436 | All | local state / inspect handler | {() => setEmployeeStatus("all")} | frontend/src/app/(app)/process-qr/page.tsx:2279 |
| C0437 | <RefreshCw className="animate-spin" /> / <QrCode /> t(issuingLabels ? "page.processQr.issuingLabels" : "page.processQr.issueLabels") | local state / inspect handler | {issueLabels} | frontend/src/app/(app)/process-qr/page.tsx:2415 |
| C0438 | <RefreshCw className="animate-spin" /> / <Printer /> t("page.processQr.printEdited", { count: editedIssuedLabels.length.toLocaleString() }) | print | {() => printIssuedLabels(editedIssuedLabels)} | frontend/src/app/(app)/process-qr/page.tsx:2453 |
| C0439 | <RefreshCw className="animate-spin" /> / <Printer /> Print all sizes | print | {() => printIssuedLabels(orderedIssuedLabels)} | frontend/src/app/(app)/process-qr/page.tsx:2462 |
| C0440 | sizeLabels.some((label) => ( label.status !== "available" \|\| Boolean(label.payroll_record_id) \|\| Boolean(label.last_scanned_at) \|\| Number(label.return_count \|\| 0) > 0 )) ? This size contains scanned, returned, or payroll [dynamic label] | local state / inspect handler | {() => deleteIssuedSize(size, sizeLabels)} | frontend/src/app/(app)/process-qr/page.tsx:2490 |
| C0441 | <RefreshCw className="animate-spin" /> / <Printer /> t("page.processQr.printThisSize", { size }) | print | {() => printIssuedLabels(sizeLabels)} | frontend/src/app/(app)/process-qr/page.tsx:2510 |
| C0442 | Form submission | submit form | {(event) => { event.preventDefault(); void saveLabelCorrection(); }} | frontend/src/app/(app)/process-qr/page.tsx:2545 |
| C0443 | Edit only | local state / inspect handler | {() => setLabelCorrectionMode("edit")} | frontend/src/app/(app)/process-qr/page.tsx:2560 |
| C0444 | Split QR | local state / inspect handler | {() => setLabelCorrectionMode("split")} | frontend/src/app/(app)/process-qr/page.tsx:2567 |
| C0445 | Remove part | local state / inspect handler | {() => removeSplitPart(index)} | frontend/src/app/(app)/process-qr/page.tsx:2628 |
| C0446 | Add part | local state / inspect handler | {addSplitPart} | frontend/src/app/(app)/process-qr/page.tsx:2641 |
| C0447 | Cancel | local state / inspect handler | {() => setLabelCorrection(null)} | frontend/src/app/(app)/process-qr/page.tsx:2658 |
| C0448 | <RefreshCw className="animate-spin" /> / <Save /> t(labelCorrection.mode === "split" ? "page.processQr.saveAndSplit" : "page.processQr.saveLabelEdit") | submit form | Local form behavior | frontend/src/app/(app)/process-qr/page.tsx:2661 |
| C0449 | Edit QR label | local state / inspect handler | {onEdit} | frontend/src/app/(app)/process-qr/page.tsx:3134 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0795 | Loading... / copy.save | local state / inspect handler | {() => void save()} | frontend/src/components/ManualModelSizes.tsx:102 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0838 | copy.add | local state / inspect handler | {() => { setCreating(!creating); setName(query); setMessage(null); }} | frontend/src/components/PaidProcessPicker.tsx:64 |
| C0839 | Saving... / copy.create | local state / inspect handler | {create} | frontend/src/components/PaidProcessPicker.tsx:71 |
| C0840 | copy.cancel | local state / inspect handler | {() => setCreating(false)} | frontend/src/components/PaidProcessPicker.tsx:72 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P064 /processes

Source: [page](../../frontend/src/app/(app)/processes/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0450 | Refresh | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/processes/page.tsx:230 |
| C0451 | Print / Save as PDF | download/export | {openExport} | frontend/src/app/(app)/processes/page.tsx:234 |
| C0452 | View | open page/link | `/production-orders/${p.production_order_id}` | frontend/src/app/(app)/processes/page.tsx:399 |
| C0453 | <ChevronUp /> / <ChevronDown /> Stage detail | filter/select/expand | {() => setExpanded(expanded === p.production_order_id ? null : p.production_order_id)} | frontend/src/app/(app)/processes/page.tsx:403 |
| C0454 | formatOrderReference(productionNo) | open page/link | `/production-orders/${process.production_order_id}` | frontend/src/app/(app)/processes/page.tsx:451 |
| C0455 | formatOrderReference(salesOrderNo) | open page/link | `/sales-orders/${process.sales_order_id}` | frontend/src/app/(app)/processes/page.tsx:459 |
| C0456 | View | open page/link | `/production-orders/${process.production_order_id}` | frontend/src/app/(app)/processes/page.tsx:479 |
| C0457 | <ChevronUp /> / <ChevronDown /> Stage detail | local state / inspect handler | {onToggle} | frontend/src/app/(app)/processes/page.tsx:483 |
| C0458 | Audit | open page/link | `/admin/audit-logs?entity=ProductionOrder&id=${process.production_order_id}` | frontend/src/app/(app)/processes/page.tsx:487 |
| C0459 | Icon control at line 501 | open new tab | imagePreviewHref(imageUrl, alt) | frontend/src/app/(app)/processes/page.tsx:501 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P065 /production-orders/[id]

Source: [page](../../frontend/src/app/(app)/production-orders/[id]/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0465 | label | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/app/(app)/production-orders/[id]/page.tsx:188 |
| C0466 | Retry | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/production-orders/[id]/page.tsx:431 |
| C0467 | Distribute the production deadline across stage deadlines using SAM x qty where available | save/change data | {cascade} | frontend/src/app/(app)/production-orders/[id]/page.tsx:445 |
| C0468 | Admin repair: recalculate counters from records and packages | save/change data | {repairTotals} | frontend/src/app/(app)/production-orders/[id]/page.tsx:447 |
| C0469 | Edit | local state / inspect handler | {openSummaryEdit} | frontend/src/app/(app)/production-orders/[id]/page.tsx:479 |
| C0470 | Form submission | save/change data | {saveSummary} | frontend/src/app/(app)/production-orders/[id]/page.tsx:484 |
| C0471 | Cancel | local state / inspect handler | {() => { setSummaryEditing(false); setSummaryMsg(""); }} | frontend/src/app/(app)/production-orders/[id]/page.tsx:562 |
| C0472 | Saving... / Save changes | submit form | Local form behavior | frontend/src/app/(app)/production-orders/[id]/page.tsx:565 |
| C0473 | Saving... / Auto Reserve | save/change data | {autoReserveMaterials} | frontend/src/app/(app)/production-orders/[id]/page.tsx:630 |
| C0474 | Release reservation | save/change data | {() => releaseReservation(reservation.id)} | frontend/src/app/(app)/production-orders/[id]/page.tsx:723 |
| C0475 | Assign | local state / inspect handler | {() => openEdit(w)} | frontend/src/app/(app)/production-orders/[id]/page.tsx:794 |
| C0476 | Block | save/change data | {() => blockWO(w.id)} | frontend/src/app/(app)/production-orders/[id]/page.tsx:797 |
| C0477 | Unblock | save/change data | {() => unblockWO(w.id)} | frontend/src/app/(app)/production-orders/[id]/page.tsx:798 |
| C0478 | Hide split / Split | open/close dialog | {() => setOpenAssignments(openAssignments === w.id ? null : w.id)} | frontend/src/app/(app)/production-orders/[id]/page.tsx:800 |
| C0479 | Cutting | open page/link | `/work-orders/${w.id}/cutting` | frontend/src/app/(app)/production-orders/[id]/page.tsx:804 |
| C0480 | Printing | open page/link | `/work-orders/${w.id}/printing` | frontend/src/app/(app)/production-orders/[id]/page.tsx:805 |
| C0481 | Sewing | open page/link | `/work-orders/${w.id}/sewing` | frontend/src/app/(app)/production-orders/[id]/page.tsx:806 |
| C0482 | Packaging | open page/link | `/work-orders/${w.id}/packaging` | frontend/src/app/(app)/production-orders/[id]/page.tsx:807 |
| C0483 | Form submission | download/export | {saveAssign} | frontend/src/app/(app)/production-orders/[id]/page.tsx:825 |
| C0484 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/production-orders/[id]/page.tsx:859 |
| C0485 | Save changes | submit form | Local form behavior | frontend/src/app/(app)/production-orders/[id]/page.tsx:860 |
| C0486 | Delete | local state / inspect handler | {() => del(a.id)} | frontend/src/app/(app)/production-orders/[id]/page.tsx:932 |
| C0487 | Form submission | save/change data | {add} | frontend/src/app/(app)/production-orders/[id]/page.tsx:938 |
| C0488 | Add assignment | local state / inspect handler | Local form behavior | frontend/src/app/(app)/production-orders/[id]/page.tsx:954 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0866 | Edit sizes | local state / inspect handler | {startEdit} | frontend/src/components/ProductionOrderSizePlan.tsx:69 |
| C0867 | Form submission | submit form | {save} | frontend/src/components/ProductionOrderSizePlan.tsx:74 |
| C0868 | Cancel | local state / inspect handler | {() => { setDraft(null); setError(""); }} | frontend/src/components/ProductionOrderSizePlan.tsx:106 |
| C0869 | Saving... / Save changes | submit form | Local form behavior | frontend/src/components/ProductionOrderSizePlan.tsx:109 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P066 /production-orders

Source: [page](../../frontend/src/app/(app)/production-orders/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0460 | View | open page/link | `/production-orders/${p.id}` | frontend/src/app/(app)/production-orders/page.tsx:84 |
| C0461 | Edit | local state / inspect handler | {() => openEdit(p)} | frontend/src/app/(app)/production-orders/page.tsx:86 |
| C0462 | Form submission | save/change data | {saveEdit} | frontend/src/app/(app)/production-orders/page.tsx:96 |
| C0463 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/app/(app)/production-orders/page.tsx:113 |
| C0464 | Save changes | submit form | Local form behavior | frontend/src/app/(app)/production-orders/page.tsx:114 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P067 /profile

Source: [page](../../frontend/src/app/(app)/profile/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0489 | Form submission | save/change data | {saveProfile} | frontend/src/app/(app)/profile/page.tsx:62 |
| C0490 | Save | local state / inspect handler | Local form behavior | frontend/src/app/(app)/profile/page.tsx:73 |
| C0491 | Form submission | save/change data | {changePassword} | frontend/src/app/(app)/profile/page.tsx:76 |
| C0492 | Save Password | local state / inspect handler | Local form behavior | frontend/src/app/(app)/profile/page.tsx:83 |

## P068 /purchasing

Source: [page](../../frontend/src/app/(app)/purchasing/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0493 | Approve | save/change data | {() => approve(request)} | frontend/src/app/(app)/purchasing/page.tsx:216 |
| C0494 | Reject | save/change data | {() => reject(request)} | frontend/src/app/(app)/purchasing/page.tsx:216 |
| C0495 | Order | save/change data | {() => order(request)} | frontend/src/app/(app)/purchasing/page.tsx:222 |
| C0496 | New request | local state / inspect handler | {() => { setMessage(""); setShowRequestForm(true); }} | frontend/src/app/(app)/purchasing/page.tsx:233 |
| C0497 | Active Orders ( openOrderCount ) | open page/link | /purchasing/receiving | frontend/src/app/(app)/purchasing/page.tsx:234 |
| C0498 | Form submission | submit form | {submitManualRequest} | frontend/src/app/(app)/purchasing/page.tsx:240 |
| C0499 | Cancel | local state / inspect handler | {() => setShowRequestForm(false)} | frontend/src/app/(app)/purchasing/page.tsx:243 |
| C0500 | Cancel | local state / inspect handler | {() => setShowRequestForm(false)} | frontend/src/app/(app)/purchasing/page.tsx:265 |
| C0501 | Create Purchase Request | local state / inspect handler | Local form behavior | frontend/src/app/(app)/purchasing/page.tsx:266 |

## P069 /purchasing/price-calculation

Source: [page](../../frontend/src/app/(app)/purchasing/price-calculation/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0502 | Edit | local state / inspect handler | {() => beginEdit(request)} | frontend/src/app/(app)/purchasing/price-calculation/page.tsx:146 |
| C0503 | Saving… / Save | save/change data | {() => save(request)} | frontend/src/app/(app)/purchasing/price-calculation/page.tsx:147 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |

## P070 /purchasing/receiving

Source: [page](../../frontend/src/app/(app)/purchasing/receiving/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0504 | Purchase Requests | open page/link | /purchasing | frontend/src/app/(app)/purchasing/receiving/page.tsx:263 |
| C0505 | t(isCollapsed ? "page.purchasing.expandSupplier" : "page.purchasing.collapseSupplier", { supplier: group.supplierName }) | local state / inspect handler | {() => toggleSupplierGroup(group.key)} | frontend/src/app/(app)/purchasing/receiving/page.tsx:297 |
| C0506 | Open material photo in a new window | open new tab | line.photo_url | frontend/src/app/(app)/purchasing/receiving/page.tsx:319 |
| C0507 | Receive | local state / inspect handler | {() => openReceive(order, line)} | frontend/src/app/(app)/purchasing/receiving/page.tsx:338 |
| C0508 | Form submission | save/change data | {submitReceive} | frontend/src/app/(app)/purchasing/receiving/page.tsx:371 |
| C0509 | Close | local state / inspect handler | {() => setReceiveState(null)} | frontend/src/app/(app)/purchasing/receiving/page.tsx:377 |
| C0510 | Cancel | local state / inspect handler | {() => setReceiveState(null)} | frontend/src/app/(app)/purchasing/receiving/page.tsx:450 |
| C0511 | Saving... / Receive | local state / inspect handler | Local form behavior | frontend/src/app/(app)/purchasing/receiving/page.tsx:451 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P071 /sales-orders/[id]

Source: [page](../../frontend/src/app/(app)/sales-orders/[id]/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0541 | Retry | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/sales-orders/[id]/page.tsx:66 |
| C0542 | Confirm | save/change data | {confirmOrder} | frontend/src/app/(app)/sales-orders/[id]/page.tsx:79 |
| C0543 | Generate Invoice | save/change data | {generateInvoice} | frontend/src/app/(app)/sales-orders/[id]/page.tsx:81 |
| C0544 | Reserve stock | save/change data | {reserveStock} | frontend/src/app/(app)/sales-orders/[id]/page.tsx:84 |
| C0545 | file.file_name \|\| file.file_url | open new tab | file.file_url | frontend/src/app/(app)/sales-orders/[id]/page.tsx:180 |

## P072 /sales-orders/first-grade

Source: [page](../../frontend/src/app/(app)/sales-orders/first-grade/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0514 | copy.stock | open page/link | /warehouse-stock?stock_kind=first_grade | frontend/src/app/(app)/sales-orders/first-grade/page.tsx:19 |
| C0515 | Form submission | navigate after action | `/sales-orders/${order.id}` | frontend/src/app/(app)/sales-orders/first-grade/page.tsx:22 |
| C0516 | copy.saveSale | local state / inspect handler | Local form behavior | frontend/src/app/(app)/sales-orders/first-grade/page.tsx:33 |

## P073 /sales-orders/new

Source: [page](../../frontend/src/app/(app)/sales-orders/new/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0517 | Back to orders | open page/link | /sales-orders | frontend/src/app/(app)/sales-orders/new/page.tsx:437 |
| C0518 | Form submission | navigate after action | `/sales-orders/${so.id}` | frontend/src/app/(app)/sales-orders/new/page.tsx:440 |
| C0519 | Add customer | open/close dialog | {() => { setCustomerError(""); setCustomerModalOpen(true); }} | frontend/src/app/(app)/sales-orders/new/page.tsx:462 |
| C0520 | Add line | local state / inspect handler | {addLine} | frontend/src/app/(app)/sales-orders/new/page.tsx:513 |
| C0521 | Distribute equally | local state / inspect handler | {distributeBySizeRange} | frontend/src/app/(app)/sales-orders/new/page.tsx:537 |
| C0522 | Remove | local state / inspect handler | {() => removeLine(i)} | frontend/src/app/(app)/sales-orders/new/page.tsx:630 |
| C0523 | file.file_name \|\| file.file_url | open new tab | file.file_url | frontend/src/app/(app)/sales-orders/new/page.tsx:683 |
| C0524 | Remove | local state / inspect handler | {() => setPrintingAttachments((prev) => prev.filter((_, j) => j !== idx))} | frontend/src/app/(app)/sales-orders/new/page.tsx:686 |
| C0525 | Creating... / Create order | local state / inspect handler | Local form behavior | frontend/src/app/(app)/sales-orders/new/page.tsx:726 |
| C0526 | Form submission | open/close dialog | {createCustomer} | frontend/src/app/(app)/sales-orders/new/page.tsx:740 |
| C0527 | Cancel | open/close dialog | {() => setCustomerModalOpen(false)} | frontend/src/app/(app)/sales-orders/new/page.tsx:784 |
| C0528 | Saving... / Add customer | submit form | Local form behavior | frontend/src/app/(app)/sales-orders/new/page.tsx:787 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P074 /sales-orders

Source: [page](../../frontend/src/app/(app)/sales-orders/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0529 | Filter | filter/select/expand | {() => setShowFilters((v) => !v)} | frontend/src/app/(app)/sales-orders/page.tsx:169 |
| C0530 | Export | download/export | {exportCsv} | frontend/src/app/(app)/sales-orders/page.tsx:170 |
| C0531 | + New Order.replace("+ ", "") | open page/link | /sales-orders/new | frontend/src/app/(app)/sales-orders/page.tsx:171 |
| C0532 | Clear search | local state / inspect handler | {() => setQuery("")} | frontend/src/app/(app)/sales-orders/page.tsx:186 |
| C0533 | tab.label tab.count | filter/select/expand | {() => setActiveTab(tab.key)} | frontend/src/app/(app)/sales-orders/page.tsx:221 |
| C0534 | o.order_no | open page/link | `/sales-orders/${o.id}` | frontend/src/app/(app)/sales-orders/page.tsx:237 |
| C0535 | formatOrderReference(o.order_no) customerMap.get(o.customer_id) ?? Unknown customer qty.toLocaleString() pct % statusLabel(o.status, t) new Date(o.deadline).toLocaleDateString("en-US", { month: "short", day: "2-digit" }) / "-" | filter/select/expand | {() => setSelectedId(o.id)} | frontend/src/app/(app)/sales-orders/page.tsx:308 |
| C0536 | {(e) => e.stopPropagation()} | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/app/(app)/sales-orders/page.tsx:309 |
| C0537 | o.order_no | open page/link | `/sales-orders/${o.id}` | frontend/src/app/(app)/sales-orders/page.tsx:310 |
| C0538 | selected.order_no | open page/link | `/sales-orders/${selected.id}` | frontend/src/app/(app)/sales-orders/page.tsx:342 |
| C0539 | Icon control at line 345 | local state / inspect handler | Local form behavior | frontend/src/app/(app)/sales-orders/page.tsx:345 |
| C0540 | Delete | filter/select/expand | {() => removeSalesOrder(selected.id, selected.order_no)} | frontend/src/app/(app)/sales-orders/page.tsx:346 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P075 /sales/price-requests

Source: [page](../../frontend/src/app/(app)/sales/price-requests/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0512 | Add row | local state / inspect handler | {addRow} | frontend/src/app/(app)/sales/price-requests/page.tsx:103 |
| C0513 | Saving… / Save | save/change data | {() => save(draft)} | frontend/src/app/(app)/sales/price-requests/page.tsx:110 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P076 /search

Source: [page](../../frontend/src/app/(app)/search/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0546 | Form submission | navigate after action | next ? `/search?q=${encodeURIComponent(next)}` : "/search" | frontend/src/app/(app)/search/page.tsx:72 |
| C0547 | Search | submit form | Local form behavior | frontend/src/app/(app)/search/page.tsx:85 |
| C0548 | row.label | open page/link | row.url | frontend/src/app/(app)/search/page.tsx:103 |
| C0549 | Load more | local state / inspect handler | {() => setVisibleCounts((current) => ({ ...current, [type]: Math.min(current[type] + INITIAL_RESULTS_PER_TYPE, grouped[type].length), }))} | frontend/src/app/(app)/search/page.tsx:110 |

## P077 /settings

Source: [page](../../frontend/src/app/(app)/settings/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0550 | Save | save/change data | {() => save("company_info")} | frontend/src/app/(app)/settings/page.tsx:108 |
| C0551 | Save | save/change data | {() => save("financial")} | frontend/src/app/(app)/settings/page.tsx:122 |
| C0552 | Save | save/change data | {() => save("preferences")} | frontend/src/app/(app)/settings/page.tsx:132 |

## P078 /sewing/daily-report

Source: [page](../../frontend/src/app/(app)/sewing/daily-report/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0553 | Refresh | local state / inspect handler | {refresh} | frontend/src/app/(app)/sewing/daily-report/page.tsx:486 |
| C0554 | Remove section | local state / inspect handler | {() => setSectionEntries((current) => current.filter((item) => item.id !== entry.id))} | frontend/src/app/(app)/sewing/daily-report/page.tsx:614 |
| C0555 | Add section | local state / inspect handler | {() => { const activeWork = lineContext?.active_work_orders?.[0]; setSectionEntries((current) => [ ...current, { ...createSectionEntry(), workKey: activeWork ? sewingWorkKey(activeWork) : "", kroyNo: activeWork?.kroy_no \|\| "", manualModel: activeWork ? { enabled: false, modelNo: "", variantNo: "" } : { enabled: true, modelNo: "", variantNo: "" }, }, ]); }} | frontend/src/app/(app)/sewing/daily-report/page.tsx:785 |
| C0556 | Saving... / Save daily report | save/change data | {saveReport} | frontend/src/app/(app)/sewing/daily-report/page.tsx:866 |
| C0557 | Refresh | local state / inspect handler | {refresh} | frontend/src/app/(app)/sewing/daily-report/page.tsx:885 |
| C0558 | Refresh | local state / inspect handler | {refresh} | frontend/src/app/(app)/sewing/daily-report/page.tsx:903 |
| C0559 | Loading... / Excel report | download/export | {() => void downloadReport("xlsx")} | frontend/src/app/(app)/sewing/daily-report/page.tsx:940 |
| C0560 | Loading... / PDF report | download/export | {() => void downloadReport("pdf")} | frontend/src/app/(app)/sewing/daily-report/page.tsx:951 |
| C0561 | Edit | local state / inspect handler | {() => setEditingRow(row)} | frontend/src/app/(app)/sewing/daily-report/page.tsx:1079 |
| C0562 | Delete | local state / inspect handler | {() => deleteReport(row)} | frontend/src/app/(app)/sewing/daily-report/page.tsx:1087 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0793 | Enter model and variant manually | local state / inspect handler | {() => onChange({ enabled: true, modelNo: value.modelNo, variantNo: value.variantNo, })} | frontend/src/components/ManualModelIdentityFields.tsx:30 |
| C0794 | Cancel | local state / inspect handler | {() => onChange({ enabled: false, modelNo: "", variantNo: "" })} | frontend/src/components/ManualModelIdentityFields.tsx:75 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0873 | Cancel | local state / inspect handler | {onClose} | frontend/src/components/SewingDailyReportEditModal.tsx:339 |
| C0874 | Saving... / Save | save/change data | {() => void saveCorrection()} | frontend/src/components/SewingDailyReportEditModal.tsx:342 |
| C0880 | selected.model_no \|\| selected.model_code \|\| "-" Variant No : selected.variant_no \|\| "-" batchLabel(selected) selected.remaining_qty Remaining.toLowerCase() | open/close dialog | {() => setOpen((current) => !current)} | frontend/src/components/SewingWorkPicker.tsx:104 |
| C0881 | work.model_no \|\| work.model_code \|\| "-" Variant No : work.variant_no \|\| "-" work.model_name && <div className="break-words text-xs text-[#8a8472]">{work.model_name}</div> [batchLabel(work), `${work.remaining_qty} ${Remai [dynamic label] | open/close dialog | {() => { onChange(key); setOpen(false); }} | frontend/src/components/SewingWorkPicker.tsx:130 |

## P079 /sewing/floor

Source: [page](../../frontend/src/app/(app)/sewing/floor/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|

No direct control definitions found; inspect route redirects and imported view composition.

## P080 /sewing/flows

Source: [page](../../frontend/src/app/(app)/sewing/flows/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0563 | orderReference(workOrder, `#${workOrder.production_order_id}`) | open page/link | `/production-orders/${workOrder.production_order_id}` | frontend/src/app/(app)/sewing/flows/page.tsx:130 |
| C0564 | Loading... / Move | local state / inspect handler | {() => onMove(workOrder)} | frontend/src/app/(app)/sewing/flows/page.tsx:152 |
| C0565 | Loading... / Assign | local state / inspect handler | {() => onAssign?.(workOrder)} | frontend/src/app/(app)/sewing/flows/page.tsx:162 |
| C0566 | Return work | local state / inspect handler | {() => onReturn(workOrder)} | frontend/src/app/(app)/sewing/flows/page.tsx:172 |
| C0567 | Open | open page/link | `/work-orders/${workOrder.id}/sewing` | frontend/src/app/(app)/sewing/flows/page.tsx:177 |
| C0568 | orderReference(workOrder, `#${workOrder.production_order_id}`) | open page/link | `/production-orders/${workOrder.production_order_id}` | frontend/src/app/(app)/sewing/flows/page.tsx:187 |
| C0569 | Loading... / Move | local state / inspect handler | {() => onMove(workOrder)} | frontend/src/app/(app)/sewing/flows/page.tsx:211 |
| C0570 | Loading... / Assign | local state / inspect handler | {() => onAssign?.(workOrder)} | frontend/src/app/(app)/sewing/flows/page.tsx:221 |
| C0571 | Return work | local state / inspect handler | {() => onReturn(workOrder)} | frontend/src/app/(app)/sewing/flows/page.tsx:231 |
| C0572 | Open | open page/link | `/work-orders/${workOrder.id}/sewing` | frontend/src/app/(app)/sewing/flows/page.tsx:236 |
| C0573 | Icon control at line 257 | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/app/(app)/sewing/flows/page.tsx:257 |
| C0574 | Cancel / (f.active_work_orders > 0 ? Currently sewing : Ready for work) | filter/select/expand | {() => setExpanded((prev) => ({ ...prev, [f.id]: !prev[f.id] }))} | frontend/src/app/(app)/sewing/flows/page.tsx:334 |
| C0575 | Cancel | local state / inspect handler | {() => setPick({ wo: null, qty: "", maxQty: 0, productionBatchId: null, batchLabel: "" })} | frontend/src/app/(app)/sewing/flows/page.tsx:612 |
| C0576 | Loading... / Assign | save/change data | {takeWork} | frontend/src/app/(app)/sewing/flows/page.tsx:613 |
| C0577 | Cancel | local state / inspect handler | {closeMove} | frontend/src/app/(app)/sewing/flows/page.tsx:651 |
| C0578 | Loading... / Move | save/change data | {moveWork} | frontend/src/app/(app)/sewing/flows/page.tsx:652 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P081 /shipments/history

Source: [page](../../frontend/src/app/(app)/shipments/history/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0579 | Shipments | open page/link | /shipments | frontend/src/app/(app)/shipments/history/page.tsx:35 |
| C0580 | shipmentReviewText[lang].reference | open new tab | `/api/shipments/${shipment.id}/invoice/print?lang=${lang}` | frontend/src/app/(app)/shipments/history/page.tsx:53 |
| C0581 | Shipment Traceability | open page/link | `/traceability?shipment=${encodeURIComponent(shipment.shipment_no \|\| shipment.id)}` | frontend/src/app/(app)/shipments/history/page.tsx:55 |
| C0582 | shipmentReviewText[lang].reference | open new tab | `/api/shipments/${shipment.id}/invoice/print?lang=${lang}` | frontend/src/app/(app)/shipments/history/page.tsx:64 |
| C0583 | Shipment Traceability | open page/link | `/traceability?shipment=${encodeURIComponent(shipment.shipment_no \|\| shipment.id)}` | frontend/src/app/(app)/shipments/history/page.tsx:64 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0886 | Scan | local state / inspect handler | {onScan} | frontend/src/components/ShipmentPreparationWorkspace.tsx:224 |
| C0887 | deleteText.deleteShipment | save/change data | {async () => { if (!(await dialogs.ask({ message: deleteText.deleteConfirm, confirmText: deleteText.deleteShipment, tone: "danger" }))) return; setDeleting(true); setReturnError(""); try { await api.post(`/api/shipments/${shipment.id}/delete`, { reason: deleteText.deleteReason }); setDeleted(shipment.id); await onReviewChanged(); } catch (error) { setReturnError(error instanceof Error ? error.message : String(error)); } finally { setDeleting(false); } }} | frontend/src/components/ShipmentPreparationWorkspace.tsx:231 |
| C0888 | Add ready packages | local state / inspect handler | {onAddReadyPackages} | frontend/src/components/ShipmentPreparationWorkspace.tsx:241 |
| C0889 | manualShipmentText[lang].ship / shipment.sales_order_id ? Ship : Confirm exit | local state / inspect handler | {onShip} | frontend/src/components/ShipmentPreparationWorkspace.tsx:243 |
| C0890 | Mark delivered | local state / inspect handler | {onDeliver} | frontend/src/components/ShipmentPreparationWorkspace.tsx:246 |
| C0891 | Shipment Traceability | open page/link | `/traceability?shipment=${encodeURIComponent(shipment.shipment_no \|\| shipment.id)}` | frontend/src/components/ShipmentPreparationWorkspace.tsx:250 |
| C0892 | reviewText.reference | open new tab | `/api/shipments/${shipment.id}/invoice/print?lang=${lang}` | frontend/src/components/ShipmentPreparationWorkspace.tsx:254 |
| C0893 | Loading... / Create shipment | local state / inspect handler | {() => onCreate(normalizeTransportDetails(transportDraft))} | frontend/src/components/ShipmentPreparationWorkspace.tsx:257 |
| C0894 | `${returnText.remove}: ${pkg.package_no}` | save/change data | {() => void returnPackage(pkg.id)} | frontend/src/components/ShipmentPreparationWorkspace.tsx:431 |
| C0895 | `${returnText.remove}: ${pkg.package_no}` | save/change data | {() => void returnPackage(pkg.id)} | frontend/src/components/ShipmentPreparationWorkspace.tsx:486 |
| C0896 | text.review | local state / inspect handler | {() => begin("amount")} | frontend/src/components/ShipmentReviewPanel.tsx:72 |
| C0897 | text.edit | local state / inspect handler | {() => begin(row.id)} | frontend/src/components/ShipmentReviewPanel.tsx:76 |
| C0898 | Form submission | save/change data | {save} | frontend/src/components/ShipmentReviewPanel.tsx:78 |
| C0899 | text.remove | save/change data | {() => void remove()} | frontend/src/components/ShipmentReviewPanel.tsx:87 |
| C0900 | text.save | local state / inspect handler | Local form behavior | frontend/src/components/ShipmentReviewPanel.tsx:87 |
| C0901 | text.cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/components/ShipmentReviewPanel.tsx:87 |
| C0902 | Form submission | download/export | {save} | frontend/src/components/ShipmentTransportDetails.tsx:67 |
| C0903 | text.saving / text.save | local state / inspect handler | Local form behavior | frontend/src/components/ShipmentTransportDetails.tsx:71 |
| C0904 | text.cancel | local state / inspect handler | {() => setEditing(false)} | frontend/src/components/ShipmentTransportDetails.tsx:72 |
| C0905 | text.edit | local state / inspect handler | {() => { setDraft({ ...saved }); setError(""); setEditing(true); }} | frontend/src/components/ShipmentTransportDetails.tsx:78 |

## P082 /shipments

Source: [page](../../frontend/src/app/(app)/shipments/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0584 | Shipment history | open page/link | /shipments/history | frontend/src/app/(app)/shipments/page.tsx:271 |
| C0585 | manualText.title | local state / inspect handler | {createWarehouseExit} | frontend/src/app/(app)/shipments/page.tsx:303 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0790 | title | open new tab | imagePreviewHref(imageUrl, label) | frontend/src/components/ImageThumbnail.tsx:33 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |
| C0882 | text.add | open/close dialog | {() => { setError(""); setOpen(true); }} | frontend/src/components/ShipmentAddClient.tsx:21 |
| C0883 | Form submission | open/close dialog | {async event => { event.preventDefault(); if (busy \|\| !name.trim()) return; setBusy(true); setError(""); try { const client = await api.post<{ id: number; name: string }>("/api/shipments/customers", { name: name.trim(), phone: phone.trim() \|\| null }); onCreated(client); setName(""); setPhone(""); setOpen(false); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); } }} | frontend/src/components/ShipmentAddClient.tsx:23 |
| C0884 | text.cancel | open/close dialog | {() => setOpen(false)} | frontend/src/components/ShipmentAddClient.tsx:36 |
| C0885 | text.save | local state / inspect handler | Local form behavior | frontend/src/components/ShipmentAddClient.tsx:36 |
| C0886 | Scan | local state / inspect handler | {onScan} | frontend/src/components/ShipmentPreparationWorkspace.tsx:224 |
| C0887 | deleteText.deleteShipment | save/change data | {async () => { if (!(await dialogs.ask({ message: deleteText.deleteConfirm, confirmText: deleteText.deleteShipment, tone: "danger" }))) return; setDeleting(true); setReturnError(""); try { await api.post(`/api/shipments/${shipment.id}/delete`, { reason: deleteText.deleteReason }); setDeleted(shipment.id); await onReviewChanged(); } catch (error) { setReturnError(error instanceof Error ? error.message : String(error)); } finally { setDeleting(false); } }} | frontend/src/components/ShipmentPreparationWorkspace.tsx:231 |
| C0888 | Add ready packages | local state / inspect handler | {onAddReadyPackages} | frontend/src/components/ShipmentPreparationWorkspace.tsx:241 |
| C0889 | manualShipmentText[lang].ship / shipment.sales_order_id ? Ship : Confirm exit | local state / inspect handler | {onShip} | frontend/src/components/ShipmentPreparationWorkspace.tsx:243 |
| C0890 | Mark delivered | local state / inspect handler | {onDeliver} | frontend/src/components/ShipmentPreparationWorkspace.tsx:246 |
| C0891 | Shipment Traceability | open page/link | `/traceability?shipment=${encodeURIComponent(shipment.shipment_no \|\| shipment.id)}` | frontend/src/components/ShipmentPreparationWorkspace.tsx:250 |
| C0892 | reviewText.reference | open new tab | `/api/shipments/${shipment.id}/invoice/print?lang=${lang}` | frontend/src/components/ShipmentPreparationWorkspace.tsx:254 |
| C0893 | Loading... / Create shipment | local state / inspect handler | {() => onCreate(normalizeTransportDetails(transportDraft))} | frontend/src/components/ShipmentPreparationWorkspace.tsx:257 |
| C0894 | `${returnText.remove}: ${pkg.package_no}` | save/change data | {() => void returnPackage(pkg.id)} | frontend/src/components/ShipmentPreparationWorkspace.tsx:431 |
| C0895 | `${returnText.remove}: ${pkg.package_no}` | save/change data | {() => void returnPackage(pkg.id)} | frontend/src/components/ShipmentPreparationWorkspace.tsx:486 |
| C0896 | text.review | local state / inspect handler | {() => begin("amount")} | frontend/src/components/ShipmentReviewPanel.tsx:72 |
| C0897 | text.edit | local state / inspect handler | {() => begin(row.id)} | frontend/src/components/ShipmentReviewPanel.tsx:76 |
| C0898 | Form submission | save/change data | {save} | frontend/src/components/ShipmentReviewPanel.tsx:78 |
| C0899 | text.remove | save/change data | {() => void remove()} | frontend/src/components/ShipmentReviewPanel.tsx:87 |
| C0900 | text.save | local state / inspect handler | Local form behavior | frontend/src/components/ShipmentReviewPanel.tsx:87 |
| C0901 | text.cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/components/ShipmentReviewPanel.tsx:87 |
| C0902 | Form submission | download/export | {save} | frontend/src/components/ShipmentTransportDetails.tsx:67 |
| C0903 | text.saving / text.save | local state / inspect handler | Local form behavior | frontend/src/components/ShipmentTransportDetails.tsx:71 |
| C0904 | text.cancel | local state / inspect handler | {() => setEditing(false)} | frontend/src/components/ShipmentTransportDetails.tsx:72 |
| C0905 | text.edit | local state / inspect handler | {() => { setDraft({ ...saved }); setError(""); setEditing(true); }} | frontend/src/components/ShipmentTransportDetails.tsx:78 |

## P083 /traceability

Source: [page](../../frontend/src/app/(app)/traceability/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0586 | Print passport | download/export | {openExport} | frontend/src/app/(app)/traceability/page.tsx:236 |
| C0587 | Form submission | submit form | {lookup} | frontend/src/app/(app)/traceability/page.tsx:242 |
| C0588 | Loading... / Lookup | local state / inspect handler | Local form behavior | frontend/src/app/(app)/traceability/page.tsx:267 |
| C0589 | Package | open page/link | `/packages/${packageId}` | frontend/src/app/(app)/traceability/page.tsx:408 |
| C0590 | Production No | open page/link | `/production-orders/${productionOrderId}` | frontend/src/app/(app)/traceability/page.tsx:409 |
| C0591 | Shipment | open page/link | `/shipments?shipment_id=${shipmentId}` | frontend/src/app/(app)/traceability/page.tsx:410 |

## P084 /usluga/models/[id]

Source: [page](../../frontend/src/app/(app)/usluga/models/[id]/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0242 | Retry | local state / inspect handler | {() => mutate()} | frontend/src/app/(app)/models/[id]/page.tsx:521 |
| C0243 | label badgeValue | filter/select/expand | {() => setTab(index)} | frontend/src/app/(app)/models/[id]/page.tsx:1001 |
| C0244 | Form submission | save/change data | {(e) => addImage(e, imageType)} | frontend/src/app/(app)/models/[id]/page.tsx:1027 |
| C0245 | Uploading... / uploadOptionTitle(imageType) | local state / inspect handler | Local form behavior | frontend/src/app/(app)/models/[id]/page.tsx:1045 |
| C0246 | Saving... / Generate sizes | save/change data | {generateModelSizeRange} | frontend/src/app/(app)/models/[id]/page.tsx:1074 |
| C0247 | Back to Usluga models / Models | open page/link | modelPageBase | frontend/src/app/(app)/models/[id]/page.tsx:1098 |
| C0248 | Cloning... / Clone | navigate after action | `${modelPageBase}/${cloned.id}?mode=edit` | frontend/src/app/(app)/models/[id]/page.tsx:1101 |
| C0249 | View | open page/link | `${modelPageBase}/${id}` | frontend/src/app/(app)/models/[id]/page.tsx:1105 |
| C0250 | Edit | open page/link | `${modelPageBase}/${id}?mode=edit` | frontend/src/app/(app)/models/[id]/page.tsx:1106 |
| C0251 | Icon control at line 1193 | open new tab | imagePreviewHref(primaryImage.file_url, primaryImage.file_name \|\| modelForm.name \|\| t("field.picture")) | frontend/src/app/(app)/models/[id]/page.tsx:1193 |
| C0252 | Remove | local state / inspect handler | {() => removeModelCompositionRow(index)} | frontend/src/app/(app)/models/[id]/page.tsx:1275 |
| C0253 | Add row | local state / inspect handler | {addModelCompositionRow} | frontend/src/app/(app)/models/[id]/page.tsx:1290 |
| C0254 | + Add to fabrics | local state / inspect handler | {resetBomForm} | frontend/src/app/(app)/models/[id]/page.tsx:1302 |
| C0255 | Edit | local state / inspect handler | {() => editBom(r, "material")} | frontend/src/app/(app)/models/[id]/page.tsx:1320 |
| C0256 | Delete | local state / inspect handler | {() => deleteBom(r)} | frontend/src/app/(app)/models/[id]/page.tsx:1323 |
| C0257 | Form submission | save/change data | {(e) => addBom(e, "material")} | frontend/src/app/(app)/models/[id]/page.tsx:1334 |
| C0258 | Save / Add | submit form | Local form behavior | frontend/src/app/(app)/models/[id]/page.tsx:1369 |
| C0259 | Cancel | local state / inspect handler | {resetBomForm} | frontend/src/app/(app)/models/[id]/page.tsx:1370 |
| C0260 | + Add to accessories | local state / inspect handler | {resetBomForm} | frontend/src/app/(app)/models/[id]/page.tsx:1376 |
| C0261 | Edit | local state / inspect handler | {() => editBom(r, "accessory")} | frontend/src/app/(app)/models/[id]/page.tsx:1393 |
| C0262 | Delete | local state / inspect handler | {() => deleteBom(r)} | frontend/src/app/(app)/models/[id]/page.tsx:1396 |
| C0263 | Form submission | save/change data | {(e) => addBom(e, "accessory")} | frontend/src/app/(app)/models/[id]/page.tsx:1409 |
| C0264 | Save / Add | submit form | Local form behavior | frontend/src/app/(app)/models/[id]/page.tsx:1423 |
| C0265 | Cancel | local state / inspect handler | {resetBomForm} | frontend/src/app/(app)/models/[id]/page.tsx:1424 |
| C0266 | Form submission | navigate after action | `${modelPageBase}/${createdVariantId}?mode=edit` | frontend/src/app/(app)/models/[id]/page.tsx:1461 |
| C0267 | Icon control at line 1498 | open new tab | imagePreviewHref(selectedVariantPictureUrl, variantForm.variant_no \|\| t("field.picture")) | frontend/src/app/(app)/models/[id]/page.tsx:1498 |
| C0268 | Saving... / editingVariantId ? Save variant : Create variant | submit form | Local form behavior | frontend/src/app/(app)/models/[id]/page.tsx:1516 |
| C0269 | Cancel | local state / inspect handler | {resetVariantForm} | frontend/src/app/(app)/models/[id]/page.tsx:1519 |
| C0270 | Loading... / Add variant | filter/select/expand | {openNewVariantForm} | frontend/src/app/(app)/models/[id]/page.tsx:1524 |
| C0271 | Icon control at line 1555 | open new tab | imagePreviewHref(v.picture_url, v.variant_no \|\| v.code \|\| "") | frontend/src/app/(app)/models/[id]/page.tsx:1555 |
| C0272 | v.variant_no \|\| v.code \|\| "-" | open page/link | `${modelPageBase}/${variantId}` | frontend/src/app/(app)/models/[id]/page.tsx:1566 |
| C0273 | Edit | local state / inspect handler | {() => startEditVariant(v)} | frontend/src/app/(app)/models/[id]/page.tsx:1582 |
| C0274 | Delete | navigate after action | /models | frontend/src/app/(app)/models/[id]/page.tsx:1591 |
| C0275 | Loading... / Load more | filter/select/expand | {() => setVariantPageCount(variantPageCount + 1)} | frontend/src/app/(app)/models/[id]/page.tsx:1616 |
| C0276 | Icon control at line 1653 | open new tab | imagePreviewHref(img.file_url, name) | frontend/src/app/(app)/models/[id]/page.tsx:1653 |
| C0277 | Download | open page/link | img.file_url | frontend/src/app/(app)/models/[id]/page.tsx:1664 |
| C0278 | Delete | local state / inspect handler | {() => deleteImage(img.id)} | frontend/src/app/(app)/models/[id]/page.tsx:1665 |
| C0279 | Icon control at line 1689 | open new tab | imagePreviewHref(primaryImage.file_url, translatedName) | frontend/src/app/(app)/models/[id]/page.tsx:1689 |
| C0280 | Form submission | save/change data | {addSize} | frontend/src/app/(app)/models/[id]/page.tsx:1740 |
| C0281 | Add | submit form | Local form behavior | frontend/src/app/(app)/models/[id]/page.tsx:1747 |
| C0282 | Delete | local state / inspect handler | {() => deleteSize(s.id)} | frontend/src/app/(app)/models/[id]/page.tsx:1761 |
| C0283 | Create new model / Save | navigate after action | `${modelPageBase}/${created.id}?mode=edit` | frontend/src/app/(app)/models/[id]/page.tsx:1822 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0837 | Remove operation | local state / inspect handler | {() => onRemove(operation.id)} | frontend/src/components/PaidOperationsEditor.tsx:74 |
| C0838 | copy.add | local state / inspect handler | {() => { setCreating(!creating); setName(query); setMessage(null); }} | frontend/src/components/PaidProcessPicker.tsx:64 |
| C0839 | Saving... / copy.create | local state / inspect handler | {create} | frontend/src/components/PaidProcessPicker.tsx:71 |
| C0840 | copy.cancel | local state / inspect handler | {() => setCreating(false)} | frontend/src/components/PaidProcessPicker.tsx:72 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P085 /usluga/models

Source: [page](../../frontend/src/app/(app)/usluga/models/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0229 | Create new model | open page/link | `${modelPageBase}/new` | frontend/src/app/(app)/models/page.tsx:180 |
| C0230 | Hide filters / Show filters | filter/select/expand | {() => setShowFilters((open) => !open)} | frontend/src/app/(app)/models/page.tsx:183 |
| C0231 | Create new model | open page/link | `${modelPageBase}/new` | frontend/src/app/(app)/models/page.tsx:186 |
| C0232 | Form submission | submit form | {(e) => e.preventDefault()} | frontend/src/app/(app)/models/page.tsx:188 |
| C0233 | Retry | local state / inspect handler | {() => void mutate()} | frontend/src/app/(app)/models/page.tsx:250 |
| C0234 | ( <VerticalModelPhoto src={imageUrl} alt={modelName} className="w-full border-r border-[#e3dfd3]" loading="lazy" width={240} height={320} adaptiveHeight /> ) / ( <div className="flex aspect-[3/4] w-full flex-col items-ce [dynamic label] | open page/link | `${modelPageBase}/${m.id}` | frontend/src/app/(app)/models/page.tsx:277 |
| C0235 | modelName | open page/link | `${modelPageBase}/${m.id}` | frontend/src/app/(app)/models/page.tsx:301 |
| C0236 | ( <img src={thumb} alt={option.variantNo \|\| option.code} className="h-full w-full object-contain p-1" loading="lazy" /> ) / ( <div className="flex h-full items-center justify-center text-[10px] text-[#8a8472]">{No image} [dynamic label] | open page/link | `${modelPageBase}/${variant.model_id \|\| variant.id}` | frontend/src/app/(app)/models/page.tsx:312 |
| C0237 | View | open page/link | `${modelPageBase}/${m.id}` | frontend/src/app/(app)/models/page.tsx:366 |
| C0238 | Approve | save/change data | {() => approve(m.id)} | frontend/src/app/(app)/models/page.tsx:368 |
| C0239 | Cloning... / Clone | navigate after action | `${modelPageBase}/${cloned.id}?mode=edit` | frontend/src/app/(app)/models/page.tsx:372 |
| C0240 | Edit | open page/link | `${modelPageBase}/${m.id}?mode=edit` | frontend/src/app/(app)/models/page.tsx:380 |
| C0241 | Delete | local state / inspect handler | {() => removeModel(m)} | frontend/src/app/(app)/models/page.tsx:381 |
| C0757 | cancelText ?? Cancel | local state / inspect handler | {onCancel} | frontend/src/components/ConfirmDialog.tsx:30 |
| C0758 | confirmText ?? Confirm | local state / inspect handler | {onConfirm} | frontend/src/components/ConfirmDialog.tsx:31 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0835 | Previous | local state / inspect handler | {() => onPageChange(page - 1)} | frontend/src/components/PaginationControls.tsx:45 |
| C0836 | Next | local state / inspect handler | {() => onPageChange(page + 1)} | frontend/src/components/PaginationControls.tsx:46 |

## P086 /usluga/orders/[id]/edit

Source: [page](../../frontend/src/app/(app)/usluga/orders/[id]/edit/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0592 | Cancel | open page/link | `/usluga/orders/${order.id}` | frontend/src/app/(app)/usluga/orders/[id]/edit/page.tsx:182 |
| C0593 | Add line | local state / inspect handler | {addLine} | frontend/src/app/(app)/usluga/orders/[id]/edit/page.tsx:210 |
| C0594 | Delete | local state / inspect handler | {() => setLines((current) => current.filter((_, rowIndex) => rowIndex !== index))} | frontend/src/app/(app)/usluga/orders/[id]/edit/page.tsx:219 |
| C0595 | Saving... / Save | navigate after action | `/usluga/orders/${order.id}` | frontend/src/app/(app)/usluga/orders/[id]/edit/page.tsx:238 |
| C0596 | Cancel | open page/link | `/usluga/orders/${order.id}` | frontend/src/app/(app)/usluga/orders/[id]/edit/page.tsx:239 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P087 /usluga/orders/[id]

Source: [page](../../frontend/src/app/(app)/usluga/orders/[id]/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0597 | Back to planning | open page/link | /usluga | frontend/src/app/(app)/usluga/orders/[id]/page.tsx:111 |
| C0598 | Open model | open page/link | `/usluga/models/${order.model.id}` | frontend/src/app/(app)/usluga/orders/[id]/page.tsx:112 |
| C0599 | Edit | open page/link | `/usluga/orders/${order.id}/edit` | frontend/src/app/(app)/usluga/orders/[id]/page.tsx:113 |
| C0600 | Hand over | open/close dialog | {() => { setHandover({ recipient: order.customer_name, notes: "" }); setHandoverOpen(true); }} | frontend/src/app/(app)/usluga/orders/[id]/page.tsx:114 |
| C0601 | stageIcon(workOrder.operation) t(`usluga.status.${workOrder.operation}`) workOrder.status workOrder.passed_quantity.toLocaleString() / workOrder.planned_quantity.toLocaleString() | open page/link | `/work-orders/${workOrder.id}/${workOrder.operation}` | frontend/src/app/(app)/usluga/orders/[id]/page.tsx:125 |
| C0602 | Save | save/change data | {() => void saveMaterial()} | frontend/src/app/(app)/usluga/orders/[id]/page.tsx:139 |
| C0603 | Cancel | open/close dialog | {() => setHandoverOpen(false)} | frontend/src/app/(app)/usluga/orders/[id]/page.tsx:167 |
| C0604 | Saving... / Confirm handover | save/change data | {() => void confirmHandover()} | frontend/src/app/(app)/usluga/orders/[id]/page.tsx:167 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P088 /usluga

Source: [page](../../frontend/src/app/(app)/usluga/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0605 | Model catalog | open page/link | /usluga/models | frontend/src/app/(app)/usluga/page.tsx:221 |
| C0606 | New Usluga model | open page/link | /usluga/models/new?mode=edit | frontend/src/app/(app)/usluga/page.tsx:222 |
| C0607 | Refresh | local state / inspect handler | {() => void mutateOrders()} | frontend/src/app/(app)/usluga/page.tsx:223 |
| C0608 | Open model | open page/link | `/usluga/models/${selectedModel.id}` | frontend/src/app/(app)/usluga/page.tsx:238 |
| C0609 | Add line | local state / inspect handler | {addLine} | frontend/src/app/(app)/usluga/page.tsx:259 |
| C0610 | Distribute | local state / inspect handler | {distributeBySizeRange} | frontend/src/app/(app)/usluga/page.tsx:265 |
| C0611 | Delete | local state / inspect handler | {() => setLines((current) => current.filter((_, rowIndex) => rowIndex !== index))} | frontend/src/app/(app)/usluga/page.tsx:274 |
| C0612 | Saving... / Create Usluga order | local state / inspect handler | {() => void createOrder()} | frontend/src/app/(app)/usluga/page.tsx:298 |
| C0613 | formatOrderReference(order.order_no) | open page/link | `/usluga/orders/${order.id}` | frontend/src/app/(app)/usluga/page.tsx:318 |
| C0614 | order.model.code · order.model.name | open page/link | `/usluga/models/${order.model.id}` | frontend/src/app/(app)/usluga/page.tsx:320 |
| C0615 | `${workOrder.operation}: ${workOrder.status}` | open page/link | workOrderLink(workOrder) | frontend/src/app/(app)/usluga/page.tsx:323 |
| C0616 | Hand over | local state / inspect handler | {() => { setFormError(""); setHandoverForm({ recipient: order.customer_name, notes: "" }); setHandoverOrder(order); }} | frontend/src/app/(app)/usluga/page.tsx:325 |
| C0617 | View | open page/link | `/usluga/orders/${order.id}` | frontend/src/app/(app)/usluga/page.tsx:325 |
| C0618 | Edit | open page/link | `/usluga/orders/${order.id}/edit` | frontend/src/app/(app)/usluga/page.tsx:325 |
| C0619 | Cancel | local state / inspect handler | {() => setHandoverOrder(null)} | frontend/src/app/(app)/usluga/page.tsx:339 |
| C0620 | Saving... / Confirm handover | save/change data | {() => void handOver()} | frontend/src/app/(app)/usluga/page.tsx:339 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0870 | placeholder | open/close dialog | {() => { const nextOpen = !open; if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE); setOpen(nextOpen); if (nextOpen) { inputRef.current?.focus(); inputRef.current?.select(); } }} | frontend/src/components/SearchableSelect.tsx:254 |
| C0871 | [dynamic content] option.label ( <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}> {option.metaText} </span> ) / null | open/close dialog | {() => choose(option)} | frontend/src/components/SearchableSelect.tsx:297 |
| C0872 | loadMoreText | local state / inspect handler | {loadMoreOptions} | frontend/src/components/SearchableSelect.tsx:350 |

## P089 /warehouse-map

Source: [page](../../frontend/src/app/(app)/warehouse-map/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0621 | code | filter/select/expand | {() => { setSelectedCell(code); setSelectedShelf("S1"); }} | frontend/src/app/(app)/warehouse-map/page.tsx:528 |
| C0622 | Empty | filter/select/expand | {() => { setSelectedCell(code); setSelectedShelf(shelf); }} | frontend/src/app/(app)/warehouse-map/page.tsx:593 |
| C0623 | top.model_code \|\| top.model_id top.model_name \|\| top.package_no top.color \|\| "-" top.total_quantity Qty | filter/select/expand | {() => { setSelectedCell(code); setSelectedShelf(shelf); }} | frontend/src/app/(app)/warehouse-map/page.tsx:614 |
| C0624 | Clear cell | filter/select/expand | {() => setSelectedCell(null)} | frontend/src/app/(app)/warehouse-map/page.tsx:725 |
| C0625 | Select all | filter/select/expand | {selectAllPackages} | frontend/src/app/(app)/warehouse-map/page.tsx:802 |
| C0626 | Clear selection | filter/select/expand | {clearPackageSelection} | frontend/src/app/(app)/warehouse-map/page.tsx:810 |
| C0627 | row.package_no row.model_code \|\| row.model_id \|\| "-" · row.total_quantity Qty | filter/select/expand | {() => setSelectedPackageId(row.id)} | frontend/src/app/(app)/warehouse-map/page.tsx:821 |
| C0628 | Confirm move / Move selected | save/change data | {handleMove} | frontend/src/app/(app)/warehouse-map/page.tsx:899 |
| C0629 | Bookmark | local state / inspect handler | {toggleBookmark} | frontend/src/app/(app)/warehouse-map/page.tsx:907 |
| C0630 | History | navigate after action | `/packages/${selectedPlacement.id}` | frontend/src/app/(app)/warehouse-map/page.tsx:915 |
| C0631 | QR | local state / inspect handler | {openLabel} | frontend/src/app/(app)/warehouse-map/page.tsx:923 |
| C0632 | Cancel | local state / inspect handler | {cancelMove} | frontend/src/app/(app)/warehouse-map/page.tsx:932 |

## P090 /warehouse-stock/count

Source: [page](../../frontend/src/app/(app)/warehouse-stock/count/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0633 | "Остатки склада" / lang === "uz" ? "Ombor qoldig‘i" : "Warehouse stock" | open page/link | /warehouse-stock | frontend/src/app/(app)/warehouse-stock/count/page.tsx:62 |
| C0634 | Form submission | submit form | {start} | frontend/src/app/(app)/warehouse-stock/count/page.tsx:64 |
| C0635 | text.loading / text.start | local state / inspect handler | Local form behavior | frontend/src/app/(app)/warehouse-stock/count/page.tsx:66 |
| C0636 | count.title new Date(count.created_at).toLocaleString() · text.complete / text.open text.scannedPackages : count.summary.scanned_packages · text.scannedPieces : count.summary.scanned_pieces · text.scanned : count.summary [dynamic label] | local state / inspect handler | {() => selectCount(count.id)} | frontend/src/app/(app)/warehouse-stock/count/page.tsx:74 |
| C0637 | `${text.download}: ${count.title}` | open page/link | `/api/warehouse-stocktakes/${count.id}/export.csv` | frontend/src/app/(app)/warehouse-stock/count/page.tsx:80 |
| C0638 | text.previous | local state / inspect handler | {() => setOffset(offset - 50)} | frontend/src/app/(app)/warehouse-stock/count/page.tsx:83 |
| C0639 | text.next | local state / inspect handler | {() => setOffset(offset + 50)} | frontend/src/app/(app)/warehouse-stock/count/page.tsx:83 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0912 | text.back | local state / inspect handler | {onBack} | frontend/src/components/StocktakeSession.tsx:134 |
| C0913 | text.download | open page/link | `${base}/export.csv` | frontend/src/components/StocktakeSession.tsx:136 |
| C0914 | text.finish | save/change data | {() => void action(`${base}/complete`, text.finishConfirm)} | frontend/src/components/StocktakeSession.tsx:137 |
| C0915 | Form submission | submit form | {submit} | frontend/src/components/StocktakeSession.tsx:145 |
| C0916 | text.add | local state / inspect handler | Local form behavior | frontend/src/components/StocktakeSession.tsx:147 |
| C0917 | text.retry | local state / inspect handler | {() => { failed.current = false; setFailure(""); void drain(); }} | frontend/src/components/StocktakeSession.tsx:152 |
| C0918 | text.discard | local state / inspect handler | {async () => { if (saving.current \|\| busy) return; setBusy(true); try { if (!await ask(text.discardConfirm)) return; const discarded = [...queue.current]; discarded.forEach(scan => removeStocktakePending(localStorage, storageKey, scan.id)); refreshQueue(); failed.current = false; setFailure(""); } catch { setFailure(text.storageError); } finally { setBusy(false); } }} | frontend/src/components/StocktakeSession.tsx:153 |
| C0919 | Form submission | filter/select/expand | {e => { e.preventDefault(); setSearch(query); setOffset(0); input.current?.focus({ preventScroll: true }); }} | frontend/src/components/StocktakeSession.tsx:181 |
| C0920 | Search | local state / inspect handler | Local form behavior | frontend/src/components/StocktakeSession.tsx:181 |
| C0921 | row.snapshot.package_no | open new tab | `/packages/${row.package_id}` | frontend/src/components/StocktakeSession.tsx:187 |
| C0922 | text.undo | save/change data | {() => void action(`${base}/scans/${row.id}`, text.undoConfirm, true)} | frontend/src/components/StocktakeSession.tsx:191 |
| C0923 | text.previous | local state / inspect handler | {() => setOffset(Math.max(0, offset - 100))} | frontend/src/components/StocktakeSession.tsx:195 |
| C0924 | text.next | local state / inspect handler | {() => setOffset(offset + 100)} | frontend/src/components/StocktakeSession.tsx:195 |

## P091 /warehouse-stock/models/[id]

Source: [page](../../frontend/src/app/(app)/warehouse-stock/models/[id]/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0640 | copy.stock | open page/link | `/warehouse-stock?stock_kind=${kind}` | frontend/src/app/(app)/warehouse-stock/models/[id]/page.tsx:18 |
| C0641 | pkg.package_no | open page/link | `/packages/${pkg.id}` | frontend/src/app/(app)/warehouse-stock/models/[id]/page.tsx:22 |
| C0642 | copy.previous | filter/select/expand | {() => setPage(page - 1)} | frontend/src/app/(app)/warehouse-stock/models/[id]/page.tsx:24 |
| C0643 | copy.next | filter/select/expand | {() => setPage(page + 1)} | frontend/src/app/(app)/warehouse-stock/models/[id]/page.tsx:24 |

## P092 /warehouse-stock

Source: [page](../../frontend/src/app/(app)/warehouse-stock/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0644 | copy.standard | local state / inspect handler | {() => setStockKind("standard")} | frontend/src/app/(app)/warehouse-stock/page.tsx:270 |
| C0645 | copy.title | local state / inspect handler | {() => setStockKind("first_grade")} | frontend/src/app/(app)/warehouse-stock/page.tsx:271 |
| C0646 | copy.sale | open page/link | /sales-orders/first-grade | frontend/src/app/(app)/warehouse-stock/page.tsx:272 |
| C0647 | Icon control at line 350 | open new tab | `/warehouse-stock/models/${group.model_id}?stock_kind=${stockKind}` | frontend/src/app/(app)/warehouse-stock/page.tsx:350 |
| C0648 | group.model_code \|\| group.model_id \|\| "-" | open new tab | `/warehouse-stock/models/${group.model_id}?stock_kind=${stockKind}` | frontend/src/app/(app)/warehouse-stock/page.tsx:360 |
| C0649 | Icon control at line 412 | open new tab | `/warehouse-stock/models/${row.model_id}?stock_kind=${stockKind}` | frontend/src/app/(app)/warehouse-stock/page.tsx:412 |
| C0650 | row.model_code \|\| row.model_id \|\| "-" | open new tab | `/warehouse-stock/models/${row.model_id}?stock_kind=${stockKind}` | frontend/src/app/(app)/warehouse-stock/page.tsx:422 |
| C0651 | row.packages[0].package_no | open page/link | `/packages/${row.packages[0].id}` | frontend/src/app/(app)/warehouse-stock/page.tsx:440 |
| C0652 | Passport | open page/link | `/traceability?package=${encodeURIComponent(row.packages[0].package_no)}` | frontend/src/app/(app)/warehouse-stock/page.tsx:444 |
| C0911 | stocktakeText[lang].title | open page/link | /warehouse-stock/count | frontend/src/components/StocktakeLink.tsx:12 |

## P093 /waste

Source: [page](../../frontend/src/app/(app)/waste/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0653 | Form submission | save/change data | {record} | frontend/src/app/(app)/waste/page.tsx:49 |
| C0654 | Record waste | local state / inspect handler | Local form behavior | frontend/src/app/(app)/waste/page.tsx:60 |
| C0655 | Receive | save/change data | {() => act(w.id, "receive")} | frontend/src/app/(app)/waste/page.tsx:80 |
| C0656 | Sell @0.1 | save/change data | {() => act(w.id, "sell", { buyer_name: "Buyer", quantity: w.quantity, unit_price: 0.1 })} | frontend/src/app/(app)/waste/page.tsx:81 |
| C0657 | Request disposal | save/change data | {() => act(w.id, "request-disposal", { reason: "Standard disposal" })} | frontend/src/app/(app)/waste/page.tsx:82 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |

## P094 /work-orders/[id]/cutting

Source: [page](../../frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0663 | Saving... / Complete with actual quantity | save/change data | {completeWithShortage} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1438 |
| C0664 | Add extra batch | open/close dialog | {openExtraBatchForm} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1457 |
| C0665 | Saving... / Save | save/change data | {() => saveBatchPlanEdit(row)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1561 |
| C0666 | Cancel | local state / inspect handler | {cancelBatchPlanEdit} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1569 |
| C0667 | Edit | local state / inspect handler | {() => startBatchPlanEdit(row)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1575 |
| C0668 | Saving... / Complete with actual quantity | save/change data | {completeWithShortage} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1611 |
| C0669 | Saving... / Save | save/change data | {saveExtraBatch} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1647 |
| C0670 | Cancel | open/close dialog | {() => setExtraBatchOpen(false)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1650 |
| C0671 | Auto split | local state / inspect handler | {() => setSplitRows(autoSplitRows(Number(wo?.planned_output_qty \|\| po?.planned_quantity \|\| 0), numberOrFallback(splitMax, 1)))} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1679 |
| C0672 | Add batch | local state / inspect handler | {addSplitRow} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1687 |
| C0673 | Remove | local state / inspect handler | {() => removeSplitRow(index)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1727 |
| C0674 | Saving... / Save batch plan | save/change data | {splitIntoBatches} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1741 |
| C0675 | Adjust bundle quantities | filter/select/expand | {showBundleAdjustments} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1757 |
| C0676 | Add another fabric batch | local state / inspect handler | {() => { setForm((prev) => ({ ...prev, input_quantity: "", cut_pieces: "", report_piece_count: "", waste_quantity: "", layer_material_kg: "", beika_kg: "", material_rolls_used: "", notes: "" })); document.getElementById("usluga-cutting-entry")?.scrollIntoView({ behavior: "smooth", block: "start" }); }} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1779 |
| C0677 | Save | save/change data | {() => saveReportPieces(Number(row.id))} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1864 |
| C0678 | Cancel | local state / inspect handler | {() => { setEditingReportPiecesId(0); setReportPiecesEdit(""); }} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1872 |
| C0679 | Edit | local state / inspect handler | {() => { setEditingReportPiecesId(Number(row.id)); setReportPiecesEdit(Number(row.report_piece_count \|\| 0)); }} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1894 |
| C0680 | Print cutting sheet | local state / inspect handler | {() => { const bundleIds = Array.isArray(row.bundle_ids) ? row.bundle_ids.join(",") : ""; const query = bundleIds ? `?bundle_ids=${encodeURIComponent(bundleIds)}` : ""; api.openLabel(`/api/cutting/records/${row.id}/production-sheet${query}`); }} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1925 |
| C0681 | Edit | local state / inspect handler | {() => { setEditingUslugaSizeCountsId(Number(row.id)); setUslugaSizeCountEdits(sizeCountRows.map((sizeRow: any) => ({ color: String(sizeRow.color \|\| ""), size: String(sizeRow.size \|\| ""), quantity: Number(sizeRow.quantity \|\| 0), bundle_count: Number(sizeRow.bundle_count \|\| 0), }))); }} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1937 |
| C0682 | Approve batch | save/change data | {() => approveUslugaBatch(Number(row.id))} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1957 |
| C0683 | Reject batch | local state / inspect handler | {() => { setUslugaRejectingId(Number(row.id)); setUslugaRejectReason(""); }} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1965 |
| C0684 | Reject batch | save/change data | {() => rejectUslugaBatch(Number(row.id))} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1988 |
| C0685 | Cancel | local state / inspect handler | {() => setUslugaRejectingId(0)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:1991 |
| C0686 | Save | save/change data | {() => saveUslugaSizeCounts(Number(row.id))} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2023 |
| C0687 | Cancel | local state / inspect handler | {() => { setEditingUslugaSizeCountsId(0); setUslugaSizeCountEdits([]); }} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2031 |
| C0688 | Form submission | save/change data | {submit} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2059 |
| C0689 | Cutting Passports | open page/link | `/cutting-passports?production_order_id=${po?.id}` | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2090 |
| C0690 | Close / Search | open/close dialog | {() => { setFabricPickerOpen((open) => !open); setFabricSearch(""); }} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2128 |
| C0691 | compactParts([batch.item_sku, batch.item_name]) \|\| t("page.cutting.itemId", { id: batch.item_id }) [dynamic content] fmtQty(batchAvailableQty(batch)) unit Number(batch.cost_per_unit \|\| 0) > 0 && ( <div>{fmtQty(batch.cost [dynamic label] | open/close dialog | {() => selectFabricBatch(batch)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2144 |
| C0692 | + Add bundle line | local state / inspect handler | {addB} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2305 |
| C0693 | Remove | local state / inspect handler | {() => remB(i)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2341 |
| C0694 | Saving... / isSecondaryUslugaFabric ? Save : Save & create bundles | local state / inspect handler | Local form behavior | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2356 |
| C0695 | <ChevronDown className="h-4 w-4 shrink-0" /> / <ChevronRight className="h-4 w-4 shrink-0" /> Order No orderReference(po, createdBundlesBatchLabel) visibleBundles.length Bundles.toLowerCase() Hide labels / Show labels | filter/select/expand | {() => setCreatedBundlesExpanded((open) => !open)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2369 |
| C0696 | t(isMilanaCutting && canEditBreakdown && wo?.status !== "completed" ? "page.cutting.printAndComplete" : "page.cutting.printProductionSheet") | local state / inspect handler | {async () => { setPrintingSheet(true); setShortageErr(""); try { const query = printableBundleIds ? `?bundle_ids=${encodeURIComponent(printableBundleIds)}` : ""; await api.openLabel(`/api/cutting/records/${printableCuttingRecordId}/production-sheet${query}`, isMilanaCutting && canEditBreakdown ? "POST" : "GET"); await Promise.all([mutateWo(), mutatePo(), mutateBatchProgress()]); } catch (error: any) { setShortageErr(error.message \|\| t("page.cutting.shortageFailed")); } finally { setPrintingSheet(false); } }} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2412 |
| C0697 | Print all labels | local state / inspect handler | {() => api.openLabel(`/api/bundles/label-sheet/by-ids?ids=${encodeURIComponent(visibleBundleIds)}`)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2432 |
| C0698 | Print | local state / inspect handler | {() => api.openLabel(`/api/bundles/${b.id}/label`)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2498 |
| C0699 | Save | save/change data | {saveBundleAdjustment} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2503 |
| C0700 | Cancel | local state / inspect handler | {() => setAdjustingBundle(null)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2506 |
| C0701 | Adjust | local state / inspect handler | {() => beginBundleAdjustment(b)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2512 |
| C0702 | Edit Cutting details | local state / inspect handler | {() => beginCuttingDetailsEdit(Number(b.cutting_record_id \|\| 0))} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2516 |
| C0703 | Saving... / Delete | local state / inspect handler | {() => deleteCreatedBundle(b)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2528 |
| C0704 | Saving... / Save | save/change data | {saveCuttingDetailsEdit} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2617 |
| C0705 | Cancel | local state / inspect handler | {() => setEditingCuttingDetails(null)} | frontend/src/app/(app)/work-orders/[id]/cutting/page.tsx:2620 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0942 | Icon control at line 144 | open new tab | imagePreviewHref(image?.file_url, name) | frontend/src/components/WorkOrderProductInfo.tsx:144 |
| C0943 | attachmentName(file, Qolip file) | open page/link | file.file_url \|\| "#" | frontend/src/components/WorkOrderProductInfo.tsx:369 |
| C0944 | Edit | local state / inspect handler | {openBreakdownEditor} | frontend/src/components/WorkOrderProductInfo.tsx:387 |
| C0945 | Remove | local state / inspect handler | {() => removeBreakdownRow(index)} | frontend/src/components/WorkOrderProductInfo.tsx:432 |
| C0946 | Add | local state / inspect handler | {addBreakdownRow} | frontend/src/components/WorkOrderProductInfo.tsx:451 |
| C0947 | Cancel | local state / inspect handler | {() => { setBreakdownEditing(false); setBreakdownMsg(""); }} | frontend/src/components/WorkOrderProductInfo.tsx:454 |
| C0948 | Saving... / Save changes | local state / inspect handler | {saveBreakdown} | frontend/src/components/WorkOrderProductInfo.tsx:462 |

## P095 /work-orders/[id]/packaging

Source: [page](../../frontend/src/app/(app)/work-orders/[id]/packaging/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0706 | Form submission | save/change data | {submitRec} | frontend/src/app/(app)/work-orders/[id]/packaging/page.tsx:648 |
| C0707 | Save packaging record | local state / inspect handler | Local form behavior | frontend/src/app/(app)/work-orders/[id]/packaging/page.tsx:689 |
| C0708 | Form submission | save/change data | {createPkg} | frontend/src/app/(app)/work-orders/[id]/packaging/page.tsx:740 |
| C0709 | Remove | local state / inspect handler | {() => setPkgItems(pkgItems.filter((_, j) => j !== i))} | frontend/src/app/(app)/work-orders/[id]/packaging/page.tsx:851 |
| C0710 | + Add size | local state / inspect handler | {() => setPkgItems([...pkgItems, { size: "L", quantity: "" }])} | frontend/src/app/(app)/work-orders/[id]/packaging/page.tsx:857 |
| C0711 | Creating... / packagePlans.length > 1 ? t("page.packaging.createCopies", { count: packagePlans.length }) : Create package | local state / inspect handler | Local form behavior | frontend/src/app/(app)/work-orders/[id]/packaging/page.tsx:860 |
| C0712 | Apply to all | local state / inspect handler | {() => setPackageWeights(Array.from({ length: packageWeightCount }, () => weightKg))} | frontend/src/app/(app)/work-orders/[id]/packaging/page.tsx:947 |
| C0713 | Print label | local state / inspect handler | {() => api.openLabel(`/api/packages/${pkg.id}/label`)} | frontend/src/app/(app)/work-orders/[id]/packaging/page.tsx:992 |
| C0757 | cancelText ?? Cancel | local state / inspect handler | {onCancel} | frontend/src/components/ConfirmDialog.tsx:30 |
| C0758 | confirmText ?? Confirm | local state / inspect handler | {onConfirm} | frontend/src/components/ConfirmDialog.tsx:31 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0785 | copy.title | open/close dialog | {() => setOpen(!open)} | frontend/src/components/FirstGradePackaging.tsx:23 |
| C0786 | Form submission | submit form | {async e => { e.preventDefault(); if (!me \|\| busy \|\| total < 1 \|\| total > 200) return; setBusy(true); setMessage(""); try { const packages = data.sizes.flatMap(row => Array.from({ length: quantities[row.size] \|\| 0 }, () => ({ production_order_id: productionOrderId, production_batch_id: batchId \|\| null, model_id: modelId, color, stock_kind: "first_grade", capacity: 1, items: [{ model_id: modelId, color, size: row.size, quantity: 1 }], }))); const result = await postPackageWorkflow<PackagePrintRun>(path, { packages }, me.id); setRun(result); setQuantities({}); setMessage(copy.saved); await mutate(); await onChanged(); } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); } }} | frontend/src/components/FirstGradePackaging.tsx:28 |
| C0787 | copy.create ( total /200) | local state / inspect handler | Local form behavior | frontend/src/components/FirstGradePackaging.tsx:45 |
| C0788 | copy.print | local state / inspect handler | {async () => { try { await api.openLabel(`/api/packages/print-runs/${run.id}/label`); } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); } }} | frontend/src/components/FirstGradePackaging.tsx:48 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0816 | copy.reprint | local state / inspect handler | {async () => { setPrintError(""); try { await api.openLabel(`/api/packages/print-runs/${run.id}/label`); } catch (e: any) { setPrintError(e.message); } }} | frontend/src/components/PackagePrintRuns.tsx:33 |
| C0817 | copy.deletePacks | filter/select/expand | {() => { setSelectedRun(run); setSelectedIds([]); }} | frontend/src/components/PackagePrintRuns.tsx:37 |
| C0818 | copy.cancel | filter/select/expand | {() => setSelectedRun(null)} | frontend/src/components/PackagePrintRuns.tsx:44 |
| C0819 | copy.deletePacks ( selectedIds.length ) | filter/select/expand | {async () => { if (!selectedRun \|\| !(await dialogs.ask({ message: `${selectedRun.run_no} · ${selectedIds.length} ${copy.packages}. ${copy.deleteConfirm}` }))) return; setDeleting(selectedRun.id); setPrintError(""); try { const query = new URLSearchParams(selectedIds.map(id => ["package_ids", String(id)])); await api.del(`/api/packages/print-runs/${selectedRun.id}/manual-packages?${query}`); setSelectedRun(null); setSelectedIds([]); await mutate(); await mutateCache(key => typeof key === "string" && (key.startsWith("/api/packages") \|\| key.startsWith("/api/finished-goods"))); } catch (e: any) { setPrintError(e.message); } finally { setDeleting(null); } }} | frontend/src/components/PackagePrintRuns.tsx:44 |
| C0820 | copy.createRun | filter/select/expand | {async () => { setBusy(true); setError(""); try { const run = await postPackageWorkflow<PackagePrintRun>("/api/packages/print-runs", { package_ids: selectedIds }, me!.id); setSelectedIds([]); setRunRefresh(value => value + 1); await api.openLabel(`/api/packages/print-runs/${run.id}/label`); } catch (e: any) { setError(e.message); } finally { setBusy(false); } }} | frontend/src/components/PackageQrSection.tsx:257 |
| C0821 | Print all labels | local state / inspect handler | {() => api.openLabel(`/api/packages/label-sheet/by-ids?ids=${encodeURIComponent(packageIds)}`)} | frontend/src/components/PackageQrSection.tsx:268 |
| C0822 | View | open page/link | `/packages/${p.id}` | frontend/src/components/PackageQrSection.tsx:332 |
| C0823 | Label | local state / inspect handler | {() => api.openLabel(`/api/packages/${p.id}/label`)} | frontend/src/components/PackageQrSection.tsx:333 |
| C0824 | Download QR | open page/link | p.qr_code_url | frontend/src/components/PackageQrSection.tsx:335 |
| C0825 | Edit | local state / inspect handler | {() => openEdit(p)} | frontend/src/components/PackageQrSection.tsx:339 |
| C0826 | Delete | local state / inspect handler | {() => setDeleting(p)} | frontend/src/components/PackageQrSection.tsx:340 |
| C0827 | Approve | save/change data | {() => approveRequest(pending)} | frontend/src/components/PackageQrSection.tsx:343 |
| C0828 | Reject | save/change data | {() => rejectRequest(pending)} | frontend/src/components/PackageQrSection.tsx:344 |
| C0829 | Form submission | save/change data | {submitEditRequest} | frontend/src/components/PackageQrSection.tsx:374 |
| C0830 | Add | local state / inspect handler | {addItemRow} | frontend/src/components/PackageQrSection.tsx:405 |
| C0831 | Remove | local state / inspect handler | {() => removeItemRow(idx)} | frontend/src/components/PackageQrSection.tsx:412 |
| C0832 | Cancel | local state / inspect handler | {() => { setEditing(null); setEditForm(null); }} | frontend/src/components/PackageQrSection.tsx:442 |
| C0833 | Saving... / Request approval | submit form | Local form behavior | frontend/src/components/PackageQrSection.tsx:443 |
| C0843 | c.loading / c.retry | local state / inspect handler | {async () => { setBusy(true); setError(""); try { const run = await postPackageWorkflow<PackagePrintRun>(path, pending, me.id); setPending(null); await onResolved(); await api.openLabel(`/api/packages/print-runs/${run.id}/label`); } catch (e: any) { setError(e.message); } finally { setBusy(false); } }} | frontend/src/components/PendingPackageWorkflow.tsx:26 |
| C0942 | Icon control at line 144 | open new tab | imagePreviewHref(image?.file_url, name) | frontend/src/components/WorkOrderProductInfo.tsx:144 |
| C0943 | attachmentName(file, Qolip file) | open page/link | file.file_url \|\| "#" | frontend/src/components/WorkOrderProductInfo.tsx:369 |
| C0944 | Edit | local state / inspect handler | {openBreakdownEditor} | frontend/src/components/WorkOrderProductInfo.tsx:387 |
| C0945 | Remove | local state / inspect handler | {() => removeBreakdownRow(index)} | frontend/src/components/WorkOrderProductInfo.tsx:432 |
| C0946 | Add | local state / inspect handler | {addBreakdownRow} | frontend/src/components/WorkOrderProductInfo.tsx:451 |
| C0947 | Cancel | local state / inspect handler | {() => { setBreakdownEditing(false); setBreakdownMsg(""); }} | frontend/src/components/WorkOrderProductInfo.tsx:454 |
| C0948 | Saving... / Save changes | local state / inspect handler | {saveBreakdown} | frontend/src/components/WorkOrderProductInfo.tsx:462 |

## P096 /work-orders/[id]/printing

Source: [page](../../frontend/src/app/(app)/work-orders/[id]/printing/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0714 | Form submission | save/change data | {collectForPlan} | frontend/src/app/(app)/work-orders/[id]/printing/page.tsx:171 |
| C0715 | Loading... / Collect | local state / inspect handler | Local form behavior | frontend/src/app/(app)/work-orders/[id]/printing/page.tsx:185 |
| C0716 | file.file_name \|\| file.file_url | open new tab | file.file_url | frontend/src/app/(app)/work-orders/[id]/printing/page.tsx:251 |
| C0717 | Form submission | save/change data | {submit} | frontend/src/app/(app)/work-orders/[id]/printing/page.tsx:303 |
| C0718 | Save record | local state / inspect handler | Local form behavior | frontend/src/app/(app)/work-orders/[id]/printing/page.tsx:350 |
| C0942 | Icon control at line 144 | open new tab | imagePreviewHref(image?.file_url, name) | frontend/src/components/WorkOrderProductInfo.tsx:144 |
| C0943 | attachmentName(file, Qolip file) | open page/link | file.file_url \|\| "#" | frontend/src/components/WorkOrderProductInfo.tsx:369 |
| C0944 | Edit | local state / inspect handler | {openBreakdownEditor} | frontend/src/components/WorkOrderProductInfo.tsx:387 |
| C0945 | Remove | local state / inspect handler | {() => removeBreakdownRow(index)} | frontend/src/components/WorkOrderProductInfo.tsx:432 |
| C0946 | Add | local state / inspect handler | {addBreakdownRow} | frontend/src/components/WorkOrderProductInfo.tsx:451 |
| C0947 | Cancel | local state / inspect handler | {() => { setBreakdownEditing(false); setBreakdownMsg(""); }} | frontend/src/components/WorkOrderProductInfo.tsx:454 |
| C0948 | Saving... / Save changes | local state / inspect handler | {saveBreakdown} | frontend/src/components/WorkOrderProductInfo.tsx:462 |

## P097 /work-orders/[id]/sewing

Source: [page](../../frontend/src/app/(app)/work-orders/[id]/sewing/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0719 | Form submission | save/change data | {submit} | frontend/src/app/(app)/work-orders/[id]/sewing/page.tsx:257 |
| C0720 | Save record | local state / inspect handler | Local form behavior | frontend/src/app/(app)/work-orders/[id]/sewing/page.tsx:325 |
| C0781 | dialog.cancelText ?? Cancel | local state / inspect handler | {() => close(false)} | frontend/src/components/DialogProvider.tsx:73 |
| C0782 | dialog.confirmText ?? (dialog.kind === "confirm" ? Confirm : OK) | local state / inspect handler | {() => close(true)} | frontend/src/components/DialogProvider.tsx:77 |
| C0807 | title children | local state / inspect handler | {closeOnOutsideClick ? onClose : undefined} | frontend/src/components/Modal.tsx:32 |
| C0808 | title children | local state / inspect handler | {(e) => e.stopPropagation()} | frontend/src/components/Modal.tsx:36 |
| C0809 | Close | local state / inspect handler | {onClose} | frontend/src/components/Modal.tsx:42 |
| C0875 | Edit | local state / inspect handler | {() => { setEditing({ ...row }); setFailure(""); }} | frontend/src/components/SewingRecordHistory.tsx:56 |
| C0876 | Delete | save/change data | {() => void save(row, true)} | frontend/src/components/SewingRecordHistory.tsx:57 |
| C0877 | Form submission | save/change data | {(event) => { event.preventDefault(); void save(editing); }} | frontend/src/components/SewingRecordHistory.tsx:60 |
| C0878 | Save changes | local state / inspect handler | Local form behavior | frontend/src/components/SewingRecordHistory.tsx:68 |
| C0879 | Cancel | local state / inspect handler | {() => setEditing(null)} | frontend/src/components/SewingRecordHistory.tsx:68 |
| C0942 | Icon control at line 144 | open new tab | imagePreviewHref(image?.file_url, name) | frontend/src/components/WorkOrderProductInfo.tsx:144 |
| C0943 | attachmentName(file, Qolip file) | open page/link | file.file_url \|\| "#" | frontend/src/components/WorkOrderProductInfo.tsx:369 |
| C0944 | Edit | local state / inspect handler | {openBreakdownEditor} | frontend/src/components/WorkOrderProductInfo.tsx:387 |
| C0945 | Remove | local state / inspect handler | {() => removeBreakdownRow(index)} | frontend/src/components/WorkOrderProductInfo.tsx:432 |
| C0946 | Add | local state / inspect handler | {addBreakdownRow} | frontend/src/components/WorkOrderProductInfo.tsx:451 |
| C0947 | Cancel | local state / inspect handler | {() => { setBreakdownEditing(false); setBreakdownMsg(""); }} | frontend/src/components/WorkOrderProductInfo.tsx:454 |
| C0948 | Saving... / Save changes | local state / inspect handler | {saveBreakdown} | frontend/src/components/WorkOrderProductInfo.tsx:462 |

## P098 /work-orders

Source: [page](../../frontend/src/app/(app)/work-orders/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0658 | orderReference(w, `#${w.production_order_id}`) | open page/link | `/production-orders/${w.production_order_id}` | frontend/src/app/(app)/work-orders/page.tsx:64 |
| C0659 | Cutting | open page/link | `/work-orders/${w.id}/cutting` | frontend/src/app/(app)/work-orders/page.tsx:86 |
| C0660 | Printing | open page/link | `/work-orders/${w.id}/printing` | frontend/src/app/(app)/work-orders/page.tsx:87 |
| C0661 | Sewing | open page/link | `/work-orders/${w.id}/sewing` | frontend/src/app/(app)/work-orders/page.tsx:88 |
| C0662 | Packaging | open page/link | `/work-orders/${w.id}/packaging` | frontend/src/app/(app)/work-orders/page.tsx:89 |

## P099 /image-preview

Source: [page](../../frontend/src/app/image-preview/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0721 | Download | open page/link | src | frontend/src/app/image-preview/ImagePreviewClient.tsx:14 |

## P100 /login

Source: [page](../../frontend/src/app/login/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0722 | Open presentation page | open page/link | /presentation | frontend/src/app/login/page.tsx:173 |
| C0723 | Open presentation page | open page/link | /presentation | frontend/src/app/login/page.tsx:266 |
| C0724 | t(`language.${l}`) | local state / inspect handler | {() => setLang(l)} | frontend/src/app/login/page.tsx:275 |
| C0725 | Form submission | navigate after action | / | frontend/src/app/login/page.tsx:303 |
| C0726 | Signing in... / Continue [dynamic content] | submit form | Local form behavior | frontend/src/app/login/page.tsx:350 |
| C0727 | Cancel | open/close dialog | {() => setForgotOpen(false)} | frontend/src/app/login/page.tsx:377 |
| C0728 | Form submission | submit form | {submitForgotPassword} | frontend/src/app/login/page.tsx:389 |
| C0729 | Cancel | open/close dialog | {() => setForgotOpen(false)} | frontend/src/app/login/page.tsx:418 |
| C0730 | Requesting... / Request reset | submit form | Local form behavior | frontend/src/app/login/page.tsx:421 |
| C0731 | trailing | local state / inspect handler | {onTrailingClick} | frontend/src/app/login/page.tsx:461 |

## P101 /presentation

Source: [page](../../frontend/src/app/presentation/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0847 | `${String(index + 1).padStart(2, "0")} ${step.title}: ${step.shortLabel}` | local state / inspect handler | {() => setActiveIndex(index)} | frontend/src/components/presentation/LiveFactoryProcess.tsx:64 |
| C0848 | Milana Ecosystem | open page/link | /presentation | frontend/src/components/presentation/PresentationLanding.tsx:39 |
| C0849 | item.label | open page/link | item.href | frontend/src/components/presentation/PresentationLanding.tsx:47 |
| C0850 | content.controls.login | open page/link | /login | frontend/src/components/presentation/PresentationLanding.tsx:56 |
| C0851 | content.controls.explore | open page/link | #flow | frontend/src/components/presentation/PresentationLanding.tsx:59 |
| C0852 | content.controls.menu | open/close dialog | {() => setMobileOpen(true)} | frontend/src/components/presentation/PresentationLanding.tsx:65 |
| C0853 | content.controls.closeMenu | open/close dialog | {() => setMobileOpen(false)} | frontend/src/components/presentation/PresentationLanding.tsx:80 |
| C0854 | item.label | open page/link | item.href | frontend/src/components/presentation/PresentationLanding.tsx:97 |
| C0855 | content.controls.login | open page/link | /login | frontend/src/components/presentation/PresentationLanding.tsx:106 |
| C0856 | content.controls.explore | open page/link | #flow | frontend/src/components/presentation/PresentationLanding.tsx:110 |
| C0857 | content.controls.login | open page/link | /login | frontend/src/components/presentation/PresentationLanding.tsx:141 |
| C0858 | item.label | open page/link | item.href | frontend/src/components/presentation/PresentationLanding.tsx:145 |
| C0859 | option.title | local state / inspect handler | {() => setLang(option.value)} | frontend/src/components/presentation/PresentationLanding.tsx:172 |
| C0860 | content.controls.light | local state / inspect handler | {() => setTheme("day")} | frontend/src/components/presentation/PresentationLanding.tsx:203 |
| C0861 | content.controls.dark | local state / inspect handler | {() => setTheme("night")} | frontend/src/components/presentation/PresentationLanding.tsx:214 |
| C0862 | content.hero.primaryAction | open page/link | #flow | frontend/src/components/presentation/PresentationLanding.tsx:271 |
| C0863 | content.hero.secondaryAction | open page/link | /login | frontend/src/components/presentation/PresentationLanding.tsx:275 |
| C0864 | content.finalCta.primaryAction | open page/link | #flow | frontend/src/components/presentation/PresentationLanding.tsx:568 |
| C0865 | content.finalCta.secondaryAction | open page/link | /login | frontend/src/components/presentation/PresentationLanding.tsx:572 |

## P102 /reset-password

Source: [page](../../frontend/src/app/reset-password/page.tsx).

| Control | Label or data expression | Effect | Destination or local handler | Evidence |
|---|---|---|---|---|
| C0732 | Form submission | submit form | {onSubmit} | frontend/src/app/reset-password/page.tsx:56 |
| C0733 | Resetting... / Reset password | submit form | Local form behavior | frontend/src/app/reset-password/page.tsx:96 |
| C0734 | Back to sign in | open page/link | /login | frontend/src/app/reset-password/page.tsx:107 |

## Shared controls and component boundaries

The CSV and JSON retain every discovered control, including global shell, dialogs, configurable controls and components with no statically resolved route owner. A blank owner is unresolved attribution, not proof that the control is unused. The main workflow guide describes business effects; this appendix preserves exact source evidence.
