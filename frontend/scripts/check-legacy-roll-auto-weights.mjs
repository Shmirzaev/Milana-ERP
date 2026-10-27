import assert from "node:assert/strict";
import fs from "node:fs";

const modal = fs.readFileSync("src/components/MaterialQrStickerModal.tsx", "utf8");
const inventory = fs.readFileSync("src/app/(app)/inventory/page.tsx", "utf8");
const rollWeights = fs.readFileSync("src/lib/materialRollWeights.ts", "utf8");

assert.match(rollWeights, /function divideBatchQuantityByRollCount/,
  "Existing batch labels must derive roll weights from total kg and roll count");
assert.match(rollWeights, /totalHundredths - baseHundredths \* count/,
  "Rounded per-roll weights must preserve the complete batch quantity");
assert.match(modal, /import \{ divideBatchQuantityByRollCount \} from "@\/lib\/materialRollWeights"/,
  "Existing batch labels must use the shared automatic roll-weight calculation");
assert.match(modal, /t\("common\.print"\)/,
  "Existing batch labels must expose a direct Print action");
assert.doesNotMatch(modal, /MaterialRollWeightFields|roll_weights_kg|\/roll-weights|saveAndPrint/,
  "Existing batch printing must not ask for or save manual roll weights");
assert.doesNotMatch(inventory, /onSaved=|rollWeightsKg:/,
  "Material Inventory must not refresh or pass saved roll weights into legacy printing");
assert.match(modal, /createPortal\([\s\S]*material-qr-print-sheet[\s\S]*document\.body/,
  "The printable sticker sheet must be portaled directly under document.body");
assert.match(modal, /body\.material-qr-print-active > \*:not\(\.material-qr-print-sheet\) \{ display: none !important; \}/,
  "Non-print ERP layout must be removed so it cannot create blank print pages");
assert.doesNotMatch(modal, /body\.material-qr-print-active \* \{ visibility: hidden/,
  "Print isolation must not use visibility because hidden ERP layout still paginates");

console.log("Legacy material roll auto-weight contract passed.");
