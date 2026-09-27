import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/payroll/scan/page.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const functions = [];
let searchSelection;
function visit(node) {
  if (ts.isFunctionDeclaration(node) && ["submitScan", "processScan", "selectEmployee", "enqueueScanAction"].includes(node.name?.text)) {
    functions.push(node.getText(ast));
  }
  if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(ast) === "PayrollEmployeeSearch") {
    const onSelect = node.attributes.properties.find(attribute => ts.isJsxAttribute(attribute) && attribute.name.text === "onSelect");
    searchSelection = onSelect?.initializer?.expression?.getText(ast);
  }
  ts.forEachChild(node, visit);
}
visit(ast);
assert(searchSelection, "execute the actual manual employee selection handler");
const handlersJs = ts.transpile(`${functions.join("\n")}\nconst selectFromSearch = ${searchSelection};`, { target: ts.ScriptTarget.ES2020 });
const employeeA = { employee_id: 1, employee_name: "A" };
const employeeB = { type: "employee_payroll", employee_id: 2, employee_name: "B" };
const employeeC = { employee_id: 3, employee_name: "C" };
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const nextTurn = () => new Promise(resolve => setTimeout(resolve, 0));

function scanner({ lookup = () => Promise.reject(new Error("no employee selected")), save = async () => {} } = {}) {
  const writes = [], notices = [];
  const refs = {
    inputRef: { current: { value: "" } }, currentEmployeeRef: { current: employeeA },
    controlReviewRef: { current: null }, lastScanRef: { current: null }, scanSequenceRef: { current: 0 },
    scanQueueRef: { current: Promise.resolve() }, controlConfirmRef: { current: false },
  };
  const env = {
    ...refs, canSavePayroll: true, clearAutoSubmitTimer() {},
    clearScanInput: () => { refs.inputRef.current.value = ""; },
    setNotice: (...args) => notices.push(args), t: key => key, lang: "en", setCurrentEmployee() {},
    setControlReview() {}, setControlError() {}, resolveScanPayload: lookup,
    recordNumericWorkScan: async (raw, employee) => {
      writes.push({ raw, id: employee.employee_id });
      await save(raw, employee);
    },
    parseScanPayload: () => { throw new Error("numeric badge"); },
  };
  const handlers = new Function(...Object.keys(env), `${handlersJs}; return {submitScan, selectFromSearch};`)(...Object.values(env));
  return {
    refs, writes, notices, select: handlers.selectFromSearch,
    scan(raw) {
      refs.inputRef.current.value = raw;
      return handlers.submitScan();
    },
    drain: () => refs.scanQueueRef.current,
  };
}

async function badgeBeforeWork(failLookup = false) {
  const badge = deferred();
  const session = scanner({ lookup: raw => raw.startsWith("1") ? badge.promise : Promise.reject(new Error("no employee selected")) });
  const first = session.scan("100000002");
  const second = session.scan("200000009");
  await nextTurn();
  assert.equal(session.writes.length, 0, "work must wait while the preceding employee badge resolves");
  if (failLookup) badge.reject(new Error("employee lookup failed"));
  else badge.resolve(employeeB);
  await Promise.all([first, second]);
  assert.deepEqual(session.writes, failLookup ? [] : [{ raw: "200000009", id: 2 }]);
}

async function manualSelectionAfterQueuedWork() {
  const firstSave = deferred();
  const session = scanner({ save: raw => raw === "200000001" ? firstSave.promise : Promise.resolve() });
  const first = session.scan("200000001");
  await nextTurn();
  const second = session.scan("200000002");
  session.select(employeeB);
  const third = session.scan("200000003");
  firstSave.resolve();
  await Promise.all([first, second, third]);
  assert.deepEqual(session.writes, [
    { raw: "200000001", id: 1 },
    { raw: "200000002", id: 1 },
    { raw: "200000003", id: 2 },
  ], "manual selection must affect later scans, never work already queued for A");
  assert.equal(session.refs.currentEmployeeRef.current, employeeB);
}

async function queuedBadgeThenManualSelection() {
  const firstSave = deferred();
  const badge = deferred();
  const session = scanner({ lookup: () => badge.promise, save: raw => raw === "200000001" ? firstSave.promise : Promise.resolve() });
  const first = session.scan("200000001");
  await nextTurn();
  const employeeScan = session.scan("100000002");
  const second = session.scan("200000002");
  session.select(employeeC);
  const third = session.scan("200000003");
  firstSave.resolve();
  await nextTurn();
  assert.equal(session.writes.length, 1, "work after a queued badge must wait for its lookup");
  badge.resolve(employeeB);
  await Promise.all([first, employeeScan, second, third]);
  assert.deepEqual(session.writes, [
    { raw: "200000001", id: 1 },
    { raw: "200000002", id: 2 },
    { raw: "200000003", id: 3 },
  ], "a previously queued badge must not overwrite the later manual selection");
}

async function manualSelectionDuringBadgeLookup(failLookup = false) {
  const badge = deferred();
  const session = scanner({ lookup: () => badge.promise });
  const employeeScan = session.scan("100000002");
  await nextTurn();
  session.select(employeeC);
  const workScan = session.scan("200000001");
  if (failLookup) badge.reject(new Error("employee lookup failed"));
  else badge.resolve(employeeB);
  await Promise.all([employeeScan, workScan]);
  assert.deepEqual(session.writes, [{ raw: "200000001", id: 3 }]);
  assert.equal(session.refs.currentEmployeeRef.current, employeeC);
}

async function failedSaveKeepsSelectionOrder() {
  const firstSave = deferred();
  const session = scanner({ save: raw => raw === "200000001" ? firstSave.promise : Promise.resolve() });
  const first = session.scan("200000001");
  await nextTurn();
  session.select(employeeB);
  const second = session.scan("200000002");
  firstSave.reject(new Error("save failed"));
  await Promise.all([first, second]);
  assert.deepEqual(session.writes, [{ raw: "200000001", id: 1 }, { raw: "200000002", id: 2 }]);
}

async function manualSelectionRespectsControlConfirmation() {
  const session = scanner();
  session.refs.controlConfirmRef.current = true;
  session.select(employeeB);
  await session.drain();
  assert.equal(session.refs.currentEmployeeRef.current, employeeA);
}

await badgeBeforeWork();
await badgeBeforeWork(true);
await manualSelectionAfterQueuedWork();
await queuedBadgeThenManualSelection();
await manualSelectionDuringBadgeLookup();
await manualSelectionDuringBadgeLookup(true);
await failedSaveKeepsSelectionOrder();
await manualSelectionRespectsControlConfirmation();
console.log("Payroll scan ordering: eight actual-handler cases passed for badges, manual selections, queued work, failures, and Control confirmation.");
