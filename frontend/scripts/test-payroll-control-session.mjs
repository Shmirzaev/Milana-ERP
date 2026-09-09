// Execute the actual scanner handlers with deferred APIs to verify employee races.
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/payroll/scan/page.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = ["selectEmployee", "showControlReview", "recordNumericWorkScan", "confirmControlReview"];
const functions = [];
function visit(node) {
  if (ts.isFunctionDeclaration(node) && names.includes(node.name?.text)) functions.push(node.getText(ast));
  ts.forEachChild(node, visit);
}
visit(ast);
assert.equal(functions.length, names.length);
const js = ts.transpile(functions.join("\n"), { target: ts.ScriptTarget.ES2020 });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const A = { employee_id: 1, employee_name: "Employee A" };
const B = { employee_id: 2, employee_name: "Employee B" };
const preview = { review_token: "review", work: { type: "process_payroll", label_id: "CTRL-1", quantity: 10 } };
const state = { review: null, employee: A, error: "", records: [], notices: [] };
let pending = deferred();
const calls = [];
const env = {
  controlConfirmRef: { current: false }, scanSequenceRef: { current: 1 },
  controlReviewRef: { current: null }, currentEmployeeRef: { current: A },
  recordsRef: { current: [] }, workRecordByKeyRef: { current: new Map() },
  canSavePayroll: true, lang: "en", inputRef: { current: { focus() {} } },
  api: { post: (path, body) => { calls.push({ path, body }); return pending.promise; } },
  normalizeScanPayload: value => value,
  setControlReview: value => { state.review = value; }, setCurrentEmployee: value => { state.employee = value; },
  setControlError: value => { state.error = value; }, setControlBusy() {},
  setNotice: value => { state.notices.push(value); },
  controlScanMessages: { en: { pending: "Review pending", error: "Confirmation failed" } },
  t: value => value, numberOrZero: Number,
  toPayrollRecord: (employee, work) => ({ employeeId: employee.employee_id, employeeName: employee.employee_name, quantity: work.quantity }),
  replaceRecords: records => { state.records = records; }, payrollScanRecordMatchesLabel: () => false,
};
const handlers = new Function(...Object.keys(env), `${js}; return {${names.join(",")}};`)(...Object.values(env));

// A scans Control, then selects B before the numeric response arrives.
const scan = handlers.recordNumericWorkScan("200000001", A, 1);
assert.equal(handlers.selectEmployee(B), true);
pending.resolve({ work: preview.work, record: null, control_preview: preview });
await scan;
assert.equal(state.review, null, "A's stale preview must not appear for B");
assert.equal(env.currentEmployeeRef.current, B);
assert.deepEqual(state.records, []);

// Selecting another employee cancels a review already displayed.
handlers.showControlReview(preview, B, env.scanSequenceRef.current);
assert.equal(state.review.employee, B);
handlers.selectEmployee(A);
assert.equal(state.review, null);
assert.equal(env.controlReviewRef.current, null);

// While confirmation is in flight, employee changes are rejected.
handlers.showControlReview(preview, A, env.scanSequenceRef.current);
pending = deferred();
const confirmation = handlers.confirmControlReview();
assert.equal(calls.at(-1).body.employee_id, 1);
assert.equal(handlers.selectEmployee(B), false);
assert.equal(state.employee, A);
assert.equal(state.review.employee, A);
pending.resolve({ id: 5, status: "recorded" });
await confirmation;
assert.equal(state.records[0].employeeId, 1);
assert.equal(state.review, null);

// A cancelled backend result cannot enter the credited local history.
state.records = [];
handlers.showControlReview(preview, A, env.scanSequenceRef.current);
pending = deferred();
const voidedConfirmation = handlers.confirmControlReview();
pending.resolve({ id: 5, status: "voided", duplicate: true });
await voidedConfirmation;
assert.deepEqual(state.records, []);
assert.equal(state.error, "Confirmation failed");
assert(state.review);
console.log("PASS: delayed numeric Control response, employee review invalidation, confirmation employee lock, and cancelled result guard.");
