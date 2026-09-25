import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/shipments/page.tsx", import.meta.url), "utf8");
assert.doesNotMatch(source, /useSWR<ShipmentRow\[\]>\("\/api\/shipments"/);
assert.doesNotMatch(source, /useSWR<EligibleOrder\[\]>\("\/api\/shipments\/eligible-orders"/);
assert.match(source, /\/api\/shipments\/order-floor\?\$\{floorParams\.toString\(\)\}/);
assert.match(source, /target_sales_order_id/);
assert.match(source, /target_shipment_id/);
assert.match(source, /manual_open=true/);
assert.match(source, /page=\$\{index \+ 1\}&page_size=50&q=/);

const jsx = (type, props) => ({ type, props: props || {} });
const keys = [];
const effects = [];
let hooks = [];
let cursor = 0;
let observed = null;
let pageMode = false;
let requestedShipmentId = null;
class IntersectionObserverMock {
  constructor(callback) { this.callback = callback; }
  observe(node) { observed = { observer: this, node }; }
  disconnect() {}
}
globalThis.IntersectionObserver = IntersectionObserverMock;
const react = {
  useRef(initial) {
    const index = cursor++;
    if (!(index in hooks)) hooks[index] = { current: initial };
    return hooks[index];
  },
  useState(initial) {
    const index = cursor++;
    if (!(index in hooks)) hooks[index] = initial;
    return [hooks[index], (value) => { hooks[index] = value; }];
  },
  useEffect(effect) { effects.push(effect); },
  useMemo: (compute) => compute(),
};
const dependencies = {
  "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
  react,
  "next/link": { default: "link" },
  "next/navigation": { useSearchParams: () => ({ get: (name) => name === "shipment_id" ? requestedShipmentId : null }) },
  swr: { default: (key) => {
    keys.push(key);
    const data = pageMode && key?.startsWith("/api/shipments/order-floor?")
      ? { rows: [], pinned: null, total: 0 }
      : pageMode && key === "/api/shipments?shipment_id=55&page=1&page_size=1"
        ? { rows: [{ id: 55, shipment_no: "OFF-PAGE-SHIPPED", status: "shipped", shipment_type: "sales_order" }], total: 1 }
        : undefined;
    return { data, isLoading: false, mutate: async () => {} };
  } },
  "swr/infinite": { default: (getKey) => ({
    data: pageMode && getKey(0, null)?.includes("&status=")
      ? [{ rows: Array.from({ length: 50 }, (_, index) => ({ id: index + 100, shipment_no: `RECENT-${index}`, status: "delivered" })), has_more: true }]
      : [],
    size: 1, setSize() {}, mutate: async () => {},
  }) },
  "@/components/ShipmentAddClient": { default: "shipment-add-client" },
  "@/components/SearchableSelect": { default: "searchable-select" },
  "@/components/PageHeader": { default: "page-header" },
  "@/components/PaginationControls": { default: "pagination" },
  "@/components/ShipmentPreparationWorkspace": { default: "preparation-workspace" },
  "@/components/StagePipeline": { statusLabel: (value) => value },
  "@/components/DialogProvider": { useDialogs: () => ({ ask: async () => false }) },
  "@/components/ShipmentTransportDetails": {
    default: "transport-details", ShipmentTransportFields: "transport-fields", normalizeTransportDetails: (value) => value,
  },
  "@/lib/api": { api: {}, fetcher() {} },
  "@/lib/auth": { can: () => true, useMe: () => ({ me: { id: 7 } }) },
  "@/lib/i18n": { useT: () => ({ t: (key) => key, lang: "en" }) },
  "@/lib/orderRef": { formatOrderReference: (value) => value },
  "@/lib/packageWorkflow": {
    packageWorkflowChangedEvent: "package-workflow-changed",
    packageWorkflowCopy: { en: {} },
    pendingPackageWorkflow() {}, postPackageWorkflow() {}, reconcilePendingPackageWorkflow() {},
  },
  "@/lib/manualShipmentText": { manualShipmentText: { en: {} } },
  "@/lib/shipmentReviewText": { shipmentReviewText: { en: {} } },
  "@/lib/shipmentTransportText": { shipmentTransportText: { en: {} } },
};
const compiled = ts.transpileModule(`${source}\nexport { ShipmentOrderWorkspace };`, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const loadedModule = { exports: {} };
new Function("require", "exports", "module", compiled)((name) => {
  assert.ok(name in dependencies, `Unexpected import ${name}`);
  return dependencies[name];
}, loadedModule.exports, loadedModule);
const Workspace = loadedModule.exports.ShipmentOrderWorkspace;

function render(orderId) {
  cursor = 0;
  return Workspace({
    order: { id: orderId, order_no: `SO-${orderId}`, customer_name: "Customer", status: "ready", shipment: null, is_scanned: false },
    canTraceability: false,
    onChanged: async () => {},
  });
}
for (let orderId = 1; orderId <= 401; orderId++) {
  hooks = [];
  render(orderId);
}
assert.equal(keys.length, 401);
assert.ok(keys.every((key) => key === null), "401 unopened cards must issue zero preparation requests");

keys.length = 0;
effects.length = 0;
hooks = [];
const closed = render(777);
assert.equal(keys.at(-1), null);
closed.props.ref.current = {};
effects.splice(0).forEach((effect) => effect());
assert.ok(observed, "a visible card must be observed for lazy preparation");
observed.observer.callback([{ isIntersecting: true }]);
const open = render(777);
assert.equal(keys.at(-1), "/api/shipments/sales-order/777/preparation");
assert.match(JSON.stringify(open), /preparation-workspace/);
console.log("PASS: 401 paged shipment cards defer preparation and a visible card loads its workspace.");

pageMode = true;
requestedShipmentId = "55";
hooks = [];
effects.length = 0;
keys.length = 0;
let scrolls = 0;
globalThis.window = {
  setTimeout: () => 1, clearTimeout() {}, addEventListener() {}, removeEventListener() {},
  requestAnimationFrame: (callback) => callback(),
};
globalThis.document = {
  getElementById: (id) => id === "shipment-history-target-55"
    ? { scrollIntoView() { scrolls += 1; } } : null,
};
function renderPage() {
  cursor = 0;
  const tree = loadedModule.exports.default();
  effects.splice(0).forEach((effect) => effect());
  return tree;
}
const targetedPage = renderPage();
assert.ok(keys.includes("/api/shipments?shipment_id=55&page=1&page_size=1"));
assert.match(JSON.stringify(targetedPage), /OFF-PAGE-SHIPPED/);
assert.equal(scrolls, 1, "off-page historical shipment should scroll into the pinned history row");
renderPage();
assert.equal(scrolls, 1, "SWR revalidation must not repeat the deep-link scroll");
console.log("PASS: off-page historical shipment is pinned and scrolls only once.");
