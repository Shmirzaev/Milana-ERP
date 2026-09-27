import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const read = path => fs.readFileSync(new URL(path, import.meta.url), "utf8").replace(/\r\n/g, "\n");
const pageSource = read("../src/app/(app)/process-qr/page.tsx");
const authGate = read("../src/components/AuthGate.tsx");
const sidebar = read("../src/components/Sidebar.tsx");

const operation = {
  id: "sew-1",
  sourceStage: "sewing",
  selected: true,
  section: "sewing",
  code: "SEW-1",
  name: "Sewing",
  rate: "250",
  copies: 1,
  splitMode: "none",
  splitQuantities: [],
  sewingFactory: "milana",
};
const processRow = {
  production_order_id: 1,
  production_no: "PO-1",
  order_no: "SO-1",
  sales_order_id: 1,
  sales_order_no: "SO-1",
  customer_name: "Synthetic customer",
  model_id: 1,
  model_code: "MODEL-1",
  model_name: "Synthetic model",
  planned_quantity: 10,
  actual_quantity: 10,
  sewing_completed_quantity: 10,
  current_stage: "sewing",
  sizes: [{ size: "M", planned_quantity: 10, completed_quantity: 10, sewing_completed_quantity: 10 }],
  batches: [],
  stages: [],
  sewing_factories: [],
};
const issuedLabel = {
  id: 1,
  label_uid: "ISSUED-1",
  qr_token: "200000001",
  payload: null,
  production_order_id: 1,
  production_no: "PO-1",
  sales_order_no: "SO-1",
  batch_no: null,
  model_code: "MODEL-1",
  operation_section: "sewing",
  operation_code: "SEW-1",
  operation_name: "Sewing",
  sewing_line_code: "LINE-1",
  sewing_line_name: "Line 1",
  cutting_passport_no: null,
  size: "M",
  copy_index: 1,
  quantity: 10,
  rate_per_piece: 250,
  currency: "UZS",
  status: "available",
  payroll_record_id: null,
  issued_at: "2026-09-20T00:00:00Z",
  last_scanned_at: null,
  return_count: 0,
  superseded_at: null,
  superseded_by: null,
  split_from_label_id: null,
};

function swrFixture(key) {
  let data;
  if (typeof key === "string" && key.startsWith("/api/process-tracking?")) data = [processRow];
  else if (key === "/api/employees" || key === "/api/departments" || key === "/api/sewing-flows") data = [];
  else if (key === "/api/models/1") data = { id: 1, code: "MODEL-1", name: "Synthetic model", details_json: {}, sizes: [{ size: "M" }] };
  else if (typeof key === "string" && key.startsWith("/api/payroll/qr-labels?")) {
    data = { items: [issuedLabel], total: 1, available_count: 1, scanned_count: 0 };
  }
  return { data, error: undefined, isLoading: false, isValidating: false, mutate: async () => undefined };
}

const iconNames = [
  "ArrowDown", "ArrowUp", "CheckSquare", "ChevronDown", "Pencil", "Plus", "Printer",
  "QrCode", "RefreshCw", "Save", "Search", "Trash2", "Users",
];
const icons = Object.fromEntries(iconNames.map(name => [name, props => React.createElement("i", { ...props, "data-icon": name })]));
const asDefault = value => ({ __esModule: true, default: value });

function dependencies({ canManage, react = React, apiCalls }) {
  const api = {
    get: async () => ({}),
    post: async (...args) => { apiCalls.push(args); return { labels: [], issued_count: 0, created_count: 0, existing_count: 0 }; },
    patch: async () => ({}),
    del: async () => ({}),
  };
  return {
    react,
    "react/jsx-runtime": jsxRuntime,
    "next/link": asDefault(({ children, href, ...props }) => React.createElement("a", { ...props, href }, children)),
    swr: asDefault(swrFixture),
    qrcode: asDefault({ toDataURL: async () => "data:image/png;base64," }),
    "lucide-react": icons,
    "@/lib/api": { api, fetcher: async () => undefined },
    "@/lib/batchSerial": { formatBatchSerial: () => "B-1" },
    "@/lib/orderRef": { orderReference: () => "SO-1", formatOrderReference: () => "SO-1" },
    "@/lib/numberInput": { parseNumberInput: value => value === "" ? "" : Number(value) },
    "@/lib/processQrLabelIdentity": {
      buildOperationLabelTokens: operations => new Map(operations.map(row => [row.id, row.code])),
      buildIssuedOperationNumbers: (_operations, labels) => new Map(labels.map((row, index) => [row.id, index + 1])),
      correctedOperationIdentityNeedsReview: () => false,
    },
    "@/lib/auth": { useMe: () => ({ me: { id: 1, factory_code: "MIL" } }), can: () => canManage },
    "@/lib/modelPaidOperations": {
      clonePaidOperations: () => [{ ...operation }],
      createPaidOperation: () => ({ ...operation }),
      materializeLegacyPaidOperations: () => [{ ...operation }],
      paidOperationFactoryFromDepartmentCode: () => "milana",
      paidOperationMatchesFactory: () => true,
      paidOperationsFromDetails: () => [{ ...operation }],
      SECTION_BADGES: { sewing: "SEW" },
      VALID_SECTIONS: ["sewing"],
      samePaidProcess: () => false,
      serializePaidOperations: rows => rows,
    },
    "@/components/PaidProcessPicker": asDefault(() => React.createElement("div", { "data-testid": "paid-process-picker" })),
    "@/components/ManualModelSizes": asDefault(() => React.createElement("div", { "data-testid": "manual-model-sizes" })),
    "@/lib/paidProcessSections": { paidSectionLabel: value => value },
    "@/components/PageHeader": asDefault(({ actions }) => React.createElement("header", null, actions)),
    "@/components/DialogProvider": { useDialogs: () => ({ confirm: async () => true, alert: async () => undefined }) },
    "@/components/Modal": asDefault(({ open, children }) => open ? React.createElement("div", null, children) : null),
    "@/lib/i18n": { useT: () => ({ lang: "en", t: (key, values) => values?.size ? `${key}:${values.size}` : key }) },
    "@/lib/modelVariants": { modelVariantOption: () => "MODEL-1" },
  };
}

