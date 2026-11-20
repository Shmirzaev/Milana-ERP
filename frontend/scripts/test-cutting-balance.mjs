import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/cuttingBalance.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { cuttingPiecesText, cuttingBundlesText } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

assert.equal(cuttingPiecesText({ pieces: 0, pieces_min: 0, pieces_max: 0 }), "0");
assert.equal(cuttingPiecesText({ pieces: 22908, pieces_min: 22908, pieces_max: 22908 }), (22908).toLocaleString());
assert.equal(cuttingPiecesText({ pieces: null, pieces_min: 0, pieces_max: 50 }), "0–50");
assert.equal(cuttingPiecesText(undefined), "—");
assert.equal(cuttingPiecesText({}), "—");
assert.equal(cuttingBundlesText({}, "Needs count"), "—");
for (const needsCount of ["Needs count", "Нужен пересчёт", "Qayta sanash kerak"]) {
  assert.equal(cuttingBundlesText({ bundles: null }, needsCount), needsCount);
  assert.equal(cuttingBundlesText({ bundles: 0 }, needsCount), "0");
}
console.log("Cutting balances: exact zero, exact pieces, unresolved ranges, rollout compatibility and EN/RU/UZ bundle counts passed.");
