import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const page = readFileSync(new URL("../src/app/(app)/sales-orders/new/page.tsx", import.meta.url), "utf8");
const locale = readFileSync(new URL("../src/lib/readySalesLocale.ts", import.meta.url), "utf8");
assert.match(page, /\/api\/sales-orders\/ready-stock-options/,
  "Available packs must come from the backend's whole-package eligibility check.");
assert.match(page, /isBrandedOrder \? \{ requested_pack_count: linePacks\(line\) \} : \{ quantity: linePieces\(line\) \}/,
  "Ready sales submit pack counts; only production sales submit a piece quantity.");
assert.doesNotMatch(page, /piecesPerPack|effectivePackPieces|includePartialPacks|full_pack_count|partial_pack_count/,
  "Sales must not choose package capacity or split physical packs into synthetic quantities.");
assert.match(page, /aria-label=\{packText.packCount\}/,
  "The pack-count control needs a localized accessible label.");
assert.match(page, /isBrandedOrder \? packText.warehouseConfirms/,
  "The order total must remain explicitly pending warehouse confirmation.");
assert.match(page, /onChange=\{\(e\) => updateLine\(i, "quantity", parseNumberInput\(e.target.value\)\)\}/,
  "Production sales must retain the editable piece quantity.");
const exports = {};
vm.runInNewContext(ts.transpileModule(locale, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports });
const english = exports.readySalesText("en");
for (const language of ["en", "ru", "uz"]) {
  const messages = exports.readySalesText(language);
  assert.deepEqual(Object.keys(messages), Object.keys(english));
  for (const message of Object.values(messages)) assert.ok(message.trim());
  if (language !== "en") assert.notEqual(messages.scanTotals, english.scanTotals);
}
console.log("Ready-sales physical pack and locale contract passed.");
