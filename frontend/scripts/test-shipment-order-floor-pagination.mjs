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
  "next/navigation": { useSearchParams: () => ({ get: () => null }) },
  swr: { default: (key) => { keys.push(key); return { data: undefined, isLoading: false, mutate: async () => {} }; } },
  "swr/infinite": { default: () => ({ data: [], size: 1, setSize() {}, mutate: async () => {} }) },
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
const module = { exports: {} };
new Function("require", "exports", "module", compiled)((name) => {
  assert.ok(name in dependencies, `Unexpected import ${name}`);
  return dependencies[name];
}, module.exports, module);
const Workspace = module.exports.ShipmentOrderWorkspace;

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
