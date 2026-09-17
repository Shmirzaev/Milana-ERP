import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/purchaseReceiptRecovery.ts", import.meta.url), "utf8");
const exports = {};
new Function("exports", ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }))(exports);
const { readPendingPurchaseReceipt: read, preparePurchaseReceipt: prepare, sendPreparedPurchaseReceipt: send, purchaseReceiptStorageKey: storageKey } = exports;
const scope = { userId: 12, factoryCode: "MIL" };
const lockTails = new Map();
const lockKeys = [];
let lockRequests = 0;
Object.defineProperty(globalThis, "navigator", { configurable: true, value: { locks: {
  request(key, action) {
    lockRequests++;
    lockKeys.push(key);
    const next = (lockTails.get(key) ?? Promise.resolve()).catch(() => {}).then(action);
    lockTails.set(key, next);
    return next;
  },
} } });
const payload = {
  supplier_id: 3, close_order: true,
  lines: [{ purchase_order_line_id: 9, received_quantity: 5, batch_no: "RECEIPT", warehouse_id: 2,
    cost_per_unit: 4, piece_count: 1, roll_weights_kg: [5] }],
};
function storage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

const saved = storage();
const first = await prepare(saved, scope, 20, payload);
assert.equal(first.isNew, true);
assert.deepEqual(read(saved, scope).payload, payload, "persist exact line, quantity and close-order choice before sending");
let received = 0;
const applied = new Set();
const server = async (pending) => {
  assert.equal(read(saved, scope).key, pending.key, "request identity must be persisted before sending");
  if (!applied.has(pending.key)) {
    applied.add(pending.key);
    received += pending.payload.lines[0].received_quantity;
    throw new Error("Backend is not responding"); // server committed, response was lost
  }
  return { received };
};
await assert.rejects(send(saved, scope, first, server), /not responding/);
assert.equal(received, 5);

// A fresh read models closing the dialog/reloading; no in-memory request survives.
const restored = read(saved, scope);
assert.equal(restored.key, first.pending.key);
assert.deepEqual(restored.payload, payload);
await assert.rejects(prepare(saved, scope, 20, { ...payload, close_order: false }), /pending/);
await assert.rejects(prepare(saved, scope, 21, payload), /pending/);
const retry = await prepare(saved, scope, restored.orderId, restored.payload);
assert.equal(retry.isNew, false);
await assert.rejects(send(saved, scope, retry, async () => { throw new Error("404: temporarily unavailable"); }), /404/);
assert.equal(read(saved, scope).key, restored.key, "a later 4xx cannot erase an uncertain committed receipt");
assert.deepEqual(await send(saved, scope, retry, server), { received: 5 });
assert.equal(received, 5);
assert.equal(read(saved, scope), null);

for (const status of [400, 404, 409, 422]) {
  const rejected = await prepare(saved, scope, 20, payload);
  await assert.rejects(send(saved, scope, rejected, async () => { throw new Error(`${status}: invalid`); }));
  assert.equal(read(saved, scope), null, "definitive first rejection allows correcting the form");
}
for (const status of [401, 403, 408, 429, 500, 503]) {
  const kept = storage();
  const uncertain = await prepare(kept, scope, 20, payload);
  await assert.rejects(send(kept, scope, uncertain, async () => { throw new Error(`${status}: unavailable`); }));
  assert.equal(read(kept, scope).key, uncertain.pending.key);
}

const isolated = storage();
const originalPayload = structuredClone(payload);
const immutable = await prepare(isolated, scope, 20, originalPayload);
originalPayload.lines[0].received_quantity = 100;
assert.equal(immutable.pending.payload.lines[0].received_quantity, 5);
assert.equal(read(isolated, { ...scope, userId: 13 }), null);
assert.equal(read(isolated, { ...scope, factoryCode: "ECO" }), null);
assert.notEqual((await prepare(isolated, { ...scope, userId: 13 }, 20, payload)).pending.key, immutable.pending.key);

