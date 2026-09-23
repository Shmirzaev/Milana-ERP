import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const departmentKey = "/api/departments";
const source = fs.readFileSync(new URL("../src/app/(app)/process-qr/page.tsx", import.meta.url), "utf8");
const pickerSource = fs.readFileSync(new URL("../src/components/PaidProcessPicker.tsx", import.meta.url), "utf8");

assert.match(
  source,
  /employeeDirectoryActive \? "\/api\/employees" : null/,
  "the employee directory must depend on an expanded employee section",
);
assert.match(
  source,
  /employeeDirectoryActive && employees\.some\(\(employee\) => employee\.department_id != null\)/,
  "the department directory must depend on an active employee directory carrying department references",
);
assert.match(
  source,
  /active=\{!collapsedSections\.paidOperations\}/,
  "the paid-process picker must receive the visible-section state without being unmounted",
);
assert.match(
  source,
  /department \? `\$\{department\.code \? `\$\{department\.code\} - ` : ""\}\$\{department\.name\}` : "-"/,
  "employee department labels and their fallback must remain unchanged",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function createHarness(employeeResult) {
  const jsx = (type, props) => ({ type, props: props || {} });
  const states = [];
  let stateCursor = 0;
  let requests = [];
  function useState(initial) {
    const index = stateCursor++;
    if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
    return [states[index], (next) => {
      states[index] = typeof next === "function" ? next(states[index]) : next;
    }];
  }
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      useEffect() {},
      useMemo: (calculate) => calculate(),
      useRef: (initial) => ({ current: initial }),
      useState,
    },
    "next/link": { default: "link" },
    swr: {
      default: (key) => {
        requests.push(key);
        const data = key === "/api/employees"
          ? employeeResult
          : key === departmentKey
            ? [{ id: 2, code: "CUT", name: "Cutting" }]
            : key === "/api/sewing-flows"
              ? []
              : key?.startsWith("/api/process-tracking?")
                ? []
                : undefined;
        return {
          data,
          error: key === "/api/employees" && employeeResult === undefined ? new Error("403 forbidden") : undefined,
          isLoading: false,
          mutate() {},
        };
      },
    },
    qrcode: { default: { toDataURL: async () => "" } },
    "lucide-react": Object.fromEntries([
      "ArrowDown", "ArrowUp", "CheckSquare", "ChevronDown", "Pencil", "Plus", "Printer", "QrCode",
      "RefreshCw", "Save", "Search", "Trash2", "Users",
    ].map((name) => [name, name])),
    "@/lib/api": { api: {}, fetcher() {} },
    "@/lib/batchSerial": { formatBatchSerial: () => "Batch" },
    "@/lib/orderRef": { orderReference: () => "Order", formatOrderReference: (value) => value },
    "@/lib/numberInput": { parseNumberInput: (value) => value },
    "@/lib/processQrLabelIdentity": {
      buildOperationLabelTokens: () => new Map(),
      buildIssuedOperationNumbers: () => new Map(),
      correctedOperationIdentityNeedsReview: () => false,
    },
    "@/lib/auth": { can: () => true, useMe: () => ({ me: { id: 1, factory_code: "MIL" } }) },
    "@/lib/modelPaidOperations": {
      clonePaidOperations: () => [],
      createPaidOperation: () => ({}),
      materializeLegacyPaidOperations: () => [],
      paidOperationFactoryFromDepartmentCode: () => "milana",
      paidOperationMatchesFactory: () => true,
      paidOperationsFromDetails: () => [],
      SECTION_BADGES: {},
      VALID_SECTIONS: [],
      samePaidProcess: () => false,
      serializePaidOperations: () => [],
    },
    "@/components/PaidProcessPicker": { default: "paid-process-picker" },
    "@/components/ManualModelSizes": { default: "manual-model-sizes" },
    "@/lib/paidProcessSections": { paidSectionLabel: (value) => value },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/DialogProvider": { useDialogs: () => ({ ask: async () => false, notify: async () => {} }) },
    "@/components/Modal": { default: "modal" },
    "@/lib/i18n": { useT: () => ({ t: (key) => key, lang: "en" }) },
    "@/lib/modelVariants": { modelVariantOption: () => ({ label: "", variantNo: "" }) },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);
  const Page = loadedModule.exports.default;
  return {
    render() {
      stateCursor = 0;
      requests = [];
      const tree = Page();
      return { requests: requests.filter(Boolean), tree };
    },
  };
}

