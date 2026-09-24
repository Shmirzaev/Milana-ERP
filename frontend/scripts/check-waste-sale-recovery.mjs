import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/wasteSaleRecovery.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const localValues = new Map();
const sessionValues = new Map();
const calls = [];
let failure = null;
let reconciliation = { status: "completed", result: { id: 1 } };
let sequence = 0;

function storage(values) {
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
}

function serialLocks() {
  const tails = new Map();
  return {
    request(name, action) {
      const prior = tails.get(name) ?? Promise.resolve();
      let release;
      const current = new Promise(resolve => { release = resolve; });
      tails.set(name, prior.then(() => current));
      return prior.then(action).finally(release);
    },
  };
}

class TestEvent {
  constructor(type) { this.type = type; }
}

const localStorage = storage(localValues);
const sessionStorage = storage(sessionValues);
const windowEvents = [];
let apiHandler = async (path) => path.endsWith("/reconcile") ? reconciliation : { id: 1 };
const context = {
  exports: {},
  crypto: { randomUUID: () => `sale-${++sequence}` },
  Event: TestEvent,
  navigator: { locks: serialLocks() },
  window: {
    localStorage,
    sessionStorage,
    dispatchEvent: event => windowEvents.push(event.type),
  },
  require: () => ({ api: { postWithIdempotency: async (...args) => {
    calls.push(args);
    if (failure) throw new Error(failure);
    return apiHandler(...args);
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
assert.ok(localValues.has("waste-sale:7:11"), "recovery evidence must be shared across tabs");
assert.equal(sessionValues.has("waste-sale:7:11"), false);

await assert.rejects(postWasteSale(7, 11, { ...payload, quantity: 3 }), error => error?.code === "pending");
assert.equal(calls.length, 1, "edited retry must not create a second sale request");
assert.equal(pendingWasteSale(8, 11), null, "pending sales must be user scoped");
assert.equal(pendingWasteSale(7, 12), null, "pending sales must be waste-record scoped");

failure = "422: changed values rejected";
await assert.rejects(postWasteSale(7, 11, payload));
assert.equal(pendingWasteSale(7, 11).key, "sale-1", "later rejection cannot erase uncertain evidence");
assert.equal(calls.at(-1)[0], "/api/waste/11/sell/reconcile", "an uncertain sale must be reconciled, not executed again");
failure = null;
await postWasteSale(7, 11, payload);
assert.equal(calls.at(-1)[2], "sale-1", "retry must reuse the original idempotency key");
assert.equal(pendingWasteSale(7, 11), null);

failure = "400: sale quantity exceeds remaining waste quantity";
await assert.rejects(postWasteSale(7, 11, payload));
assert.equal(pendingWasteSale(7, 11), null, "first definitive rejection is safe to clear");
failure = null;

localValues.set("waste-sale:7:12", JSON.stringify({ version: 1, key: "sale-cancelled", payload }));
reconciliation = { status: "cancelled" };
await assert.rejects(postWasteSale(7, 12, payload), error => error?.code === "cancelled");
assert.equal(pendingWasteSale(7, 12), null, "a server tombstone safely releases cancelled evidence");

localValues.set("waste-sale:7:13", JSON.stringify({ version: 1, key: "sale-unavailable", payload }));
reconciliation = { status: "completed_unavailable" };
await assert.rejects(postWasteSale(7, 13, payload), error => error?.code === "completed_unavailable");
assert.equal(pendingWasteSale(7, 13), null, "a committed unavailable result must not be physically replayed");
reconciliation = { status: "completed", result: { id: 1 } };

sessionValues.set("waste-sale:7:14", JSON.stringify({ version: 1, key: "legacy-sale", payload }));
failure = "Backend is not responding";
await assert.rejects(postWasteSale(7, 14, payload));
assert.equal(sessionValues.has("waste-sale:7:14"), false, "same-tab legacy evidence must migrate");
assert.equal(pendingWasteSale(7, 14).key, "legacy-sale");
assert.ok(localValues.has("waste-sale:7:14"), "migrated evidence must become cross-tab visible");
failure = null;

localValues.set("waste-sale:7:15", "{broken");
assert.throws(() => pendingWasteSale(7, 15), error => error?.code === "storage");
const callsBeforeCorrupt = calls.length;
await assert.rejects(postWasteSale(7, 15, payload), error => error?.code === "storage");
assert.equal(calls.length, callsBeforeCorrupt, "corrupt evidence must fail before sending");
localValues.set("waste-sale:7:16", JSON.stringify({ version: 1, key: "sale-bad", payload: { ...payload, quantity: null } }));
assert.throws(() => pendingWasteSale(7, 16), error => error?.code === "storage", "non-finite persisted fields must fail closed");

localValues.set("waste-sale:7:17", JSON.stringify({ version: 1, key: "shared-sale", payload }));
sessionValues.set("waste-sale:7:17", JSON.stringify({ version: 1, key: "conflicting-sale", payload }));
await assert.rejects(postWasteSale(7, 17, payload), error => error?.code === "storage");
assert.equal(calls.length, callsBeforeCorrupt, "conflicting tab evidence must fail before sending");

const workingLocks = context.navigator.locks;
context.navigator.locks = undefined;
await assert.rejects(postWasteSale(7, 18, payload), error => error?.code === "storage");
context.navigator.locks = workingLocks;
assert.equal(calls.length, callsBeforeCorrupt, "missing cross-tab locking must fail before sending");
assert.ok(windowEvents.includes("waste-sale-changed"), "same-tab UI must be notified when evidence changes");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const concurrentStart = calls.length;
const physicalSale = deferred();
apiHandler = async path => path === "/api/waste/19/sell"
  ? physicalSale.promise
  : path === "/api/waste/19/sell/reconcile"
    ? { status: "completed", result: { id: 19 } }
    : path.endsWith("/reconcile") ? reconciliation : { id: 1 };
const firstTab = postWasteSale(7, 19, payload);
await Promise.resolve();
await Promise.resolve();
const secondTab = postWasteSale(7, 19, payload);
assert.deepEqual(await secondTab, { id: 19 });
physicalSale.resolve({ id: 19 });
assert.deepEqual(await firstTab, { id: 19 });
const concurrentCalls = calls.slice(concurrentStart).filter(([path]) => path.includes("/waste/19/"));
assert.deepEqual(concurrentCalls.map(([path]) => path), [
  "/api/waste/19/sell",
  "/api/waste/19/sell/reconcile",
]);
assert.equal(concurrentCalls[0][2], concurrentCalls[1][2], "cross-tab calls must share one request key");
assert.equal(pendingWasteSale(7, 19), null);
apiHandler = async path => path.endsWith("/reconcile") ? reconciliation : { id: 1 };

function walk(node, predicate, found = []) {
  if (!node || typeof node !== "object") return found;
  if (predicate(node)) found.push(node);
  const children = node.props?.children;
  for (const child of Array.isArray(children) ? children : [children]) walk(child, predicate, found);
  return found;
}

class HarnessRecoveryError extends Error {
  constructor(code) { super(code); this.code = code; }
}

function pageHarness({ confirmPromise, refreshFailure = false, storageFailure = false, recoveryCode = null } = {}) {
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
      ? { data: [{ id: 11, waste_type: "offcuts", quantity: 10, remaining_quantity: 6, unit: "kg", sellable: true, status: "sold", estimated_value: 1 }], mutate: async () => { if (refreshFailure) throw new Error("refresh failed"); } }
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
        if (storageFailure) throw new HarnessRecoveryError("storage");
        return { version: 1, key: "sale-1", payload };
      },
      postWasteSale: async (...args) => {
        posts.push(args);
        if (recoveryCode) throw new HarnessRecoveryError(recoveryCode);
        return { id: 1 };
      },
      WasteSaleRecoveryError: HarnessRecoveryError,
      wasteSaleChangedEvent: "waste-sale-changed",
      wasteSaleStorageKey: (userId, wasteId) => `waste-sale:${userId}:${wasteId}`,
    },
  })[name] ?? (() => { throw new Error(`Unexpected dependency: ${name}`); })());
  const tree = pageExports.default();
  return { tree, updates, submissionRef, asks, posts };
}

