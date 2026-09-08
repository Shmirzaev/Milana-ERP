import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/packageWorkflow.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const storage = new Map();
const calls = [];
let failure = null;
let seq = 0;
const context = {
  exports: {}, crypto: { randomUUID: () => `request-${++seq}` },
  sessionStorage: { getItem: key => storage.get(key) || null, setItem: (key, val) => storage.set(key, val), removeItem: key => storage.delete(key) },
  require: () => ({ api: { post: async (url, body) => { calls.push({ url, body }); if (failure) throw Error(failure); return { ok: true }; } } }),
};
vm.runInNewContext(code, context);
const { postPackageWorkflow, pendingPackageWorkflow, packageWorkflowCopy } = context.exports;
(async () => {
  const url = "/api/packages/manual-receipt";
  const body = { model_id: 3, count: 6, sizes: [{ size: "M", quantity: 4 }] };
  failure = "Network timeout";
  await assert.rejects(postPackageWorkflow(url, body, 7));
  const key = calls[0].body.request_key;
  assert.equal(pendingPackageWorkflow(url, 7).body.count, 6);
  await assert.rejects(postPackageWorkflow(url, { ...body, count: 4 }, 7), /saved package request/);
  assert.equal(calls.length, 1, "editing must not issue another request");
  failure = null;
  await postPackageWorkflow(url, pendingPackageWorkflow(url, 7).body, 7);
  assert.equal(calls[1].body.request_key, key);
  assert.equal(pendingPackageWorkflow(url, 7), null);
  await postPackageWorkflow(url, { ...body, count: 4 }, 7);
  assert.notEqual(calls[2].body.request_key, key);
  failure = "500: uncertain server failure";
  await assert.rejects(postPackageWorkflow(url, body, 7));
  assert.ok(pendingPackageWorkflow(url, 7));
  failure = null;
  await postPackageWorkflow(url, body, 8);
  assert.ok(pendingPackageWorkflow(url, 7), "another user's request must not clear the first");
  failure = "422: invalid sizes";
  await assert.rejects(postPackageWorkflow(url, body, 7));
  assert.ok(pendingPackageWorkflow(url, 7), "a later rejection cannot clear an earlier uncertain result");
  await assert.rejects(postPackageWorkflow(url, body, 9));
  assert.equal(pendingPackageWorkflow(url, 9), null, "a definite first rejection can be corrected");
  for (const lang of ["ru", "uz"]) assert.deepEqual(Object.keys(packageWorkflowCopy[lang]).sort(), Object.keys(packageWorkflowCopy.en).sort());
  console.log("Package request identity, uncertain retry, user isolation, and locale tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