function visit(tree, callback) {
  if (tree === null || tree === undefined || typeof tree === "boolean") return;
  if (Array.isArray(tree)) {
    for (const child of tree) visit(child, callback);
    return;
  }
  if (typeof tree !== "object") {
    callback(tree);
    return;
  }
  callback(tree);
  visit(tree.props?.children, callback);
}

function textContent(tree) {
  const values = [];
  visit(tree, (node) => {
    if (typeof node === "string" || typeof node === "number") values.push(String(node));
  });
  return values.join(" ");
}

function sectionToggles(tree) {
  const toggles = [];
  visit(tree, (node) => {
    if (typeof node === "object" && node.type === "button" && typeof node.props?.["aria-expanded"] === "boolean") {
      toggles.push(node);
    }
  });
  return toggles;
}

const employeeWithDepartment = {
  id: 5,
  employee_no: "EMP-5",
  full_name: "Employee Five",
  position: "Cutter",
  status: "active",
  department_id: 2,
};
const withDepartmentHarness = createHarness([employeeWithDepartment]);
const closed = withDepartmentHarness.render();
assert.equal(closed.requests.filter((key) => key === "/api/employees").length, 0);
assert.equal(closed.requests.filter((key) => key === departmentKey).length, 0);
assert.doesNotMatch(textContent(closed.tree), /Employee Five|CUT - Cutting/);
const closedToggles = sectionToggles(closed.tree);
assert.equal(closedToggles.length, 4, "all four actual collapsible section controls must render");
closedToggles[1].props.onClick();

const withDepartment = withDepartmentHarness.render();
assert.equal(withDepartment.requests.filter((key) => key === "/api/employees").length, 1);
assert.equal(withDepartment.requests.filter((key) => key === departmentKey).length, 1);
assert.match(textContent(withDepartment.tree), /Employee Five/);
assert.match(textContent(withDepartment.tree), /CUT - Cutting/);

const withoutDepartmentHarness = createHarness([{
  id: 6,
  employee_no: "EMP-6",
  full_name: "Employee Six",
  position: "Operator",
  status: "active",
  department_id: null,
}]);
sectionToggles(withoutDepartmentHarness.render().tree)[1].props.onClick();
const withoutDepartment = withoutDepartmentHarness.render();
assert.equal(withoutDepartment.requests.filter((key) => key === "/api/employees").length, 1);
assert.equal(withoutDepartment.requests.filter((key) => key === departmentKey).length, 0);
assert.match(textContent(withoutDepartment.tree), /Employee Six/);

const deniedHarness = createHarness(undefined);
sectionToggles(deniedHarness.render().tree)[1].props.onClick();
const denied = deniedHarness.render();
assert.equal(denied.requests.filter((key) => key === "/api/employees").length, 1);
assert.equal(denied.requests.filter((key) => key === departmentKey).length, 0);
assert.match(textContent(denied.tree), /403 forbidden/);
assert.doesNotMatch(textContent(denied.tree), /Employee Five|CUT - Cutting/);

const pickerCompiled = ts.transpileModule(pickerSource, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function renderPicker({ active, authorized }) {
  const requests = [];
  const jsx = (type, props) => ({ type, props: props || {} });
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      useEffect() {},
      useRef: (initial) => ({ current: initial }),
      useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
    },
    swr: { default: (key) => { requests.push(key); return { data: { items: [], has_more: false }, mutate() {} }; } },
    "lucide-react": { Plus: "plus" },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/lib/auth": { can: () => authorized, useMe: () => ({ me: { id: 1 } }) },
    "@/lib/i18n": { useT: () => ({ t: (key) => key, lang: "en" }) },
    "@/lib/modelPaidOperations": { VALID_SECTIONS: [], samePaidProcess: () => false },
    "@/lib/paidProcessSections": { paidSectionLabel: (value) => value },
    "@/components/SearchableSelect": { default: "searchable-select" },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", pickerCompiled)((name) => {
    assert.ok(name in dependencies, `Unexpected picker dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);
  loadedModule.exports.default({ active, existing: [], onSelect() {} });
  return requests.filter(Boolean);
}

assert.deepEqual(renderPicker({ active: false, authorized: true }), []);
assert.deepEqual(renderPicker({ active: true, authorized: false }), []);
assert.deepEqual(renderPicker({ active: true, authorized: true }), ["/api/paid-processes?search="]);

console.log("Process QR directories: collapsed employees/paid processes stay dormant; expanded and denied paths retain exact behavior.");
