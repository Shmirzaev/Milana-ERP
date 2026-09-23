import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const localValues = new Map();
const legacyValues = new Map();
const listeners = new Map();
const calls = [];
let response = { status: "completed", result: { id: 8, run_no: "RUN-8" } };
let labelError = null;

function storage(values) {
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
}

const lockTails = new Map();
Object.defineProperty(globalThis, "navigator", { configurable: true, value: { locks: {
  request(key, action) {
    const next = (lockTails.get(key) ?? Promise.resolve()).catch(() => {}).then(action);
    lockTails.set(key, next);
    return next;
  },
} } });

globalThis.window = {
  localStorage: storage(localValues),
  sessionStorage: storage(legacyValues),
  addEventListener(type, listener) {
    const entries = listeners.get(type) ?? new Set();
    entries.add(listener);
    listeners.set(type, entries);
  },
  removeEventListener(type, listener) { listeners.get(type)?.delete(listener); },
  dispatchEvent(event) {
    for (const listener of listeners.get(event.type) ?? []) listener(event);
    return true;
  },
};
globalThis.Event = class Event { constructor(type) { this.type = type; } };

const api = {
  post: async (path, body) => { calls.push({ path, body }); return response; },
  openLabel: async () => { if (labelError) throw new Error(labelError); },
};
const packageSource = ts.transpileModule(
  fs.readFileSync(new URL("../src/lib/packageWorkflow.ts", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } },
).outputText;
const packageModule = { exports: {} };
new Function("require", "exports", "module", packageSource)(
  id => id === "@/lib/api" ? { api } : {},
  packageModule.exports,
  packageModule,
);
const packageWorkflow = packageModule.exports;

const hooks = [];
let cursor = 0;
let dirty = false;
let effects = [];
const react = {
  useState(initial) {
    const index = cursor++;
    if (!(index in hooks)) hooks[index] = typeof initial === "function" ? initial() : initial;
    return [hooks[index], next => {
      const value = typeof next === "function" ? next(hooks[index]) : next;
      if (value !== hooks[index]) dirty = true;
      hooks[index] = value;
    }];
  },
  useEffect(effect, deps) {
    const index = cursor++;
    if (!hooks[index] || deps.some((value, i) => value !== hooks[index][i])) effects.push(effect);
    hooks[index] = deps;
  },
  useMemo: calculate => calculate(),
};
const jsx = (type, props) => ({ type, props: props || {} });
const componentSource = ts.transpileModule(
  fs.readFileSync(new URL("../src/components/PendingPackageWorkflow.tsx", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } },
).outputText;
const componentModule = { exports: {} };
new Function("require", "exports", "module", componentSource)(id => {
  if (id === "react") return react;
  if (id === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "fragment" };
  if (id === "@/lib/api") return { api };
  if (id === "@/lib/auth") return { useMe: () => ({ me: { id: 7 } }) };
  if (id === "@/lib/i18n") return { useT: () => ({ lang: "en" }) };
  if (id === "@/lib/packageWorkflow") return packageWorkflow;
  throw new Error(`unexpected import ${id}`);
}, componentModule.exports, componentModule);
const PendingPackageWorkflow = componentModule.exports.default;

const path = "/api/packages/print-runs";
const body = { package_ids: [1] };
const storageKey = packageWorkflow.packageWorkflowStorageKey(path, 7);
function save(requestKey) {
  localValues.set(storageKey, JSON.stringify({ requestKey, body }));
}
function render(onResolved = async () => {}) {
  for (let attempt = 0; attempt < 5; attempt++) {
    cursor = 0;
    dirty = false;
    const tree = PendingPackageWorkflow({ path, onResolved });
    const queued = effects;
    effects = [];
    queued.forEach(effect => effect());
    if (!dirty) return tree;
  }
  throw new Error("Pending workflow did not settle");
}
function elements(tree, type) {
  if (!tree) return [];
  if (Array.isArray(tree)) return tree.flatMap(child => elements(child, type));
  if (typeof tree !== "object") return [];
  return [...(tree.type === type ? [tree] : []), ...elements(tree.props?.children, type)];
}
async function recover(onResolved = async () => {}) {
  const tree = render(onResolved);
  const button = elements(tree, "button")[0];
  assert(button, "pending component must render its recovery handler");
  await button.props.onClick();
  return render(onResolved);
}

save("request-1");
response = { status: "completed" };
await recover();
assert(localValues.has(storageKey), "invalid reconciliation keeps the pending request");
assert.equal(calls.length, 1);
assert.equal(calls[0].path, "/api/packages/print-runs/reconcile");

response = { status: "completed", result: { id: 9, run_no: "RUN-9" } };
labelError = "403: forbidden";
await recover();
assert.equal(calls.length, 2, "label permission failure must not repost the package action");
assert.equal(calls[1].path, "/api/packages/print-runs/reconcile");
assert.equal(localValues.has(storageKey), false, "committed action clears recovery evidence");
labelError = null;

save("request-3");
window.dispatchEvent(new Event("storage"));
response = { status: "completed_unavailable" };
let tree = await recover();
assert.equal(localValues.has(storageKey), false);
assert.match(JSON.stringify(tree), /result is deleted or no longer available/);

