import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const directReceiving = fs.readFileSync("src/app/(app)/inventory/receive/page.tsx", "utf8");
const purchaseReceiving = fs.readFileSync("src/app/(app)/purchasing/receiving/page.tsx", "utf8");
const rollWeights = fs.readFileSync("src/lib/materialRollWeights.ts", "utf8");

assert.match(directReceiving, /MaterialRollWeightFields/,
  "Direct receiving must accept exact individual roll weights");
assert.match(directReceiving, /form\.roll_weights_kg\.map\(Number\)/,
  "Direct receiving must persist entered weights without redistributing them");
assert.match(directReceiving, /rollWeightsTotal\(weights\)/,
  "The receipt total must follow the entered roll weights");
assert.match(directReceiving, /readOnly=\{individualRolls\}/,
  "Individual weights determine the total and roll count");
assert.match(directReceiving, /divideBatchQuantityByRollCount/,
  "Total-only receiving must retain its existing allocation");
assert.doesNotMatch(purchaseReceiving, /MaterialRollWeightFields|validRollWeights|rollWeightsTotal/,
  "Purchase-order receiving keeps its existing total/count workflow");
assert.match(purchaseReceiving, /divideBatchQuantityByRollCount/);

assert.match(directReceiving, /toReceivePayload\(receiveForm, isFabricReceiving\)/,
  "Direct fabric receiving must submit generated roll weights");
assert.match(directReceiving, /required=\{requireRollCount\}/,
  "Direct fabric receiving must require a roll count");
assert.match(purchaseReceiving, /piece_count: usesRollWeights \? rollCount : null/,
  "Purchase-order receiving must save the entered roll count");
assert.match(purchaseReceiving, /roll_weights_kg: rollWeights/,
  "Purchase-order receiving must save generated weights");
assert.doesNotMatch(purchaseReceiving, /readOnly=\{isKilogramUnit/,
  "Purchase-order total kg must remain editable");
assert.match(purchaseReceiving, /step=\{isKilogramUnit\(receiveState\.line\.unit\) \? "0\.01" : "0\.0001"\}/,
  "Purchase-order fabric kg must be entered to the same precision used by roll stickers");
assert.match(rollWeights, /totalHundredths - baseHundredths \* count/,
  "Automatic allocation must preserve the exact two-decimal total");

console.log("Receiving automatic roll-weight contract passed.");

// Exercise the actual payload builder: unequal rolls must not become averages.
const numberHelper = directReceiving.slice(directReceiving.indexOf("function numberOrZero("), directReceiving.indexOf("function toReceivePayload("));
const payloadHelper = directReceiving.slice(directReceiving.indexOf("function toReceivePayload("), directReceiving.indexOf("function materialColorLabel("));
const code = ts.transpile(`${rollWeights.replace("export function", "function")}\n${numberHelper}\n${payloadHelper}\nglobalThis.buildPayload = toReceivePayload;`, { target: ts.ScriptTarget.ES2020 });
const context = {};
vm.runInNewContext(code, context);
const form = { item_id: 1, batch_no: "roll-entry", color: "white", quantity: 35.5, unit: "kg", cost_per_unit: 0, warehouse_id: 1, qc_status: "passed", supplier_id: 0, old_code: "", color_code: "", color_status: "", order_no: "", gsm: "", roll_lengths_m: ["42.125", ""], piece_count: 2, roll_weights_kg: ["15.5", "20"], weight_entry: "rolls", processes: "", image_url: "" };
const exact = context.buildPayload(form, true);
assert.equal(JSON.stringify(exact.roll_weights_kg), "[15.5,20]");
assert.equal(exact.quantity, 35.5);
assert.equal(exact.piece_count, 2);
assert.equal(JSON.stringify(exact.roll_lengths_m), "[42.125,null]");
assert.ok(!("length_m" in exact));
const totalOnly = context.buildPayload({ ...form, weight_entry: "total", quantity: 10, piece_count: 3 }, true);
assert.equal(JSON.stringify(totalOnly.roll_weights_kg), "[3.34,3.33,3.33]");
assert.equal(JSON.stringify(totalOnly.roll_lengths_m), "[42.125,null,null]");
assert.equal(JSON.stringify(context.buildPayload(form, false).roll_lengths_m), "[]");
assert.equal(JSON.stringify(context.buildPayload(form, false).roll_weights_kg), "[]");
for (const lang of ["en", "ru", "uz"]) {
  const runtime = fs.readFileSync(`src/lib/i18n/locales/${lang}-base.ts`, "utf8");
  for (const key of ["fabricRollEntry.totalKg", "fabricRollEntry.individual", "materialLength.perRoll", "materialLength.rolls", "passportBatch.add", "sewingReport.deleteConfirm"]) assert.ok(runtime.includes(`"${key}"`), `${lang} runtime missing ${key}`);
}
console.log("Exact roll-weight payload and runtime labels passed.");
