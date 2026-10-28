import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const transpile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React } }).outputText;
const helper = await import(`data:text/javascript;base64,${Buffer.from(transpile(fs.readFileSync("src/lib/processQrSizeAllocation.ts", "utf8"))).toString("base64")}`);
const { allocateLabelSizes, allocationQuantity, issuedSizeAllocationConflicts } = helper;
const sizes = ["46", "48", "50", "52", "54"];
const values = allocation => allocation.rows.map(row => row.quantity);
assert.deepEqual(values(allocateLabelSizes(300, [], sizes)), [60, 60, 60, 60, 60]);
assert.deepEqual(values(allocateLabelSizes(302, [], sizes)), [61, 61, 60, 60, 60]);
assert.deepEqual(values(allocateLabelSizes(2, [], sizes)), [1, 1, 0, 0, 0]);
assert.deepEqual(values(allocateLabelSizes(300, [], [...sizes, "46", " 48 ", "", "-"])), [60, 60, 60, 60, 60]);
assert.equal(allocateLabelSizes(300, [], []).valid, false);
assert.equal(allocateLabelSizes(-1, [], sizes).valid, false);
assert.equal(allocateLabelSizes(1.5, [], sizes).valid, false);
const allocated = allocateLabelSizes(300, [{ size: "46", sewing_completed_quantity: 200 }, { size: "48", sewing_completed_quantity: 100 }], sizes);
assert.deepEqual(values(allocated), [200, 100]);
assert.equal(allocated.suggested, false);
assert.equal(allocated.valid, true);
const partial = allocateLabelSizes(300, [{ size: "46", sewing_completed_quantity: 50 }], sizes);
assert.deepEqual(values(partial), [100, 50, 50, 50, 50]);
assert.equal(partial.valid, true);
assert.equal(allocateLabelSizes(20, [{ size: "46", sewing_completed_quantity: 30 }], sizes).valid, false);
const base = allocateLabelSizes(300, [], sizes);
const quantities = { "46": 50, "48": 70, "50": 60, "52": 60, "54": 60 };
const draft = { fingerprint: base.fingerprint, quantities };
assert.deepEqual(values(allocateLabelSizes(300, [], sizes, draft)), [50, 70, 60, 60, 60]);
assert.deepEqual(values(allocateLabelSizes(305, [], sizes, draft)), [61, 61, 61, 61, 61], "changed physical totals invalidate stale drafts");
for (const bad of ["", -1, 50.5, NaN, Infinity, 1]) {
  assert.equal(allocateLabelSizes(300, [], sizes, { ...draft, quantities: { ...quantities, "46": bad } }).valid, false);
}
assert.equal(allocateLabelSizes(300, [{ size: "46", sewing_completed_quantity: 50 }], sizes, {
  fingerprint: partial.fingerprint, quantities: { "46": 49, "48": 101, "50": 50, "52": 50, "54": 50 },
}).valid, false, "recorded output cannot be reassigned");
assert.equal(allocationQuantity(base, "46"), 60);
assert.equal(allocationQuantity(allocateLabelSizes(300, [], []), "46"), 0);
const proposed = [{ labelUid: "PY:319:189:K:OP:M:SEW:46:1", quantity: 50 }];
assert.equal(issuedSizeAllocationConflicts(proposed, [{ label_uid: proposed[0].labelUid, quantity: 60, status: "available" }]), true);
assert.equal(issuedSizeAllocationConflicts(proposed, [{ label_uid: proposed[0].labelUid, quantity: 50, status: "scanned" }]), false);
assert.equal(issuedSizeAllocationConflicts(proposed, [{ label_uid: "PY:319:189:K:OP:M:SEW:48:1", quantity: 60, status: "available" }]), true);
assert.equal(issuedSizeAllocationConflicts(proposed, [{ label_uid: "PY:319:192:K:OP:M:SEW:46:1", quantity: 60, status: "available" }]), false);

