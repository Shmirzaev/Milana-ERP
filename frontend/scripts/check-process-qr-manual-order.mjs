import assert from "node:assert/strict";
import fs from "node:fs";
import { runtimeMessages } from "./runtime-locales.mjs";

const page = fs.readFileSync("src/app/(app)/process-qr/page.tsx", "utf8");
const translations = ["en", "ru", "uz"].map(runtimeMessages);

assert.match(page, /sourceMode.*"erp".*"manual"/s, "Process QR must expose ERP and manual source modes");
assert.match(page, /\$\{manualModelApiBase\}\/model-options\?search=.*page=1&page_size=50/, "Manual variants must use bounded factory-catalog model search");
assert.match(page, /manualProductionReference\(selectedModelId, kroyNo\)/, "Manual jobs need a stable model-and-Kroy reference");
assert.match(page, /paidOperationsFromDetails\(selectedModel\.details_json, !isUslugaModel\)/, "Paid operations must load from the selected variant with the service-model boundary");
assert.match(page, /selectedModel\.sizes/, "Manual size inputs must come from the selected model variant");
assert.match(page, /order_no=\$\{encodeURIComponent\(selectedProcess\.production_no\)\}/, "Previously issued manual labels must reload by their exact reference");
assert.match(page, /production_order_id: label\.process\.is_manual \? null/, "Manual labels must not invent a production-order foreign key");
assert.match(page, /production_batch_id: label\.process\.is_manual \? null/, "Manual labels must not invent a production-batch foreign key");
assert.match(page, /if \(process\.is_manual\)/, "Manual label identifiers must use a dedicated deterministic branch");
assert.match(page, /buildOperationLabelTokens\(factoryOperations, issuedLabels\)/, "Duplicate checked operation codes must receive distinct label identities");
assert.match(page, /label_uid: label\.labelUid/, "Issued manual labels must use the collision-safe identity computed for the preview");

for (const key of [
  "page.processQr.erpOrder",
  "page.processQr.manualOrder",
  "page.processQr.searchVariant",
  "page.processQr.kroyNoPlaceholder",
  "page.processQr.manualModelHasNoSizes",
]) {
  assert.ok(translations.every(messages => messages.has(key)), `${key} must exist in all runtime languages`);
}

console.log("Process QR manual-order contract passed.");
