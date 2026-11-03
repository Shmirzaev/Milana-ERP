import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

class ApiError extends Error { constructor(status) { super(); this.status = status; } }
let response = {}; let failure;
const calls = [];
const api = {
  postForm: async (url, body) => { calls.push({ url, body }); return { id: 7 }; },
  postWithHeaders: async (url, body, headers) => { calls.push({ url, body, headers }); if (failure) throw failure; return response; },
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
assert.equal(out.findAcceptedOperation([response], request)?.id, 12);
assert.equal(out.findAcceptedOperation([response], { ...request, acceptedId: 13 }), undefined);
assert.equal(out.findAcceptedOperation([response], { ...request, payload: { ...payload, device_ids: [3] } }), undefined);

// Exercise the component's real submission handler with controlled async outcomes.
const component = fs.readFileSync(new URL("../src/components/hr/turnstile/TurnstileAccessPreview.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("TurnstileAccessPreview.tsx", component, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let handler;
function visit(node) { if (ts.isFunctionDeclaration(node) && node.name?.text === "retryPending") handler = node.getText(ast); ts.forEachChild(node, visit); }
visit(ast); assert(handler);
const handlerJs = ts.transpile(handler, { target: ts.ScriptTarget.ES2020 });
async function runHandler(outcome, { refreshFails = false, verifyFirst = false, operations = [], mounted = true } = {}) {
  const events = [], journal = new Map([["key", JSON.stringify(request)]]);
  const env = { running: { current: false }, mounted: { current: mounted }, setBusy: v => events.push(["busy", v]), setMessage: v => events.push(["message", v]),
    context: { mutate: async () => { if (refreshFails) throw new Error("offline"); return { operations }; } },
    findAcceptedOperation: out.findAcceptedOperation, removeMatchingJournal: out.removeMatchingJournal, markJournalAccepted: out.markJournalAccepted, submitEnrollment: async () => { events.push(["post"]); return outcome; }, employee: { id: 4 },
    sessionStorage: { getItem: k => journal.get(k) ?? null, setItem: (k, v) => journal.set(k, v), removeItem: k => journal.delete(k) }, recoveryKey: "key", clearPending: () => { events.push(["clear"]); journal.delete("key"); },
    setAccepted: op => events.push(["accepted", op.id]), setResultId: id => events.push(["result", id]), setConfirm: () => {}, focusWithin: () => {},
    b: { uncertain: "unknown", refused: "refused", refreshFailed: "refresh failed" } };
  const fn = new Function(...Object.keys(env), `${handlerJs}; return retryPending;`)(...Object.values(env));
  await fn(request, verifyFirst); return { events, journal };
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
const recovered = await runHandler({ kind: "unknown" }, { verifyFirst: true, operations: [response] });
assert(!recovered.events.some(e => e[0] === "post")); assert(recovered.events.some(e => e[0] === "accepted"));
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
const driftEnv = { confirm: true, blocked: false, photo: { blob }, checks: [true, true], targetDevices: [{ id: 2 }], reviewedNumber: "EMP-4", employeeNumber: "EMP-NEW", setConfirm: value => driftEvents.push(["confirm", value]), setMessage: value => driftEvents.push(["message", value]), b: { identityChanged: "changed" } };
const applyDrift = new Function(...Object.keys(driftEnv), `${applyJs}; return backendApply;`)(...Object.values(driftEnv));
await applyDrift();
assert.deepEqual(driftEvents, [["confirm", false], ["message", "changed"]]);
console.log("turnstile reviewed identity drift test passed");

assert.equal(out.findAcceptedOperation([{ ...response, external_person_id: "OTHER-NUMBER" }], request), undefined);