// Execute the actual page's preview and issuance handler, not a mirrored implementation.
const source = fs.readFileSync("src/app/(app)/process-qr/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let candidate, issue;
const declarations = ast.statements.filter(node => ts.isFunctionDeclaration(node) && node.name?.text !== "ProcessQrPage").map(node => node.getText(ast)).join("\n");
function visit(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(ast) === "candidateLabels") candidate = node.initializer.arguments[0].getText(ast);
  if (ts.isFunctionDeclaration(node) && node.name?.text === "issueLabels") issue = node.getText(ast);
  ts.forEachChild(node, visit);
}
visit(ast); assert.ok(candidate); assert.ok(issue);
const process = { production_order_id: 319, production_no: "PO-0294", model_id: 8456, model_code: "KJ13051-V-6472", stages: [] };
const batches = [189, 192].map((id, index) => ({ key: `batch-${id}`, batchId: id, batchIndex: index + 1, batchNo: `0319-0${index + 1}`, serial: `0319-0${index + 1}`, sewingSizes: [], sewingCompletedQuantity: 300 }));
const operation = { id: "op", code: "OP-6162", name: "Sleeve", section: "sewing", sewingFactory: "milana", selected: true, copies: 1, splitMode: "none", rate: 550 };
const writes = [];
const context = vm.createContext({
  console, Map, Set, Math, Number, String, JSON, encodeURIComponent,
  selectedProcess: process, selectedSewingLine: { id: 6, code: "SEW-06", name: "Line 6" },
  selectedModel: { id: 8456 }, selectedModelId: 8456, loadedOperationsModelId: 8456,
  issuedLabelsLoading: false, issuedLabelsError: null, invalidSizeAllocation: false, issuedSizeConflict: false,
  sizeOptions: sizes.map(size => ({ size })), batchesToPrint: batches, factoryOperations: [operation],
  sizeQuantityMode: "custom", customSizeQuantities: {}, sameSizeQuantity: 0, currency: "UZS",
  erpSizeAllocations: new Map([[batches[0].key, allocateLabelSizes(300, [], sizes, draft)], [batches[1].key, base]]),
  allocationQuantity, operationLabelTokens: new Map([["op", "OP-6162"]]), FACTORY_SHORT_CODES: { milana: "M" },
  issuingLabels: false, operationIdentityNeedsReview: false,
  api: { post: async (url, body) => { writes.push({ url, body }); return { created_count: body.labels.length }; } },
  setIssuingLabels() {}, setPrintError() {}, setIssueNotice() {}, mutateIssuedLabels: async () => {},
  t: key => key, window: { requestAnimationFrame() {} },
});
vm.runInContext(transpile(declarations + "\n" + issue + `\nfunction generate(){ return (${candidate})(); }`), context);
let labels = vm.runInContext("generate()", context);
assert.equal(labels.length, 10);
assert.deepEqual(Array.from(labels.filter(row => row.batch.batchId === 189), row => row.quantity), [50,70,60,60,60]);
assert.deepEqual(Array.from(labels.filter(row => row.batch.batchId === 192), row => row.quantity), [60,60,60,60,60]);
context.unissuedLabels = labels;
await vm.runInContext("issueLabels()", context);
assert.equal(writes.length, 1);
assert.equal(writes[0].url, "/api/payroll/qr-labels/issue");
assert.equal(writes[0].body.labels[0].quantity, 50);
assert.equal(writes[0].body.labels[0].production_batch_id, 189);
assert.equal(writes[0].body.labels[0].size, "46");
assert.equal(writes[0].body.labels[0].payload.split("*")[10], "50");
for (const gate of ["invalidSizeAllocation", "issuedSizeConflict", "issuedLabelsLoading", "operationIdentityNeedsReview"]) {
  context[gate] = true;
  await vm.runInContext("issueLabels()", context);
  assert.equal(writes.length, 1, `${gate} blocks issuance`);
  context[gate] = false;
}
context.invalidSizeAllocation = true;
assert.equal(vm.runInContext("generate()", context).length, 0);
context.invalidSizeAllocation = false;
context.selectedProcess = { ...process, is_manual: true, manual_kroy_no: "TEST" };
context.batchesToPrint = [batches[0]];
context.customSizeQuantities = { "46": 7, "48": 8, "50": 0, "52": 0, "54": 0 };
assert.deepEqual(Array.from(vm.runInContext("generate()", context), row => row.quantity), [7, 8], "manual quantities are unchanged");
console.log("PASS: size allocation, conservation, partial output, invalid/stale drafts, issued-label conflict and real preview-to-issue payload; manual flow preserved.");