function loadPage(source, options) {
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
  }).outputText;
  const loadedModule = { exports: {} };
  const available = dependencies(options);
  new Function("exports", "module", "require", output)(loadedModule.exports, loadedModule, name => {
    assert.ok(name in available, `Unexpected page dependency: ${name}`);
    return available[name];
  });
  return loadedModule.exports.default;
}

function renderRole(canManage) {
  const apiCalls = [];
  const Page = loadPage(pageSource.replace("<style jsx global>", "<style>"), { canManage, apiCalls });
  return { html: renderToStaticMarkup(React.createElement(Page)), apiCalls };
}

const scanOnly = renderRole(false);
assert.ok(!scanOnly.html.includes("page.processQr.issueLabels"), "scan-only render must hide label issuance");
assert.ok(!scanOnly.html.includes("page.processQr.deleteSize"), "scan-only render must hide issued-label mutation");
assert.ok(scanOnly.html.includes("page.processQr.printAllIssued"), "scan-only render must retain issued-label printing");
assert.ok(scanOnly.html.includes("page.processQr.printThisSize:M"), "scan-only render must retain per-size printing");
assert.equal(scanOnly.apiCalls.length, 0, "rendering must not make mutation requests");

const manager = renderRole(true);
assert.ok(manager.html.includes("page.processQr.issueLabels"), "manager render must expose label issuance");
assert.ok(manager.html.includes("page.processQr.deleteSize"), "manager render must expose issued-label management");
assert.ok(manager.html.includes("page.processQr.printAllIssued"), "manager render must retain issued-label printing");
assert.equal(manager.apiCalls.length, 0, "rendering must not make mutation requests");

const exposedSource = pageSource.replaceAll("{canManagePayroll && (", "{true && (");

function makeIssuableHookShim() {
  let stateIndex = 0;
  const stateOverrides = new Map([
    [10, "po-1"],
    [12, "1"],
    [13, "LINE-1"],
    [14, "Line 1"],
    [19, 1],
  ]);
  return {
    ...React,
    useEffect: () => undefined,
    useMemo: factory => factory(),
    useRef: initial => ({ current: initial }),
    useState: initial => {
      stateIndex += 1;
      const initialValue = typeof initial === "function" ? initial() : initial;
      return [stateOverrides.has(stateIndex) ? stateOverrides.get(stateIndex) : initialValue, () => undefined];
    },
  };
}

function textContent(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textContent).join("");
  return textContent(node.props?.children);
}

function findElements(node, predicate, found = []) {
  if (node == null || typeof node === "boolean") return found;
  if (Array.isArray(node)) {
    for (const child of node) findElements(child, predicate, found);
    return found;
  }
  if (typeof node !== "object") return found;
  if (predicate(node)) found.push(node);
  findElements(node.props?.children, predicate, found);
  return found;
}

function exposedIssueButton(canManage, apiCalls) {
  const Page = loadPage(exposedSource, { canManage, react: makeIssuableHookShim(), apiCalls });
  const buttons = findElements(
    Page(),
    node => node.type === "button" && textContent(node).includes("page.processQr.issueLabels"),
  );
  assert.ok(buttons.length > 0, "test instrumentation must expose the real issuance handler");
  assert.equal(buttons[0].props.disabled, false, "handler fixture must contain a valid unissued label");
  return buttons[0];
}

const originalWindow = globalThis.window;
globalThis.window = { requestAnimationFrame: callback => callback() };
try {
  const managerCalls = [];
  await exposedIssueButton(true, managerCalls).props.onClick();
  assert.equal(managerCalls.length, 1, "the real manager handler must POST the valid label fixture");
  assert.equal(managerCalls[0][0], "/api/payroll/qr-labels/issue");

  const deniedCalls = [];
  await exposedIssueButton(false, deniedCalls).props.onClick();
  assert.equal(deniedCalls.length, 0, "the same real handler must not call the API for a scan-only user");
} finally {
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
}

assert.match(authGate, /prefix: "\/process-qr", perms: \["payroll\.scan", "\*"\]/);
assert.match(sidebar, /href: "\/process-qr"[^\n]+perms: \["payroll\.scan", "\*"\]/);

console.log("Payroll payable roles: scan-only render/handler denial and manager issuance controls passed");
