import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const pagePath = path.join(root, "src", "app", "(app)", "inventory", "page.tsx");
const source = fs.readFileSync(pagePath, "utf8");

const requiredPatterns = [
  ['supplier is loaded into the batch form', 'supplier_id: batch.supplier_id ? String(batch.supplier_id) : ""'],
  ['supplier is sent in the batch update payload', 'supplier_id: form.supplier_id ? Number(form.supplier_id) : null'],
  ['supplier options are loaded from the supplier API', '"/api/suppliers"'],
  ['supplier selector is bound to the batch form', 'value={batchForm.supplier_id}'],
  ['saving a batch uses the batch update endpoint', 'api.patch(`/api/inventory/batches/${editingBatch.id}`, batchPayload(batchForm))'],
];

const missing = requiredPatterns.filter(([, pattern]) => !source.includes(pattern));
if (missing.length) {
  for (const [label, pattern] of missing) {
    console.error(`Missing inventory supplier-edit contract: ${label}\n  ${pattern}`);
  }
  process.exit(1);
}

const supplierSelector = source.indexOf('value={batchForm.supplier_id}');
const batchDetails = source.indexOf('{editingBatch && (', supplierSelector);
if (supplierSelector < 0 || batchDetails < 0 || supplierSelector > batchDetails) {
  console.error("The supplier selector must remain visible at the top of the batch edit form.");
  process.exit(1);
}

console.log("Inventory supplier-edit contract check passed.");
