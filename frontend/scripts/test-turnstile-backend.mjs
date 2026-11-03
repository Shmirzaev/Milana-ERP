import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

class ApiError extends Error { constructor(status) { super(); this.status = status; } }
let response = {}; let failure;
const calls = [];
const api = {
  postForm: async (url, body) => { calls.push({ url, body }); return { id: 7 }; },
  postWithHeaders: async (url, body, headers) => { calls.push({ url, body, headers }); if (failure) throw failure; return response; },
  getWithHeaders: async (url, headers) => { calls.push({ url, headers, method: "GET" }); return response; },
  get: async url => { calls.push({ url }); return {}; },
  post: async url => { calls.push({ url }); return {}; },
};
const source = fs.readFileSync(new URL("../src/components/hr/turnstile/turnstileBackend.ts", import.meta.url), "utf8");
const js = ts.transpile(source, { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS });
const previewSource = fs.readFileSync(new URL("../src/components/hr/turnstile/turnstilePreview.ts", import.meta.url), "utf8");
const preview = {};
new Function("exports", ts.transpile(previewSource, { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS }))(preview);
const out = {};
new Function("exports", "require", js)(out, name => { if (name === "./turnstilePreview") return preview; if (name === "@/lib/api") return { api }; if (name === "@/lib/errorMessages") return { ApiError }; throw new Error(name); });
const blob = new Blob(["test"], { type: "image/jpeg" });
await out.uploadPhoto(4, blob);
assert.equal(calls[0].url, "/api/turnstile-access/employees/4/photos");
assert.equal(await calls[0].body.get("file").text(), "test");
assert.equal(calls[0].body.get("file").name, "photo.jpg");
await out.uploadPhoto(4, new Blob(["png"], { type: "image/png" }));
assert.equal(calls.pop().body.get("file").name, "photo.png");
const payload = { expected_employee_no: "EMP-4", device_ids: [2], photo_asset_id: 7, reviewed_name: "Test", manual_face_reviewed: true, action: "enroll" };
await out.enroll(4, payload, "stable-key");
await out.enroll(4, payload, "stable-key");
assert.deepEqual(calls[1], calls[2]);
assert.equal(calls[1].headers["Idempotency-Key"], "stable-key");
await out.getOperation(12); await out.processOperation(12); await out.reconnectOperation(12);
assert.deepEqual(calls.slice(3).map(c => c.url), ["/api/turnstile-access/operations/12", "/api/turnstile-access/operations/12/simulate", "/api/turnstile-access/operations/12/simulator-reconnect"]);
const projected = out.projectOperation({ id: 12, action: "enroll", created_at: "2026-01-01", full_name: "Test", targets: [{ device_id: 2, device_name: "North", state: "waiting" }, { device_id: 3, device_name: "Former terminal", state: "uncertain" }] });
assert.deepEqual(projected.targets, [{ deviceId: 2, name: "North", state: "waiting" }, { deviceId: 3, name: "Former terminal", state: "uncertain" }]);
console.log("turnstile backend bridge tests passed");

const request = { key: "stable-key", payload };
response = { id: 12, external_person_id: "EMP-4", action: "enroll", mode: "simulator", photo_asset_id: 7, full_name: "Test", targets: [{ device_id: 2 }] };
assert.equal((await out.submitEnrollment(4, request)).kind, "accepted");
for (const status of [400, 401, 403, 404, 409, 413, 415, 422]) {
  failure = new ApiError(status);
  assert.deepEqual(await out.submitEnrollment(4, request), { kind: "refused", status });
}
for (const error of [new ApiError(500), new ApiError(504), new TypeError("network")]) {
  failure = error;
  assert.equal((await out.submitEnrollment(4, request)).kind, "unknown");
}
failure = undefined;
assert.equal(out.findAcceptedOperation([response], request), undefined);
assert.equal(out.findAcceptedOperation([response], { ...request, acceptedId: 12 })?.id, 12);
assert.equal(out.findAcceptedOperation([response], { ...request, acceptedId: 13 }), undefined);
assert.equal(out.findAcceptedOperation([response], { ...request, payload: { ...payload, device_ids: [3] }, acceptedId: 12 }), undefined);

