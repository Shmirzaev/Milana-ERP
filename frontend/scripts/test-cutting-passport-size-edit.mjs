import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync("src/app/(app)/cutting-passports/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = new Set(["openEdit", "expandSizeSelection", "uniqueSizes", "cleanSize", "sizeCountForSelection", "compute"]);
const functions = [];
function visit(node) {
  if (ts.isFunctionDeclaration(node) && names.has(node.name?.text)) functions.push(node.getText(ast));
  ts.forEachChild(node, visit);
}
visit(ast);
const code = ts.transpileModule(functions.join("\n"), { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
const requests = [];
const state = {};
const context = vm.createContext({
  orderRequest: { current: 0 }, EMPTY_FORM: {},
  resetMaterialPicker() {}, setMaterialForms() {}, setEditing() {}, setShowForm() {},
  setSizeChoices: sizes => { state.sizes = Array.from(sizes); },
  setForm: form => { state.form = form; }, setErr: error => { state.error = error; },
  api: { get: url => new Promise(resolve => requests.push({ url, resolve })) },
});
vm.runInContext(code, context);
context.openEdit({ production_order_id: 297, size_range: "48", date: "2026-10-07" });
assert.deepEqual(state.sizes, ["48"]);
assert.ok(requests[0].url.endsWith("production_order_id=297"));
requests[0].resolve({ sizes: ["48"], available_sizes: ["48", "50", "52", "54"] });
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(state.sizes, ["48"], "Model-only sizes must not be mixed into order choices");
assert.equal(state.form.size_range, "48", "Loading options must preserve the saved selection and measurements");
context.openEdit({ production_order_id: 298, size_range: "M", date: "2026-10-07" });
context.openEdit({ production_order_id: 299, size_range: "S", date: "2026-10-07" });
requests[1].resolve({ sizes: ["M", "L"] });
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(state.sizes, ["S"], "A late response must not replace another order's sizes");
requests[2].resolve({ sizes: ["S", "M"] });
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(state.sizes, ["S", "M"]);
console.log("Passport editing loads all order sizes without overwriting saved input or accepting stale responses.");

const children = ["122", "128", "134", "140", "146", "152"];
assert.equal(context.sizeCountForSelection("122-152", children), 6);
assert.equal(context.sizeCountForSelection(children.join(", ") + " ×2", children), 12);
assert.equal(context.sizeCountForSelection("128-146", children), 4);
assert.equal(context.sizeCountForSelection("128", children), 1);
assert.equal(context.sizeCountForSelection("40-42", ["40-42", "44-46"]), 1);
assert.equal(context.sizeCountForSelection("40-42, 44-46 ×2", ["40-42", "44-46"]), 4);
assert.equal(context.sizeCountForSelection("46", children), 0);

const measurements = { pieces: 600, fabric_width_m: 1.8, lay_length_m: 3.37, gramage: .191,
  beka_per_piece_kg: .005, other_beka_per_piece_kg: .001, scrap_kg: 2 };
for (const [selection, divisor] of [["122-152", 6], [children.join(", ") + " ×2", 12]]) {
  for (const meter_mode of [false, true]) {
    const result = context.compute({ ...measurements, meter_mode }, context.sizeCountForSelection(selection, children));
    const expected = (meter_mode ? 3.37 : 1.8 * 3.37 * .191) / divisor + .006;
    assert.ok(Math.abs(result.AE - expected) < 1e-9);
    assert.ok(Math.abs(result.Q - (expected * 600 + 2)) < 1e-9);
  }
}
console.log("Order 122–152 uses six exact sizes, twelve doubled, and correct kg/metre fabric consumption.");
