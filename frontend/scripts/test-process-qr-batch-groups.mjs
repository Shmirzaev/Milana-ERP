import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync("src/app/(app)/process-qr/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = new Set([
  "issuedBatchKey", "groupIssuedLabelsByBatch", "compareIssuedLabelOrder",
  "compareGarmentSizes", "namedSizeRank", "normalizedSizeName", "operationNumberForLabel", "printIssuedLabels", "deleteIssuedSize",
]);
const declarations = [];
function visit(node) {
  if (ts.isFunctionDeclaration(node) && names.has(node.name?.text)) declarations.push(node.getText(ast));
  ts.forEachChild(node, visit);
}
visit(ast);
assert.equal(declarations.length, names.size);
const issuedSizeOrder = new Map([["122", 0], ["128", 1]]);
const issuedOperationNumbers = new Map();
let prepared, confirmation, deletion;
const label = (id, batch, size, operation, copy = 1, extra = {}) => {
  issuedOperationNumbers.set(id, operation);
  return {
    id, factory_code: "MIL", production_order_id: 420, production_batch_id: batch,
    batch_no: `0420-${String(batch).padStart(2, "0")}`, size, copy_index: copy,
    qr_token: String(200000000 + id), quantity: 75, status: "available",
    ...extra,
  };
};
const labels = [
  label(1, 2, "122", 1), label(2, 1, "128", 1),
  label(3, 1, "122", 2), label(4, 1, "122", 1, 2),
  label(5, 10, "122", 1), label(6, 1, "122", 1),
  label(7, 2, "128", 2), label(8, 2, "122", 2),
];
const original = JSON.stringify(labels);
const context = vm.createContext({
  Map, Set, String, Number, Math, JSON, console,
  issuedSizeOrder, issuedOperationNumbers, preparingPrint: false, deletingSize: null,
  qrDataUrl: async token => { await new Promise(resolve => setTimeout(resolve, Number(token) % 3)); return `image:${token}`; },
  setPrintError: value => assert.equal(value, ""),
  setPreparingPrint() {}, setWorkLabelsToPrint: rows => { prepared = rows; },
  printSelectedMode: mode => assert.equal(mode, "work"),
  t: (key, args) => { if (key.endsWith("deleteSizeConfirm")) confirmation = args; return key; },
  dialogs: { ask: async () => true, notify: async () => assert.fail("unused labels must be deletable") },
  setDeletingSize() {}, setIssueNotice() {}, mutateIssuedLabels: async () => {},
  api: { post: async (url, body) => { deletion = { url, body }; return { deleted_count: body.label_ids.length, size: body.size }; } },
});
const namedSizes = ast.statements.find(node => ts.isVariableStatement(node) && node.declarationList.declarations.some(d => d.name.getText(ast) === "NAMED_SIZE_ORDER"));
vm.runInContext(ts.transpile(namedSizes.getText(ast) + "\n" + declarations.join("\n"), { target: ts.ScriptTarget.ES2022 }), context);
const sorted = [...labels].sort((a, b) => context.compareIssuedLabelOrder(a, b, issuedSizeOrder, issuedOperationNumbers));
assert.deepEqual(sorted.map(row => row.id), [6, 4, 3, 2, 1, 8, 7, 5],
  "finish every process/copy/size in a batch before starting the next batch; batch 2 precedes 10");
const groups = context.groupIssuedLabelsByBatch(sorted);
assert.deepEqual(Array.from(groups, batch => batch.batchNo), ["0420-01", "0420-02", "0420-10"]);
assert.deepEqual(Array.from(groups[0].sizes.keys()), ["122", "128"]);
assert.deepEqual(Array.from(groups[0].sizes.get("122"), row => row.id), [6, 4, 3]);
await context.printIssuedLabels(labels);
assert.deepEqual(Array.from(prepared, row => row.label.id), sorted.map(row => row.id));
assert.ok(prepared.every(row => row.qrImage === `image:${row.label.qr_token}`));
await context.printIssuedLabels(groups[1].labels);
assert.deepEqual(Array.from(prepared, row => row.label.id), [1, 8, 7], "batch printing excludes siblings");
await context.printIssuedLabels(groups[0].sizes.get("122"));
assert.deepEqual(Array.from(prepared, row => row.label.id), [6, 4, 3], "size printing stays inside its batch");
await context.deleteIssuedSize("122", groups[0].sizes.get("122"));
assert.deepEqual(Array.from(deletion.body.label_ids), [6, 4, 3], "size deletion sends only this batch's exact IDs");
assert.equal(confirmation.batch, "0420-01");
assert.equal(confirmation.size, "122");
assert.equal(JSON.stringify(labels), original, "sorting/printing must not rewrite QR identities or quantities");

// Equal display names never merge different actual batches, orders or factories.
const sameNames = [
  label(20, 1, "122", 2), label(21, 2, "122", 1, 1, { batch_no: "0420-01" }),
  label(22, 1, "122", 1, 1, { factory_code: "BST" }),
  label(23, 1, "122", 1, 1, { production_order_id: 421 }),
  label(24, 1, "122", 1),
];
sameNames.sort((a, b) => context.compareIssuedLabelOrder(a, b, issuedSizeOrder, issuedOperationNumbers));
const separate = context.groupIssuedLabelsByBatch(sameNames);
assert.equal(separate.length, 4);
assert.ok(separate.every(group => group.labels.every(row => context.issuedBatchKey(row) === group.key)));
const legacy = [
  label(30, null, "122", 1, 1, { batch_no: null }),
  label(31, null, "128", 1, 1, { batch_no: null }),
  label(32, null, "122", 1, 1, { batch_no: "Manual 1" }),
  label(33, null, "122", 1, 1, { batch_no: "Manual 2" }),
];
assert.equal(context.groupIssuedLabelsByBatch(legacy).length, 3, "manual and unbatched labels remain available");
for (const lang of ["en", "ru", "uz"]) {
  const locale = fs.readFileSync(`src/lib/i18n/locales/${lang}-supplemental.ts`, "utf8");
  for (const key of ["printThisBatch", "noBatch"]) assert.ok(locale.includes(`"page.processQr.${key}"`));
  assert.match(locale, /"page\.processQr\.deleteSizeConfirm": "[^\n]*\{batch\}/);
}
console.log("Actual QR grouping, numeric batch order, split copies, print boundary and exact-batch deletion passed.");
