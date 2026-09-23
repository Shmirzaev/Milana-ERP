import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/packageWorkflow.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const localValues = new Map();
const legacyValues = new Map();
const calls = [];
const events = [];
let failure = null;
let response = { ok: true };
let postHandler = null;
let seq = 0;
const storage = values => ({
  getItem: key => values.get(key) || null,
  setItem: (key, value) => values.set(key, value),
  removeItem: key => values.delete(key),
});
const lockTails = new Map();
const navigator = { locks: { request(key, action) {
  const next = (lockTails.get(key) || Promise.resolve()).catch(() => {}).then(action);
  lockTails.set(key, next);
  return next;
} } };
const context = {
  exports: {}, crypto: { randomUUID: () => `request-${++seq}` },
  Event: class { constructor(type) { this.type = type; } },
  navigator,
  window: {
    dispatchEvent: event => events.push(event.type),
    localStorage: storage(localValues),
    sessionStorage: storage(legacyValues),
  },
  require: () => ({ api: { post: async (url, body) => { calls.push({ url, body }); if (postHandler) return postHandler(url, body); if (failure) throw Error(failure); return response; } } }),
};
vm.runInNewContext(code, context);
const { postPackageWorkflow, pendingPackageWorkflow, reconcilePendingPackageWorkflow, packageWorkflowCopy, packageWorkflowStorageKey } = context.exports;
(async () => {
  const url = "/api/packages/manual-receipt";
  const body = { model_id: 3, count: 6, sizes: [{ size: "M", quantity: 4 }] };
  failure = "Network timeout";
  const firstPendingEvent = events.length;
  await assert.rejects(postPackageWorkflow(url, body, 7));
  assert.equal(events.length, firstPendingEvent + 1, "saving uncertain evidence must notify pending-request listeners");
  const key = calls[0].body.request_key;
  assert.equal(pendingPackageWorkflow(url, 7).body.count, 6);
  const concurrentCallStart = calls.length;
  await Promise.allSettled([
    postPackageWorkflow(url, body, 23),
    postPackageWorkflow(url, body, 23),
  ]);
  const concurrentKeys = calls.slice(concurrentCallStart).map(call => call.body.request_key);
  assert.equal(new Set(concurrentKeys).size, 1, "concurrent tabs must reuse one persisted package request key");
  const unchangedEventCount = events.length;
  const callsBeforeEdit = calls.length;
  await assert.rejects(postPackageWorkflow(url, { ...body, count: 4 }, 7), /saved package request/);
  assert.equal(calls.length, callsBeforeEdit, "editing must not issue another request");
  assert.equal(events.length, unchangedEventCount, "unchanged pending evidence must not emit a false UI update");
  failure = null;
  await postPackageWorkflow(url, pendingPackageWorkflow(url, 7).body, 7);
  assert.equal(calls.at(-1).body.request_key, key);
  assert.equal(pendingPackageWorkflow(url, 7), null);
  assert.equal(events.length, unchangedEventCount + 1, "clearing confirmed evidence must notify pending-request listeners");
  await postPackageWorkflow(url, { ...body, count: 4 }, 7);
  assert.notEqual(calls.at(-1).body.request_key, key);
  failure = "500: uncertain server failure";
  await assert.rejects(postPackageWorkflow(url, body, 7));
  assert.ok(pendingPackageWorkflow(url, 7));
  failure = null;
  await postPackageWorkflow(url, body, 8);
  assert.ok(pendingPackageWorkflow(url, 7), "another user's request must not clear the first");
  failure = "400: invalid sizes";
  const rejectedRetryKey = pendingPackageWorkflow(url, 7).requestKey;
  const rejectedEventCount = events.length;
  await assert.rejects(postPackageWorkflow(url, body, 7));
  assert.equal(pendingPackageWorkflow(url, 7), null, "a serialized business rejection must release the saved request");
  assert.equal(events.length, rejectedEventCount + 1, "rejected retry cleanup must notify pending-request listeners");
  failure = null;
  const correctedRetryBody = { ...body, count: 5 };
  await postPackageWorkflow(url, correctedRetryBody, 7);
  assert.equal(calls.at(-1).body.count, 5);
  assert.notEqual(calls.at(-1).body.request_key, rejectedRetryKey, "corrected values must use a new request key");

  failure = "422: invalid sizes";
  await assert.rejects(postPackageWorkflow(url, body, 9));
  assert.equal(pendingPackageWorkflow(url, 9), null, "a definite first rejection can be corrected");

  failure = "429: Too Many Requests";
  await assert.rejects(postPackageWorkflow(url, body, 14));
  const rateLimitedKey = calls.at(-1).body.request_key;
  assert.equal(pendingPackageWorkflow(url, 14), null, "a rate-limited first request must not block corrected values");
  failure = null;
  const correctedBody = { ...body, count: 4 };
  await postPackageWorkflow(url, correctedBody, 14);
  assert.equal(calls.at(-1).body.count, 4);
  assert.notEqual(calls.at(-1).body.request_key, rateLimitedKey);
  assert.equal(pendingPackageWorkflow(url, 14), null);

  for (const [userId, retryFailure] of [
    [15, "403: permission revoked"],
    [16, "429: Too Many Requests"],
    [17, "410: Some labels in this manual receipt were deleted"],
    [18, "422: request no longer matches the deployed schema"],
  ]) {
    failure = "Network timeout";
    await assert.rejects(postPackageWorkflow(url, body, userId));
    const uncertainKey = pendingPackageWorkflow(url, userId).requestKey;
    failure = retryFailure;
    const ambiguousEventCount = events.length;
    await assert.rejects(postPackageWorkflow(url, body, userId));
    assert.equal(pendingPackageWorkflow(url, userId).requestKey, uncertainKey, `${retryFailure} must retain uncertain evidence`);
    assert.equal(events.length, ambiguousEventCount, `${retryFailure} must not emit a false clear event`);
    failure = null;
    response = { status: "cancelled" };
    assert.equal((await reconcilePendingPackageWorkflow(url, userId)).status, "cancelled");
  }

  failure = "Network timeout";
  await assert.rejects(postPackageWorkflow(url, body, 10));
  await assert.rejects(reconcilePendingPackageWorkflow(url, 10));
  assert.ok(pendingPackageWorkflow(url, 10), "failed reconciliation must retain pending state");
  failure = null;
  response = { status: "completed_unavailable" };
  assert.equal((await reconcilePendingPackageWorkflow(url, 10)).status, "completed_unavailable");
  assert.equal(pendingPackageWorkflow(url, 10), null, "deleted or revoked results safely release pending state without data");

  failure = "Network timeout";
  await assert.rejects(postPackageWorkflow(url, body, 11));
  failure = null;
  response = { status: "completed", result: { receipt_no: "WMR-1" } };
  const completed = await reconcilePendingPackageWorkflow(url, 11);
  assert.equal(completed.result.receipt_no, "WMR-1");
  assert.equal(pendingPackageWorkflow(url, 11), null, "committed reconciliation clears pending state");

  const deferred = () => {
    let resolve; let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
  };
  for (const [userId, lateOutcome] of [[12, "success"], [13, "rejection"]]) {
    const original = deferred();
    const newer = deferred();
    postHandler = (path, request) => path.endsWith("/reconcile")
      ? { status: "cancelled" }
      : request.count === 6 ? original.promise : newer.promise;
    const lateOriginal = postPackageWorkflow(url, body, userId);
    await navigator.locks.request(packageWorkflowStorageKey(url, userId), () => {});
    const originalKey = pendingPackageWorkflow(url, userId).requestKey;
    assert.equal((await reconcilePendingPackageWorkflow(url, userId)).status, "cancelled");
    const newerBody = { ...body, count: 4 };
    const newerRequest = postPackageWorkflow(url, newerBody, userId);
    await navigator.locks.request(packageWorkflowStorageKey(url, userId), () => {});
    const newerKey = pendingPackageWorkflow(url, userId).requestKey;
    assert.notEqual(newerKey, originalKey);
    if (lateOutcome === "success") {
      original.resolve({ ok: true });
      await assert.rejects(lateOriginal, /newer pending package request/);
    } else {
      original.reject(Error("422: late validation rejection"));
      await assert.rejects(lateOriginal);
    }
    assert.equal(pendingPackageWorkflow(url, userId).requestKey, newerKey, "late request A must not erase newer request B");
    newer.reject(Error("Network timeout"));
    await assert.rejects(newerRequest);
    assert.equal(pendingPackageWorkflow(url, userId).requestKey, newerKey);
  }
  postHandler = null;
  const printRunPath = "/api/packages/print-runs";
  failure = "Network timeout";
  await assert.rejects(postPackageWorkflow(printRunPath, { package_ids: [1] }, 19));
  failure = null;
  response = { status: "cancelled" };
  assert.equal((await reconcilePendingPackageWorkflow(printRunPath, 19)).status, "cancelled");
  assert.equal(calls.at(-1).url, "/api/packages/print-runs/reconcile");

  failure = "Network timeout";
  await assert.rejects(postPackageWorkflow(url, body, 20));
  failure = null;
  response = { status: "completed" };
  await assert.rejects(reconcilePendingPackageWorkflow(url, 20), /invalid status/);
  assert.ok(pendingPackageWorkflow(url, 20), "missing completed result must retain pending evidence");

  const legacyPath = "/api/packages/print-runs/create-packages";
  const legacyKey = `package-request:21:${legacyPath}`;
  legacyValues.set(legacyKey, JSON.stringify({ requestKey: "legacy-request", body: { packages: [{ id: 1 }] } }));
  failure = "Network timeout";
  await assert.rejects(postPackageWorkflow(legacyPath, { packages: [{ id: 1 }] }, 21));
  assert.equal(legacyValues.has(legacyKey), false, "legacy tab evidence migrates under the cross-tab lock");
  assert.equal(JSON.parse(localValues.get(legacyKey)).requestKey, "legacy-request");

  const corruptPath = "/api/packages/manual-receipt";
  const corruptKey = `package-request:22:${corruptPath}`;
  localValues.set(corruptKey, "not-json");
  const callsBeforeCorrupt = calls.length;
  await assert.rejects(postPackageWorkflow(corruptPath, body, 22), /invalid/);
  assert.equal(calls.length, callsBeforeCorrupt, "corrupt evidence must fail before minting or sending another key");
  assert.equal(localValues.get(corruptKey), "not-json");
  for (const lang of ["ru", "uz"]) assert.deepEqual(Object.keys(packageWorkflowCopy[lang]).sort(), Object.keys(packageWorkflowCopy.en).sort());
  console.log("Package request identity, cross-tab locking, generic reconciliation, unavailable-result cleanup, legacy migration, and locale tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
