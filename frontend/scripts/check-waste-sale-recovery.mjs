import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/wasteSaleRecovery.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const storage = new Map();
const calls = [];
let failure = null;
let sequence = 0;
const context = {
  exports: {},
  crypto: { randomUUID: () => `sale-${++sequence}` },
  sessionStorage: {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
  },
  require: () => ({ api: { postWithIdempotency: async (...args) => {
    calls.push(args);
    if (failure) throw new Error(failure);
    return { id: 1 };
  } } }),
};
vm.runInNewContext(code, context);
const { pendingWasteSale, postWasteSale } = context.exports;

const payload = { buyer_name: "Factory recycler", quantity: 4.25, unit_price: 2.5 };
failure = "Backend is not responding";
await assert.rejects(postWasteSale(7, 11, payload));
const first = pendingWasteSale(7, 11);
assert.equal(first.key, "sale-1");
assert.deepEqual(JSON.parse(JSON.stringify(first.payload)), payload);
assert.equal(calls[0][0], "/api/waste/11/sell");
assert.equal(calls[0][2], "sale-1");

await assert.rejects(postWasteSale(7, 11, { ...payload, quantity: 3 }), /saved waste sale/);
assert.equal(calls.length, 1, "edited retry must not create a second sale request");
assert.equal(pendingWasteSale(8, 11), null, "pending sales must be user scoped");
assert.equal(pendingWasteSale(7, 12), null, "pending sales must be waste-record scoped");

failure = "422: changed values rejected";
await assert.rejects(postWasteSale(7, 11, payload));
assert.equal(pendingWasteSale(7, 11).key, "sale-1", "later rejection cannot erase uncertain evidence");
failure = null;
await postWasteSale(7, 11, payload);
assert.equal(calls.at(-1)[2], "sale-1", "retry must reuse the original idempotency key");
assert.equal(pendingWasteSale(7, 11), null);

failure = "400: sale quantity exceeds remaining waste quantity";
await assert.rejects(postWasteSale(7, 11, payload));
assert.equal(pendingWasteSale(7, 11), null, "first definitive rejection is safe to clear");

storage.set("waste-sale:7:13", "{broken");
assert.throws(() => pendingWasteSale(7, 13), /evidence is unreadable/);
await assert.rejects(postWasteSale(7, 13, payload), /evidence is unreadable/);
assert.equal(calls.length, 4, "corrupt evidence must fail before sending");
storage.set("waste-sale:7:14", JSON.stringify({ version: 1, key: "sale-bad", payload: { ...payload, quantity: null } }));
assert.throws(() => pendingWasteSale(7, 14), /evidence is unreadable/, "non-finite persisted fields must fail closed");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function walk(node, predicate, found = []) {
  if (!node || typeof node !== "object") return found;
  if (predicate(node)) found.push(node);
  const children = node.props?.children;
  for (const child of Array.isArray(children) ? children : [children]) walk(child, predicate, found);
  return found;
}

function pageHarness({ confirmPromise, refreshFailure = false, storageFailure = false } = {}) {
  const initial = [
    { item_id: 0, source_department_id: 0, waste_type: "fabric", quantity: "", unit: "kg", reason: "", sellable: true },
    "",
    { wasteId: 11, buyer: "Factory recycler", quantity: "4.25", unitPrice: "2.5" },
    null,
    new Set([11]),
  ];
  const updates = initial.map(() => []);
  let stateIndex = 0;
  const submissionRef = { current: false };
  const asks = [];
  const posts = [];
  const pageSource = fs.readFileSync(new URL("../src/app/(app)/waste/page.tsx", import.meta.url), "utf8");
  const pageCode = ts.transpileModule(pageSource, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const pageExports = {};
  const reactHooks = {
    ...React,
    useState(value) {
      const index = stateIndex++;
      const current = initial[index] ?? (typeof value === "function" ? value() : value);
      return [current, update => updates[index].push(typeof update === "function" ? update(current) : update)];
    },
    useEffect(effect) { effect(); },
    useRef() { return submissionRef; },
  };
  new Function("exports", "require", pageCode)(pageExports, name => ({
    react: reactHooks,
    "react/jsx-runtime": jsxRuntime,
    swr: { default: key => key === "/api/waste"
      ? { data: [{ id: 11, waste_type: "offcuts", quantity: 10, unit: "kg", sellable: true, status: "sold", estimated_value: 1 }], mutate: async () => { if (refreshFailure) throw new Error("refresh failed"); } }
      : { data: undefined } },
    "@/lib/api": { api: { post: async () => ({}) }, fetcher() {} },
    "@/components/PageHeader": { default: () => null },
    "@/components/StagePipeline": { statusLabel: value => value },
    "@/lib/i18n": { useT: () => ({ t: key => key }) },
    "@/components/DialogProvider": { useDialogs: () => ({ ask: async (...args) => { asks.push(args); return confirmPromise ? confirmPromise.promise : true; } }) },
    "@/lib/numberInput": { numberOrZero: Number, parseNumberInput: value => value },
    "@/lib/auth": { useMe: () => ({ me: { id: 7 } }) },
    "@/lib/wasteSaleRecovery": {
      pendingWasteSale: () => {
        if (storageFailure) throw new Error("Saved waste sale evidence is unreadable; do not submit another sale");
        return { version: 1, key: "sale-1", payload };
      },
      postWasteSale: async (...args) => { posts.push(args); return { id: 1 }; },
    },
  })[name] ?? (() => { throw new Error(`Unexpected dependency: ${name}`); })());
  const tree = pageExports.default();
  return { tree, updates, submissionRef, asks, posts };
}

const confirmation = deferred();
const overlap = pageHarness({ confirmPromise: confirmation, refreshFailure: true });
assert.ok(walk(overlap.tree, node => node.type === "button" && node.props.children === "page.waste.retrySale").length,
  "a sold row with pending evidence must expose exact replay");
const saleForm = walk(overlap.tree, node => node.type === "form" && String(node.props.className).includes("min-w-64"))[0];
const firstSubmit = saleForm.props.onSubmit({ preventDefault() {} });
const overlappingSubmit = saleForm.props.onSubmit({ preventDefault() {} });
assert.equal(overlap.asks.length, 1, "synchronous ref guard must block overlapping confirmations");
await overlappingSubmit;
confirmation.resolve(true);
await firstSubmit;
assert.equal(overlap.posts.length, 1);
assert.ok(overlap.updates[2].includes(null), "confirmed POST must close the form before refresh");
assert.ok(overlap.updates[1].includes("page.waste.saleRecordedRefreshFailed"), "refresh failure must retain sale success");
assert.equal(overlap.submissionRef.current, false);

const rejectedConfirmation = deferred();
const rejection = pageHarness({ confirmPromise: rejectedConfirmation });
const rejectionForm = walk(rejection.tree, node => node.type === "form" && String(node.props.className).includes("min-w-64"))[0];
const rejectedSubmit = rejectionForm.props.onSubmit({ preventDefault() {} });
rejectedConfirmation.reject(new Error("dialog failed"));
await rejectedSubmit;
assert.equal(rejection.submissionRef.current, false, "confirmation rejection must release the synchronous guard");

const corrupt = pageHarness({ storageFailure: true });
assert.ok(corrupt.updates[4].some(value => value.has(11)), "corrupt evidence must retain pending attention without throwing in a state updater");
console.log("Waste sales: real inputs, retained idempotent retries, isolation, and in-flight guard pass.");
