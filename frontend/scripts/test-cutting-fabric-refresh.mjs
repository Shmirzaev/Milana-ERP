import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync("src/app/(app)/work-orders/[id]/cutting/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = new Set(["submit", "refreshFabricSources", "saveCuttingDetailsEdit", "deleteCuttingBatch"]), functions = [];
function visit(node) {
  if (ts.isFunctionDeclaration(node) && names.has(node.name?.text)) functions.push(node.getText(ast));
  ts.forEachChild(node, visit);
}
visit(ast);
assert.equal(functions.length, 4);
const code = ts.transpileModule(functions.join("\n"), { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
function fixture() {
  const refreshes = [], requests = [];
  const context = vm.createContext({
    submitting: false, editingBatchId: 0, batchPlanEditBusy: false, extraBatchBusy: false,
    isUsluga: false, isSecondaryUslugaFabric: false, isAlreadyBatched: false, hasPlannedMaterials: false,
    deferMaterialUsage: false, usePassportMaterials: true, selectedPassportId: 1, bundlePlanTotal: 10,
    id: 9, form: { fabric_batch_id: 7, input_quantity: 6.5, cut_pieces: 10 }, fabricPickedManually: true,
    bundles: [{ quantity: 10, count: 1 }], cuttingMaterials: [],
    numberOrZero: value => Number(value || 0), numberOrFallback: (value, fallback) => Number(value || fallback),
    emptyMaterialDetails: () => ({}), mergeBundleRows: (...rows) => rows.flat(), t: key => key,
    setErr: value => { context.error = value; }, setDoneMsg() {}, setSubmitting() {}, setLastCuttingRecordId() {},
    setCreatedBundles() {}, setCreatedBundlesExpanded() {}, setCuttingMaterials() {},
    setForm: value => { context.form = typeof value === "function" ? value(context.form) : value; },
    mutatePo: async () => {}, mutateWo: async () => {}, mutateBatchProgress: async () => {},
    mutateBundles: async () => {}, mutateUslugaCutting: async () => {},
    refreshFabricBatches: async () => { refreshes.push("filtered-central"); },
    refreshAllMaterialBatches: async () => { refreshes.push("all-central"); },
    refreshEcoFabricSources: async () => { refreshes.push("eco"); context.visibleBalance = { quantity: 93.5, reserved_quantity: 10, available_quantity: 83.5 }; },
    setEditingCuttingDetailsBusy() {}, setEditingCuttingDetailsErr() {}, setEditingCuttingDetails() {},
    setBatchPlanEditBusy() {}, setBatchPlanEditErr() {}, setEditingBatchId() {}, window: { confirm: () => true },
    api: { post: async (...args) => { requests.push(args); return { id: 1, bundles: [] }; },
      patch: async (...args) => { requests.push(args); }, del: async (...args) => { requests.push(args); } },
  });
  vm.runInContext(code, context);
  return { context, refreshes, requests };
}

const success = fixture();
let acknowledge;
success.context.api.post = () => new Promise(resolve => { acknowledge = resolve; });
const pending = success.context.submit({ preventDefault() {} });
assert.equal(success.refreshes.length, 0, "Do not refresh or invent successful balances before the write is acknowledged");
acknowledge({ id: 1, bundles: [] });
await pending;
assert.deepEqual(success.refreshes.sort(), ["all-central", "eco", "filtered-central"]);
assert.deepEqual(success.context.visibleBalance, { quantity: 93.5, reserved_quantity: 10, available_quantity: 83.5 });
assert.equal(success.context.form.fabric_batch_id, 7);
assert.equal(success.context.fabricPickedManually, true);

const failed = fixture();
failed.context.api.post = async () => { throw Error("Refused consumption"); };
await failed.context.submit({ preventDefault() {} });
assert.equal(failed.refreshes.length, 0);
assert.equal(failed.context.error, "Refused consumption");

for (const pendingUsage of [false, true]) {
  const detail = fixture();
  detail.context.editingCuttingDetails = { recordId: 1, groupedMaterials: false, materialUsagePending: pendingUsage,
    materials: [{ stock_batch_id: 7, quantity: 6.5, unit: "kg", details: {} }],
    layer_material_kg: 0, beika_kg: 0, material_rolls_used: 0, layup_operator_name: "", notes: "" };
  await detail.context.saveCuttingDetailsEdit();
  assert.equal(detail.refreshes.length, pendingUsage ? 3 : 0, "Deferred usage refreshes sources; metadata-only editing does not");
}
const reversal = fixture();
await reversal.context.deleteCuttingBatch({ id: 1, name: "Nastil" });
assert.equal(reversal.refreshes.length, 3, "Successful stock reversal refreshes exact source balances");
const usluga = fixture(); usluga.context.isUsluga = true;
await usluga.context.refreshFabricSources();
assert.equal(usluga.refreshes.length, 0);
console.log("Actual Cutting handlers refresh three existing source reads after acknowledged spend/reversal, preserve selection and leave refused/metadata/Usluga actions untouched.");
