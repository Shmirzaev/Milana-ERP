import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const positionKey = "/api/hr/positions";
const source = fs.readFileSync(new URL("../src/app/(app)/hr/employees/page.tsx", import.meta.url), "utf8");

assert.match(
  source,
  /const positionDirectoryKey = editing !== null \|\| employees\.some\(\(employee\) => employee\.hr_position_id != null\)[\s\S]*?\? "\/api\/hr\/positions"[\s\S]*?: null;/,
  "the staffing-position directory must depend on an active editor or referenced row",
);
assert.match(
  source,
  /positions\?\.find\(\(row\) => row\.id === employee\.hr_position_id\)\?\.name \|\| employee\.position \|\| "—"/,
  "the visible position label fallback must remain unchanged",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function createHarness({ employees, denied = false }) {
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
    react: { useEffect: (callback) => callback(), useMemo: (calculate) => calculate(), useState },
    swr: {
      default: (key) => {
        requests.push(key);
        return {
          data: key === "/api/employees?page=1&page_size=50&search=" && employees
            ? { rows: employees, total: employees.length, page: 1, page_size: 50, has_more: false, active_total: employees.length, inactive_total: 0, profile_coverage_percent: null, search: "" }
            : key === "/api/departments"
              ? [{ id: 2, name: "Cutting" }]
              : key === positionKey
                ? [{ id: 3, name: "Senior Cutter" }]
                : undefined,
          error: key === "/api/employees?page=1&page_size=50&search=" && denied ? new Error("403 forbidden") : undefined,
          isLoading: false,
          mutate() {},
        };
      },
    },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/components/Modal": { default: "modal" },
    "@/components/hr/HrUi": { HrHeader: "hr-header", LoadState: "load-state", MetricGrid: "metric-grid" },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);
  const Page = loadedModule.exports.default;

  function render() {
    stateCursor = 0;
    requests = [];
    Page(); // The paged screen copies the fetched page into state in an effect.
    stateCursor = 0;
    requests = [];
    const tree = Page();
    return { requests: requests.filter(Boolean), tree };
  }

  return { render };
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

function find(tree, predicate) {
  let match = null;
  visit(tree, (node) => {
    if (!match && typeof node === "object" && predicate(node)) match = node;
  });
  return match;
}

function textContent(tree) {
  const values = [];
  visit(tree, (node) => {
    if (typeof node === "string" || typeof node === "number") values.push(String(node));
  });
  return values.join(" ");
}

const baseEmployee = {
  id: 5,
  factory_code: "MIL",
  employee_no: "5",
  full_name: "Employee Five",
  department_id: 2,
  position: "Operator",
  phone: null,
  salary: null,
  status: "active",
  joined_at: null,
  manager_employee_id: null,
  hr_position_id: null,
  hr_profile_json: {},
};

const referenced = createHarness({ employees: [{ ...baseEmployee, hr_position_id: 3 }] }).render();
assert.equal(referenced.requests.filter((key) => key === positionKey).length, 1);
assert.match(textContent(referenced.tree), /Employee Five/);
assert.match(textContent(referenced.tree), /Senior Cutter/);

const closedHarness = createHarness({ employees: [baseEmployee] });
const closed = closedHarness.render();
assert.equal(closed.requests.filter((key) => key === positionKey).length, 0);
assert.match(textContent(closed.tree), /Employee Five/);
assert.match(textContent(closed.tree), /Operator/);
const header = find(closed.tree, (node) => node.type === "hr-header");
assert.ok(header, "the employee header must render");
const addButton = find(header.props.actions, (node) => node.type === "button" && node.props?.children === "Add employee");
assert.ok(addButton, "the Add employee action must remain available");
addButton.props.onClick();
const open = closedHarness.render();
assert.equal(open.requests.filter((key) => key === positionKey).length, 1);
assert.match(textContent(open.tree), /Senior Cutter/);

const denied = createHarness({ employees: undefined, denied: true }).render();
assert.equal(denied.requests.filter((key) => key === positionKey).length, 0);
const deniedState = find(denied.tree, (node) => node.type === "load-state");
assert.equal(deniedState?.props?.error?.message, "403 forbidden");
assert.doesNotMatch(textContent(denied.tree), /Senior Cutter|Employee Five/);

console.log("HR employee positions: closed/denied key 1 -> 0; referenced row and open editor remain exactly 1.");