const broken = storage();
broken.setItem(storageKey(scope), "not-json");
await assert.rejects(prepare(broken, scope, 20, payload), /storage/);
assert.equal(broken.getItem(storageKey(scope)), "not-json", "unreadable pending data must not be discarded");
await assert.rejects(prepare({ ...storage(), setItem() { throw new Error("Quota exceeded"); } }, scope, 20, payload), /storage/);

const tabs = storage();
const locksBefore = lockRequests;
const [tabA, tabB] = await Promise.all([prepare(tabs, scope, 20, payload), prepare(tabs, scope, 20, payload)]);
assert.equal(lockRequests - locksBefore, 2, "every tab must acquire the shared browser lock");
assert.equal(tabA.pending.key, tabB.pending.key, "concurrent tabs reuse the persisted key");
assert.deepEqual([tabA.isNew, tabB.isNew], [true, false]);

// Successful and definitively rejected sends must await the same cross-tab lock
// before inspecting/removing recovery data, not just fire-and-forget cleanup.
for (const status of [null, 409]) {
  const completionStorage = storage();
  const prepared = await prepare(completionStorage, scope, 20, payload);
  const acquired = deferred();
  const release = deferred();
  const held = navigator.locks.request(storageKey(scope), () => {
    acquired.resolve();
    return release.promise;
  });
  await acquired.promise;
  const requestsBeforeCompletion = lockRequests;
  let settled = false;
  const completion = send(completionStorage, scope, prepared, async () => {
    if (status) throw new Error(`${status}: rejected`);
    return "received";
  }).then(
    value => { settled = true; return { value }; },
    error => { settled = true; return { error }; },
  );
  try {
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(lockRequests - requestsBeforeCompletion, 1, "cleanup must acquire a browser lock");
    assert.equal(lockKeys.at(-1), storageKey(scope), "cleanup and preparation must share the exact lock key");
    assert.equal(settled, false, "send must await cleanup while another tab holds the lock");
    assert.equal(read(completionStorage, scope).key, prepared.pending.key, "held lock must prevent premature deletion");
  } finally {
    release.resolve();
  }
  await held;
  const result = await completion;
  if (status) assert.equal(result.error.message, `${status}: rejected`);
  else assert.equal(result.value, "received");
  assert.equal(read(completionStorage, scope), null);
}

// One tab may finish/retry an old request after another tab has already cleared
// that request and prepared a new one. The late completion must keep the new key.
const lateStorage = storage();
const oldFirst = await prepare(lateStorage, scope, 20, payload);
const oldRetry = await prepare(lateStorage, scope, 20, payload);
const lateResponse = deferred();
const lateCompletion = send(lateStorage, scope, oldFirst, () => lateResponse.promise);
await send(lateStorage, scope, oldRetry, async () => "already received");
const newer = await prepare(lateStorage, scope, 21, payload);
assert.notEqual(newer.pending.key, oldFirst.pending.key);
const requestsBeforeLateCompletion = lockRequests;
lateResponse.resolve("received late");
assert.equal(await lateCompletion, "received late");
assert.equal(lockRequests - requestsBeforeLateCompletion, 1, "late completion must still acquire the shared lock");
assert.equal(lockKeys.at(-1), storageKey(scope));
assert.deepEqual(read(lateStorage, scope), newer.pending, "late old-key completion must not remove newer recovery data");

const workingLocks = navigator.locks;
navigator.locks = undefined;
await assert.rejects(prepare(storage(), scope, 20, payload), /storage/);
navigator.locks = workingLocks;

