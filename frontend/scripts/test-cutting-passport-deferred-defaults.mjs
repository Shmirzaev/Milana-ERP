import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync("src/app/(app)/cutting-passports/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const functions = [];
function visit(node) { if (ts.isFunctionDeclaration(node) && ["selectProductionOrder", "preserveSingleMaterialDraft", "materialDraftChanged", "clearPendingDefaults", "reviewMaterialDefaults", "save"].includes(node.name?.text)) functions.push(node.getText(ast)); ts.forEachChild(node, visit); }
visit(ast);
const keys = ast.statements.find(node => ts.isVariableStatement(node) && node.declarationList.declarations.some(d => d.name.getText(ast) === "MATERIAL_DRAFT_KEYS")).getText(ast);
const code = ts.transpileModule([keys, ...functions].join("\n"), { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
const pending = [];
let form = { production_order_id: "", order_no: "", pieces: "", planned_kg: "" }, materials = [], pendingState = false, questions = [];
const ctx = vm.createContext({
  resetMaterialPicker() {}, pendingApply: { current: null }, setMaterialDefaultsPending(value) { pendingState = value; },
  saving: false, get materialDefaultsPending() { return pendingState; }, setErr() {}, setSaving() { throw new Error("save must be blocked"); },
  dialogs: { ask() { return new Promise(resolve => questions.push(resolve)); } }, t: x => x,
  materialFormsRef: { get current() { return materials; } }, orderRequest: { current: 0 }, pendingOrderInitial: { current: null }, mounted: { current: true }, draftRevision: { current: 0 }, EMPTY_FORM: {},
  setMaterialForms(value) { materials = typeof value === "function" ? value(materials) : value; }, setBatchInfos() {}, setSizeChoices() {}, rememberBatches() {},
  prodOrdersArr: [{ id: 1, planned_quantity: 20 }], rawOrderReference: () => "order",
  setForm(value) { form = typeof value === "function" ? value(form) : value; },
  api: { get() { return new Promise(resolve => pending.push(resolve)); } },
  get form() { return form; },
  formRef: { get current() { return form; } },
  modelCodeParts: () => null, modelQolipNo: () => "", expandSizeSelection: () => [],
});
vm.runInContext(code, ctx);
const first = ctx.selectProductionOrder("1");
form = { ...form, pieces: 77 }; ctx.draftRevision.current++;
pending.shift()({ pieces: 20, model_code: "M-1", materials: [{ stock_batch_id: 5 }] }); await first;
assert.equal(form.pieces, 77, "late defaults must preserve an edited draft");
assert.equal(form.model_code, "M-1", "unrelated defaults still apply");
assert.equal(materials[0].stock_batch_id, 5, "late defaults must still supply material rows");
assert.equal(({ ...form, ...materials[0] }).pieces, 77, "visible single material retains edited pieces");
const second = ctx.selectProductionOrder("1");
ctx.orderRequest.current++;
pending.shift()({ pieces: 30, materials: [{ stock_batch_id: 6 }] }); await second;
assert.equal(form.pieces, 20, "a closed or changed order must reject late defaults");
assert.equal(materials.length, 0);
const third = ctx.selectProductionOrder("1");
pending.shift()({ pieces: 31, materials: [{ stock_batch_id: 7 }] }); await third;
assert.equal(form.pieces, 31, "unmodified drafts receive defaults");
assert.equal(materials[0].stock_batch_id, 7);
const two = ctx.preserveSingleMaterialDraft([{ pieces: 11 }, { pieces: 12 }], { pieces: 77 }, { pieces: 20 });
assert.deepEqual(Array.from(two, row => row.pieces), [11, 12], "never duplicate a manual quantity across multiple materials");
const fourth = ctx.selectProductionOrder("1");
form = { ...form, pieces: 77 };
pending.shift()({ materials: [{ stock_batch_id: 8, pieces: 10 }, { stock_batch_id: 9, pieces: 20 }] });
await new Promise(resolve => setImmediate(resolve));
assert.equal(pendingState, true); assert.equal(materials.length, 0); assert.equal(form.pieces, 77);
questions.shift()(false); await fourth;
assert.equal(pendingState, true, "cancel keeps save blocked"); assert.equal(form.pieces, 77);
await ctx.save({ preventDefault() {} });
let review = ctx.reviewMaterialDefaults(); questions.shift()(true); await review;
assert.equal(pendingState, false); assert.deepEqual(Array.from(materials, r => r.pieces), [10, 20]);
const fifth = ctx.selectProductionOrder("1"); form = { ...form, pieces: 88 };
pending.shift()({ materials: [{ stock_batch_id: 8 }, { stock_batch_id: 9 }] }); await new Promise(resolve => setImmediate(resolve));
ctx.orderRequest.current++; questions.shift()(true); await fifth;
assert.equal(materials.length, 0, "stale confirmation cannot apply");
ctx.clearPendingDefaults();
const editedWhileAsking = ctx.selectProductionOrder("1"); form = { ...form, pieces: 99 };
pending.shift()({ materials: [{ stock_batch_id: 8 }, { stock_batch_id: 9 }] }); await new Promise(resolve => setImmediate(resolve));
ctx.draftRevision.current++; questions.shift()(true); await editedWhileAsking;
assert.equal(pendingState, true, "edits while confirmation is open keep the draft pending"); assert.equal(materials.length, 0);
ctx.clearPendingDefaults();
const sixth = ctx.selectProductionOrder("1");
pending.shift()({ materials: [{ stock_batch_id: 8, pieces: 10 }, { stock_batch_id: 9, pieces: 20 }] }); await sixth;
assert.equal(questions.length, 0, "unchanged material draft does not prompt");
assert.deepEqual(Array.from(materials, r => r.pieces), [10, 20]);
console.log("Cutting order defaults preserve changed drafts and reject stale requests.");