save("request-4");
window.dispatchEvent(new Event("storage"));
response = { status: "cancelled" };
tree = await recover();
assert.equal(localValues.has(storageKey), false);
assert.match(JSON.stringify(tree), /safely cancelled/);

save("request-5");
window.dispatchEvent(new Event("storage"));
response = { status: "completed", result: { id: 11, run_no: "RUN-11" } };
await recover(async () => { throw new Error("refresh failed"); });
assert.equal(calls.length, 5, "refresh failure after commit must not repost the package action");
assert.equal(localValues.has(storageKey), false, "refresh failure keeps the committed action resolved");
assert.ok(calls.every(call => call.path.endsWith("/reconcile")), "recovery only calls status/tombstone endpoints");

const manualSource = fs.readFileSync(new URL("../src/components/ManualPackageReceipt.tsx", import.meta.url), "utf8");
assert.match(manualSource, /reconcilePendingPackageWorkflow<[^>]*PackagePrintRun/, "manual receipt handler must reconcile rather than repost");
assert.match(manualSource, /addEventListener\("storage", update\)/, "manual receipt handler must observe other tabs");
const shipmentSource = fs.readFileSync(new URL("../src/app/(app)/shipments/page.tsx", import.meta.url), "utf8");
assert.match(shipmentSource, /reconcilePendingPackageWorkflow<ShipmentRow>/, "shipment handler must reconcile rather than repost");
assert.match(shipmentSource, /addEventListener\("storage", update\)/, "shipment handler must observe other tabs");

// Exercise the actual revoked-access shipment page handler. It must remain
// visible for saved evidence and call only the result-free reconcile route.
hooks.length = 0;
cursor = 0;
dirty = false;
effects = [];
listeners.clear();
const shipmentModule = { exports: {} };
const shipmentDependencies = {
  "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
  react,
  "next/link": { default: "a" },
  "next/navigation": { useSearchParams: () => ({ get: () => null }) },
  swr: { default: () => ({ data: [], mutate: async () => [] }) },
  "@/components/ShipmentAddClient": { default: "ShipmentAddClient" },
  "@/components/SearchableSelect": { default: "SearchableSelect" },
  "@/components/PageHeader": { default: "PageHeader" },
  "@/components/ShipmentPreparationWorkspace": { default: "ShipmentPreparationWorkspace" },
  "@/components/StagePipeline": { statusLabel: value => value },
  "@/components/DialogProvider": { useDialogs: () => ({ ask: async () => false }) },
  "@/components/ShipmentTransportDetails": {
    default: "ShipmentTransportDetails",
    ShipmentTransportFields: "ShipmentTransportFields",
    normalizeTransportDetails: value => value,
  },
  "@/lib/api": { api, fetcher: async () => [] },
  "@/lib/auth": { can: () => false, useMe: () => ({ me: { id: 7 } }) },
  "@/lib/i18n": { useT: () => ({ t: key => key, lang: "en" }) },
  "@/lib/orderRef": { formatOrderReference: value => value },
  "@/lib/packageWorkflow": packageWorkflow,
  "@/lib/manualShipmentText": { manualShipmentText: { en: {
    title: "Manual shipment", hint: "Hint", choose: "Choose", none: "None", created: "Created", confirm: "Confirm", type: "Manual",
  } } },
  "@/lib/shipmentReviewText": { shipmentReviewText: { en: { reference: "Reference", print: "Print" } } },
  "@/lib/shipmentTransportText": { shipmentTransportText: { en: { optional: "Optional" } } },
};
new Function("require", "exports", "module", ts.transpileModule(shipmentSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText)(id => {
  assert.ok(id in shipmentDependencies, `unexpected shipment import ${id}`);
  return shipmentDependencies[id];
}, shipmentModule.exports, shipmentModule);
const ShipmentsPage = shipmentModule.exports.default;
const shipmentPath = "/api/shipments";
const shipmentKey = packageWorkflow.packageWorkflowStorageKey(shipmentPath, 7);
localValues.set(shipmentKey, JSON.stringify({
  requestKey: "shipment-request-1",
  body: { manual: true, customer_id: 3, transport_details: null },
}));
function renderShipmentPage() {
  for (let attempt = 0; attempt < 5; attempt++) {
    cursor = 0;
    dirty = false;
    const tree = ShipmentsPage();
    const queued = effects;
    effects = [];
    queued.forEach(effect => effect());
    if (!dirty) return tree;
  }
  throw new Error("Shipment page did not settle");
}
response = { status: "completed_unavailable" };
const shipmentCallsBefore = calls.length;
let shipmentTree = renderShipmentPage();
const shipmentRecover = elements(shipmentTree, "button")
  .find(button => JSON.stringify(button.props.children).includes("Recover saved request"));
assert.ok(shipmentRecover, "revoked shipment access must retain the recovery handler");
await shipmentRecover.props.onClick();
shipmentTree = renderShipmentPage();
assert.equal(calls.length, shipmentCallsBefore + 1);
assert.equal(calls.at(-1).path, "/api/shipments/reconcile");
assert.equal(localValues.has(shipmentKey), false);
assert.match(JSON.stringify(shipmentTree), /result is deleted or no longer available/);

console.log("PASS: actual package and revoked-access shipment handlers reconcile lost/deleted/revoked results without reposting; manual receipt contracts observe cross-tab evidence.");
