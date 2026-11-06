import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
const source = fs.readFileSync("src/app/(app)/cutting-passports/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const functions = [];
function visit(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === "compute") functions.push(node.getText(ast));
  ts.forEachChild(node, visit);
}
visit(ast);
const context = vm.createContext({});
vm.runInContext(ts.transpileModule(functions.join("\n"), { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText, context);
const form = { meter_mode: true, pieces: 600, lay_length_m: 7.72, fabric_width_m: 1.77, gramage: 0.191, other_beka_per_piece_kg: 0.015 };
for (const [length, ae, q] of [[7.72, 1.559, 935.4], [7.88, 1.591, 954.6]]) {
 const result = context.compute({ ...form, lay_length_m: length }, 5);
 assert.equal(Number(result.AE.toFixed(6)), ae);
 assert.equal(Number(result.Q.toFixed(6)), q);
}
const kg = context.compute({ ...form, meter_mode: false, beka_per_piece_kg: 0.01 }, 5);
assert.equal(kg.AE, 1.77 * 7.72 * 0.191 / 5 + 0.01 + 0.015);
const metres = context.compute({ ...form, beka_per_piece_kg: 0.01, scrap_kg: 2 }, 5);
assert.equal(Number(metres.Q.toFixed(6)), 943.4);
assert.equal(context.compute(form, 0).Q, 0);
assert.match(source, /checked=\{f.meter_mode\} onChange=\{sf\("meter_mode"\)\}/);
assert.match(source, /meter_mode: p.meter_mode \?\? false/);
assert.match(source, /meter_mode: form.meter_mode/);
console.log("Metre workbook calculations, kg fallback and checkbox persistence passed.");
