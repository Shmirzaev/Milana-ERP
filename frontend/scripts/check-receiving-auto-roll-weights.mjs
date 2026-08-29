import assert from "node:assert/strict";
import fs from "node:fs";

const directReceiving = fs.readFileSync("src/app/(app)/inventory/receive/page.tsx", "utf8");
const purchaseReceiving = fs.readFileSync("src/app/(app)/purchasing/receiving/page.tsx", "utf8");
const rollWeights = fs.readFileSync("src/lib/materialRollWeights.ts", "utf8");

for (const [name, source] of [["direct fabric receiving", directReceiving], ["purchase-order receiving", purchaseReceiving]]) {
  assert.doesNotMatch(source, /MaterialRollWeightFields|validRollWeights|rollWeightsTotal/,
    `${name} must not ask operators for each roll's kg`);
  assert.match(source, /divideBatchQuantityByRollCount/,
    `${name} must automatically divide total kg by roll count`);
}

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