// Exercise the component's real submission handler with controlled async outcomes.
const component = fs.readFileSync(new URL("../src/components/hr/turnstile/TurnstileAccessPreview.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("TurnstileAccessPreview.tsx", component, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let handler;
function visit(node) { if (ts.isFunctionDeclaration(node) && node.name?.text === "retryPending") handler = node.getText(ast); ts.forEachChild(node, visit); }
visit(ast); assert(handler);
const handlerJs = ts.transpile(handler, { target: ts.ScriptTarget.ES2020 });
async function runHandler(outcome, { refreshFails = false, verifyFirst = false, operations = [], receipt = null, mounted = true, savedRequest = request } = {}) {
  const events = [], journal = new Map([["key", JSON.stringify(savedRequest)]]);
  const env = { running: { current: false }, mounted: { current: mounted }, setBusy: v => events.push(["busy", v]), setMessage: v => events.push(["message", v]),
    context: { mutate: async () => { if (refreshFails) throw new Error("offline"); return { operations }; } },
    lookupRequest: async (employeeId, saved) => { events.push(["lookup", employeeId, saved.key]); return receipt; }, setRecoveryBlocked: v => events.push(["blocked", v]),
    findAcceptedOperation: out.findAcceptedOperation, removeMatchingJournal: out.removeMatchingJournal, markJournalAccepted: out.markJournalAccepted, submitEnrollment: async () => { events.push(["post"]); return outcome; }, employee: { id: 4 },
    sessionStorage: { getItem: k => journal.get(k) ?? null, setItem: (k, v) => journal.set(k, v), removeItem: k => journal.delete(k) }, recoveryKey: "key", clearPending: () => { events.push(["clear"]); journal.delete("key"); },
    setAccepted: op => events.push(["accepted", op.id]), setResultId: id => events.push(["result", id]), setConfirm: () => {}, focusWithin: () => {},
    b: { uncertain: "unknown", refused: "refused", refreshFailed: "refresh failed" } };
  const fn = new Function(...Object.keys(env), `${handlerJs}; return retryPending;`)(...Object.values(env));
  await fn(savedRequest, verifyFirst); return { events, journal };
}
const refusal = await runHandler({ kind: "refused", status: 409 });
assert(refusal.events.some(e => e[0] === "clear"));
assert(refusal.events.some(e => e[1] === "refused"));
const unknown = await runHandler({ kind: "unknown" });
assert(unknown.journal.has("key")); assert(!unknown.events.some(e => e[0] === "clear"));
const acceptedRefreshFailure = await runHandler({ kind: "accepted", operation: response }, { refreshFails: true });
assert(acceptedRefreshFailure.events.some(e => e[0] === "accepted" && e[1] === 12));
assert(acceptedRefreshFailure.events.some(e => e[1] === "refresh failed"));
assert(!acceptedRefreshFailure.events.some(e => e[1] === "unknown"));
const recovered = await runHandler({ kind: "unknown" }, { verifyFirst: true, operations: [response], receipt: response });
assert(!recovered.events.some(e => e[0] === "post")); assert(recovered.events.some(e => e[0] === "accepted"));
const retryRefused = await runHandler({ kind: "refused", status: 403 }, { verifyFirst: true, operations: [response], receipt: null });
assert(retryRefused.events.some(e => e[0] === "post")); assert(retryRefused.journal.has("key"));
assert(!retryRefused.events.some(e => e[0] === "clear"));
assert(retryRefused.events.some(e => e[1] === "unknown"));
const wrongReceipt = await runHandler({ kind: "unknown" }, { verifyFirst: true, receipt: response, savedRequest: { ...request, acceptedId: 13 } });
assert(wrongReceipt.journal.has("key")); assert(wrongReceipt.events.some(e => e[0] === "blocked")); assert(!wrongReceipt.events.some(e => e[0] === "post" || e[0] === "accepted"));
const closed = await runHandler({ kind: "accepted", operation: response }, { mounted: false });
assert.equal(JSON.parse(closed.journal.get("key")).acceptedId, 12);
console.log("turnstile refusal and recovery tests passed");

const newer = new Map([["key", JSON.stringify({ key: "new-request" })]]);
const storage = { getItem: key => newer.get(key) ?? null, setItem: (key, value) => newer.set(key, value), removeItem: key => newer.delete(key) };
assert.equal(out.markJournalAccepted(storage, "key", request, 12), false);
assert.equal(out.removeMatchingJournal(storage, "key", "old-request"), false);
assert(newer.has("key"));
assert.equal(out.removeMatchingJournal(storage, "key", "new-request"), true);
assert(!newer.has("key"));

let applyHandler;
function findApply(node) { if (ts.isFunctionDeclaration(node) && node.name?.text === "backendApply") applyHandler = node.getText(ast); ts.forEachChild(node, findApply); }
findApply(ast); assert(applyHandler);
const applyJs = ts.transpile(applyHandler, { target: ts.ScriptTarget.ES2020 });
const driftEvents = [];
const driftEnv = { action: preview.GateAction.Enroll, GateAction: preview.GateAction, confirm: true, blocked: false, photo: { blob }, checks: [true, true], targetDevices: [{ id: 2 }], reviewedNumber: "EMP-4", employeeNumber: "EMP-NEW", setConfirm: value => driftEvents.push(["confirm", value]), setMessage: value => driftEvents.push(["message", value]), b: { identityChanged: "changed" } };
const applyDrift = new Function(...Object.keys(driftEnv), `${applyJs}; return backendApply;`)(...Object.values(driftEnv));
await applyDrift();
assert.deepEqual(driftEvents, [["confirm", false], ["message", "changed"]]);
console.log("turnstile reviewed identity drift test passed");

assert.equal(out.findAcceptedOperation([{ ...response, external_person_id: "OTHER-NUMBER" }], request), undefined);

const hash = "a".repeat(64);
const editRequest = { key: "edit-key", payload: { expected_employee_no: "EMP-4", reviewed_name: "New Name", action: preview.GateAction.Edit, targets: [{ device_id: 2, expected_revision: 3, expected_profile_hash: hash }] } };
const editReceipt = { ...response, action: preview.GateAction.Edit, full_name: "New Name", photo_asset_id: null, targets: [{ device_id: 2, baseline_revision: 3, baseline_profile_hash: hash }] };
assert(out.validRequest(request)); assert(out.validRequest(editRequest));
assert(!out.validRequest({ ...editRequest, payload: { ...editRequest.payload, action: "EDIT" } }));
assert(!out.validRequest({ ...editRequest, payload: { ...editRequest.payload, targets: [{ ...editRequest.payload.targets[0], expected_profile_hash: "bad" }] } }));
response = editReceipt;
assert.equal((await out.submitEnrollment(4, editRequest)).kind, "accepted");
assert.equal(calls.at(-1).url, "/api/turnstile-access/employees/4/edit");
assert.equal(calls.at(-1).headers["Idempotency-Key"], "edit-key");
assert.equal(out.findAcceptedOperation([editReceipt], editRequest), undefined);
assert.equal(out.findAcceptedOperation([editReceipt], { ...editRequest, acceptedId: 12 })?.id, 12);
assert.equal(out.findAcceptedOperation([{ ...editReceipt, targets: [{ ...editReceipt.targets[0], baseline_revision: 4 }] }], { ...editRequest, acceptedId: 12 }), undefined);
assert.equal(out.findAcceptedOperation([{ ...editReceipt, targets: [{ ...editReceipt.targets[0], baseline_profile_hash: "b".repeat(64) }] }], { ...editRequest, acceptedId: 12 }), undefined);
failure = new TypeError("lost response"); assert.equal((await out.submitEnrollment(4, editRequest)).kind, "unknown"); failure = undefined;
console.log("turnstile edit bridge tests passed");

const staleEvents = [];
const staleEnv = { action: preview.GateAction.Edit, GateAction: preview.GateAction, confirm: true, blocked: false, targetDevices: [{ id: 2 }], reviewedTargets: editRequest.payload.targets, context: { data: { bindings: [{ device_id: 2, state: "active", edit_baseline: { revision: 4, profile_hash: hash } }] } }, setConfirm: v => staleEvents.push(["confirm", v]), setMessage: v => staleEvents.push(["message", v]), b: { staleBaseline: "stale" } };
await new Function(...Object.keys(staleEnv), `${applyJs}; return backendApply;`)(...Object.values(staleEnv))();
assert.deepEqual(staleEvents, [["confirm", false], ["message", "stale"]]);
console.log("turnstile stale baseline refusal test passed");

response = editReceipt;
assert.equal(await out.lookupRequest(4, editRequest), editReceipt);
assert.deepEqual(calls.at(-1), { method: "GET", url: "/api/turnstile-access/employees/4/requests/edit", headers: { "Idempotency-Key": "edit-key" } });
await out.lookupRequest(9, request);
assert.deepEqual(calls.at(-1), { method: "GET", url: "/api/turnstile-access/employees/9/requests/enroll", headers: { "Idempotency-Key": "stable-key" } });
const recoveredEdit = await runHandler({ kind: "unknown" }, { verifyFirst: true, receipt: editReceipt, savedRequest: editRequest });
assert(recoveredEdit.events.some(e => e[0] === "accepted" && e[1] === 12)); assert(!recoveredEdit.events.some(e => e[0] === "post"));
console.log("turnstile authoritative receipt lookup tests passed");

let recheckHandler;
function findRecheck(node) { if (ts.isFunctionDeclaration(node) && node.name?.text === "recheck") recheckHandler = node.getText(ast); ts.forEachChild(node, findRecheck); }
findRecheck(ast); assert(recheckHandler);
const recheckEvents = [];
const recheckEnv = { setBusy: v => recheckEvents.push(["busy", v]), context: { mutate: async () => ({ operations: [response] }) }, pending: request, lookupRequest: async () => { recheckEvents.push(["lookup"]); return null; }, employee: { id: 4 }, findAcceptedOperation: out.findAcceptedOperation, setRecoveryBlocked: () => {}, setMessage: () => {}, setAccepted: () => recheckEvents.push(["accepted"]), setResultId: () => {}, clearPending: () => recheckEvents.push(["clear"]), setConfirm: () => {}, latest: null, getOperation: async () => {}, b: { failed: "failed" } };
await new Function(...Object.keys(recheckEnv), `${ts.transpile(recheckHandler, { target: ts.ScriptTarget.ES2020 })}; return recheck;`)(...Object.values(recheckEnv))();
assert(recheckEvents.some(e => e[0] === "lookup")); assert(!recheckEvents.some(e => e[0] === "clear" || e[0] === "accepted"));
// Evaluate the component's real blocked expression with the retained pending request.
let blockedExpression;
function findBlocked(node) { if (ts.isVariableDeclaration(node) && node.name.getText(ast) === "blocked") blockedExpression = node.initializer.getText(ast); ts.forEachChild(node, findBlocked); }
findBlocked(ast); assert(blockedExpression);
const isBlocked = new Function("canManage", "BACKEND_ENABLED", "context", "action", "busy", "pending", "recoveryBlocked", "employeeNumber", "employee", "GateAction", `return ${blockedExpression};`);
assert.equal(isBlocked(true, true, { data: { simulator_enabled: true, supported_actions: [preview.GateAction.Enroll] } }, preview.GateAction.Enroll, false, JSON.parse(retryRefused.journal.get("key")), false, "EMP-4", { status: "active" }, preview.GateAction), true);
const laterReceipt = await runHandler({ kind: "unknown" }, { verifyFirst: true, receipt: { ...response, action: "enroll", full_name: "Test", photo_asset_id: 7, targets: [{ device_id: 2 }] }, savedRequest: JSON.parse(retryRefused.journal.get("key")) });
assert(laterReceipt.events.some(e => e[0] === "accepted")); assert(!laterReceipt.journal.has("key")); assert(!laterReceipt.events.some(e => e[0] === "post"));
console.log("turnstile readonly null recheck test passed");