const confirmation = deferred();
const overlap = pageHarness({ confirmPromise: confirmation, refreshFailure: true });
assert.ok(walk(overlap.tree, node => node.type === "div" && node.props.children?.join?.("") === "field.remaining: 6.00 kg").length,
  "the actual page must render the server-computed remaining balance");
assert.ok(walk(overlap.tree, node => node.type === "button" && node.props.children === "page.waste.retrySale").length,
  "a sold row with pending evidence must expose exact replay");
const saleForm = walk(overlap.tree, node => node.type === "form" && String(node.props.className).includes("min-w-64"))[0];
assert.ok(walk(saleForm, node => node.type === "input" && node.props.type === "number" && node.props.max === 6).length,
  "the sale quantity input must expose the server-computed balance while server validation remains authoritative");
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

const unavailable = pageHarness({ recoveryCode: "completed_unavailable" });
const unavailableForm = walk(unavailable.tree, node => node.type === "form" && String(node.props.className).includes("min-w-64"))[0];
await unavailableForm.props.onSubmit({ preventDefault() {} });
assert.ok(unavailable.updates[2].includes(null), "a committed unavailable sale must close without replaying the write");
assert.ok(unavailable.updates[1].includes("page.waste.saleRecoveryResolved"));

const cancelled = pageHarness({ recoveryCode: "cancelled" });
const cancelledForm = walk(cancelled.tree, node => node.type === "form" && String(node.props.className).includes("min-w-64"))[0];
await cancelledForm.props.onSubmit({ preventDefault() {} });
assert.equal(cancelled.updates[2].includes(null), false, "an uncommitted cancelled sale stays open for review");
assert.ok(cancelled.updates[1].includes("page.waste.saleRecoveryCancelled"));

console.log("Waste sales: balance display, cross-tab reconciliation, exact inputs, and recovery guards pass.");
