// Execute the actual scanner handlers with deferred APIs to verify employee races.
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/payroll/scan/page.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = ["selectEmployee", "showControlReview", "recordNumericWorkScan", "confirmControlReview", "showSessionRecord"];
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
let sessionIds = new Set();
const env = {
  employeeSessionRef: { current: 0 }, lastScanRef: { current: null },
  setShowAllHistory() {}, setSessionRecordIds: value => { sessionIds = typeof value === "function" ? value(sessionIds) : value; },
  controlConfirmRef: { current: false }, scanSequenceRef: { current: 1 },
  controlReviewRef: { current: null }, currentEmployeeRef: { current: A },
  recordsRef: { current: [] }, workRecordByKeyRef: { current: new Map() },
  canSavePayroll: true, lang: "en", inputRef: { current: { focus() {} } },
  api: { post: (path, body) => { calls.push({ path, body }); return pending.promise; } },
  normalizeScanPayload: value => value, buildWorkKey: work => work.label_id,
  setControlReview: value => { state.review = value; }, setCurrentEmployee: value => { state.employee = value; },
  setControlError: value => { state.error = value; }, setControlBusy() {},
  setNotice: value => { state.notices.push(value); },
  controlScanMessages: { en: { pending: "Review pending", error: "Confirmation failed" } },
  t: value => value, numberOrZero: Number,
  toPayrollRecord: (employee, work) => ({ id: work.label_id, employeeId: employee.employee_id, employeeName: employee.employee_name, quantity: work.quantity }),
  replaceRecords: records => { state.records = records; env.recordsRef.current = records; }, payrollScanRecordMatchesLabel: () => false,
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

// Each selection is a fresh view, including A -> B -> A and selecting A again.
handlers.selectEmployee(A);
handlers.showSessionRecord({ id: "a-first", employeeId: 1 }, env.employeeSessionRef.current);
assert.deepEqual([...sessionIds], ["a-first"]);
const previousSession = env.employeeSessionRef.current;
handlers.selectEmployee(B);
assert.equal(sessionIds.size, 0);
handlers.showSessionRecord({ id: "b-new", employeeId: 2 }, env.employeeSessionRef.current);
handlers.selectEmployee(A);
assert.equal(sessionIds.size, 0);
handlers.showSessionRecord({ id: "a-late", employeeId: 1 }, previousSession);
assert.equal(sessionIds.size, 0, "a late response from A's earlier session must stay hidden");
handlers.showSessionRecord({ id: "a-new", employeeId: 1 }, env.employeeSessionRef.current);
assert.deepEqual([...sessionIds], ["a-new"]);
handlers.selectEmployee(A);
assert.equal(sessionIds.size, 0);

// In-flight numeric work remains saved under A, without filling B's fresh view.
pending = deferred();
const lateWork = handlers.recordNumericWorkScan("200000002", A, env.scanSequenceRef.current);
handlers.selectEmployee(B);
const noticesBefore = state.notices.length;
pending.resolve({ work: { type: "process_payroll", label_id: "WORK-2", quantity: 8 }, record: { id: 8, status: "recorded" } });
await lateWork;
assert.equal(state.records[0].employeeId, 1);
assert.equal(state.records[0].saveStatus, "saved");
assert.equal(sessionIds.size, 0);
assert.equal(state.notices.length, noticesBefore);
handlers.selectEmployee(A);
assert.equal(sessionIds.size, 0, "reselecting A must not rehydrate saved work");
assert(state.records.some(record => record.backendId === 8), "saved work must remain in recovery/duplicate history");
console.log("PASS: fresh A/B/A sessions, same employee reselection, and delayed saved responses preserve payroll without restoring old history.");