const page = fs.readFileSync(new URL("../src/app/(app)/purchasing/receiving/page.tsx", import.meta.url), "utf8");
// Exercise the actual page's reload/open/retry handlers against a closed order.
const browserStorage = storage();
const closedPayload = { ...payload, lines: [{ ...payload.lines[0], piece_count: null, roll_weights_kg: [] }] };
const closedPending = (await prepare(browserStorage, scope, 20, closedPayload)).pending;
const hooks = [];
let cursor = 0;
let dirty = false;
let effects = [];
let confirmationCount = 0;
const sent = [];
const closedOrder = {
  id: 20, po_no: "PO-TEST", status: "received",
  // Current master data changed since the uncertain request. Replay its original payload.
  lines: [{ id: 9, item_id: 1, item_sku: "TEST", unit: "kg", ordered_quantity: 5,
    received_quantity: 5, remaining_quantity: 0, unit_cost: 4 }],
};
const t = (key) => key;
const jsx = (type, props) => ({ type, props });
const dependencies = {
  "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
  react: {
    Fragment: "fragment",
    useState(initial) {
      const index = cursor++;
      if (!(index in hooks)) hooks[index] = typeof initial === "function" ? initial() : initial;
      return [hooks[index], (next) => {
        const value = typeof next === "function" ? next(hooks[index]) : next;
        if (value !== hooks[index]) dirty = true;
        hooks[index] = value;
      }];
    },
    useRef(initial) { const index = cursor++; return hooks[index] ??= { current: initial }; },
    useMemo: (calculate) => calculate(),
    useEffect(effect, deps) {
      const index = cursor++;
      if (!hooks[index] || deps.some((value, i) => value !== hooks[index][i])) effects.push(effect);
      hooks[index] = deps;
    },
  },
  swr: { default: (key) => ({ data: key === "/api/purchasing/orders" ? [closedOrder] : [], mutate() {} }) },
  "next/link": { default: "a" },
  "lucide-react": Object.fromEntries(["ArrowLeft", "ChevronDown", "ChevronRight", "PackageCheck", "X"].map(name => [name, name])),
  "@/components/PageHeader": { default: "header" },
  "@/components/DialogProvider": { useDialogs: () => ({ async ask() { confirmationCount++; return false; } }) },
  "@/components/StagePipeline": { statusLabel: value => value },
  "@/lib/api": { api: { async postWithIdempotency(...args) { sent.push(args); return {}; } }, fetcher() {} },
  "@/lib/auth": { can: () => true, useMe: () => ({ me: { id: scope.userId, factory_code: scope.factoryCode } }) },
  "@/lib/i18n": { useT: () => ({ t }) },
  "@/lib/orderRef": { formatOrderReference: value => value },
  "@/lib/materialRollWeights": { divideBatchQuantityByRollCount: () => { throw new Error("Retry must not rebuild roll weights"); } },
  "@/lib/purchaseReceiptRecovery": exports,
};
const pageExports = {};
new Function("exports", "require", ts.transpile(page, {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
}))(pageExports, (name) => {
  assert.ok(name in dependencies, `Unexpected page dependency ${name}`);
  return dependencies[name];
});
function render() {
  for (let attempt = 0; attempt < 5; attempt++) {
    cursor = 0;
    dirty = false;
    const tree = pageExports.default();
    const queued = effects;
    effects = [];
    queued.forEach(effect => effect());
    if (!dirty) return tree;
  }
  throw new Error("Page did not settle");
}
function elements(tree, type) {
  if (!tree) return [];
  if (Array.isArray(tree)) return tree.flatMap(child => elements(child, type));
  if (typeof tree !== "object") return [];
  return [...(tree.type === type ? [tree] : []), ...elements(tree.props?.children, type)];
}
const originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
try {
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: browserStorage });
  let tree = render();
  const retryButton = elements(tree, "button").find(button => JSON.stringify(button.props.children).includes("common.retry"));
  assert.ok(retryButton, "closed orders must still expose pending-receipt recovery");
  retryButton.props.onClick();
  tree = render();
  assert.equal(elements(tree, "fieldset")[0].props.disabled, true, "pending receipt fields must remain immutable");
  await elements(tree, "form")[0].props.onSubmit({ preventDefault() {} });
  assert.equal(confirmationCount, 0, "retry must retain the original close-order decision");
  assert.deepEqual(sent, [["/api/purchasing/orders/20/receive", closedPayload, closedPending.key]]);
  assert.equal(read(browserStorage, scope), null);
  assert.equal(elements(render(), "form").length, 0);
} finally {
  if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage);
  else delete globalThis.localStorage;
}
console.log("Purchase receipts: replay/reload recovery, cross-tab preparation and awaited cleanup locks, late-completion key preservation, and definitive rejection recovery pass.");
