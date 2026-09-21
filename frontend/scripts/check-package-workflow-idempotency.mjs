import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/packageWorkflow.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const storage = new Map();
const calls = [];
const events = [];
let failure = null;
let response = { ok: true };
let postHandler = null;
let seq = 0;
const context = {
  exports: {}, crypto: { randomUUID: () => `request-${++seq}` },
  Event: class { constructor(type) { this.type = type; } },
  window: { dispatchEvent: event => events.push(event.type) },
  sessionStorage: { getItem: key => storage.get(key) || null, setItem: (key, val) => storage.set(key, val), removeItem: key => storage.delete(key) },
  require: () => ({ api: { post: async (url, body) => { calls.push({ url, body }); if (postHandler) return postHandler(url, body); if (failure) throw Error(failure); return response; } } }),
};
vm.runInNewContext(code, context);
const { postPackageWorkflow, pendingPackageWorkflow, reconcilePendingPackageWorkflow, packageWorkflowCopy } = context.exports;
(async () => {
  const url = "/api/packages/manual-receipt";
  const body = { model_id: 3, count: 6, sizes: [{ size: "M", quantity: 4 }] };
  failure = "Network timeout";
  const firstPendingEvent = events.length;
  await assert.rejects(postPackageWorkflow(url, body, 7));
  assert.equal(events.length, firstPendingEvent + 1, "saving uncertain evidence must notify pending-request listeners");
  const key = calls[0].body.request_key;
  assert.equal(pendingPackageWorkflow(url, 7).body.count, 6);
  const unchangedEventCount = events.length;
  await assert.rejects(postPackageWorkflow(url, { ...body, count: 4 }, 7), /saved package request/);
  assert.equal(calls.length, 1, "editing must not issue another request");
  assert.equal(events.length, unchangedEventCount, "unchanged pending evidence must not emit a false UI update");
  failure = null;
  await postPackageWorkflow(url, pendingPackageWorkflow(url, 7).body, 7);
  assert.equal(calls[1].body.request_key, key);
  assert.equal(pendingPackageWorkflow(url, 7), null);
  assert.equal(events.length, unchangedEventCount + 1, "clearing confirmed evidence must notify pending-request listeners");
  await postPackageWorkflow(url, { ...body, count: 4 }, 7);
  assert.notEqual(calls[2].body.request_key, key);
  failure = "500: uncertain server failure";
  await assert.rejects(postPackageWorkflow(url, body, 7));
  assert.ok(pendingPackageWorkflow(url, 7));
  failure = null;
  await postPackageWorkflow(url, body, 8);
  assert.ok(pendingPackageWorkflow(url, 7), "another user's request must not clear the first");
  failure = "422: invalid sizes";
  const retainedEventCount = events.length;
  await assert.rejects(postPackageWorkflow(url, body, 7));
  assert.ok(pendingPackageWorkflow(url, 7), "a later rejection cannot clear an earlier uncertain result");
  assert.equal(events.length, retainedEventCount, "retained uncertain evidence must not emit a false UI update");
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

  failure = "Network timeout";
  await assert.rejects(postPackageWorkflow(url, body, 10));
  await assert.rejects(reconcilePendingPackageWorkflow(url, 10));
  assert.ok(pendingPackageWorkflow(url, 10), "failed reconciliation must retain pending state");
  failure = "The saved receipt is no longer active";
  await assert.rejects(reconcilePendingPackageWorkflow(url, 10));
  assert.ok(pendingPackageWorkflow(url, 10), "an inactive completed receipt must remain pending for operator review");
  failure = null;
  response = { status: "cancelled" };
  assert.equal((await reconcilePendingPackageWorkflow(url, 10)).status, "cancelled");
  assert.equal(pendingPackageWorkflow(url, 10), null, "server cancellation safely releases pending state");

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
    const originalKey = pendingPackageWorkflow(url, userId).requestKey;
    assert.equal((await reconcilePendingPackageWorkflow(url, userId)).status, "cancelled");
    const newerBody = { ...body, count: 4 };
    const newerRequest = postPackageWorkflow(url, newerBody, userId);
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
  await assert.rejects(reconcilePendingPackageWorkflow("/api/packages/print-runs", 12), /Only manual receipts/);
  response = { status: "completed" };
  await assert.rejects(reconcilePendingPackageWorkflow(url, 12), /invalid status/);
  assert.ok(pendingPackageWorkflow(url, 12), "missing completed result must retain pending evidence");
  for (const lang of ["ru", "uz"]) assert.deepEqual(Object.keys(packageWorkflowCopy[lang]).sort(), Object.keys(packageWorkflowCopy.en).sort());
  console.log("Package request identity, uncertain retry, user isolation, and locale tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
