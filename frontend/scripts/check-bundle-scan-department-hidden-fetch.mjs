import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const departmentKey = "/api/departments";
const source = fs.readFileSync(new URL("../src/components/BundleScanPanel.tsx", import.meta.url), "utf8");
const pageSource = fs.readFileSync(new URL("../src/app/(app)/bundles/scan/page.tsx", import.meta.url), "utf8");

assert.match(pageSource, /<BundleScanPanel scope="all" \/>/, "the general scan page must mount the tested panel");
assert.match(
  source,
  /const departmentDirectoryKey = bundle && \(\s*bundle\.current_department_id != null \|\| bundle\.next_department_id != null\s*\) \? "\/api\/departments" : null;/,
  "the department directory must depend on a scanned bundle carrying department references",
);
assert.match(
  source,
  /<strong>\{departmentLabel\(bundle\.current_department_id\)\}<\/strong>[\s\S]*<strong>\{departmentLabel\(bundle\.next_department_id\)\}<\/strong>/,
  "current and next department rendering must remain intact",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function createHarness({ lookupResult, lookupError }) {
  const requests = [];
  const states = [];
  const refs = [];
  let stateCursor = 0;
  let refCursor = 0;
  const jsx = (type, props) => ({ type, props: props || {} });
  const react = {
    useCallback: (callback) => callback,
    useEffect() {},
    useMemo: (calculate) => calculate(),
    useRef(initial) {
      const index = refCursor++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index];
    },
    useState(initial) {
      const index = stateCursor++;
      if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
      return [states[index], (next) => {
        states[index] = typeof next === "function" ? next(states[index]) : next;
      }];
    },
  };
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react,
    swr: {
      default: (key) => {
        requests.push(key);
        return {
          data: key === departmentKey
            ? [
                { id: 2, code: "CUT", name: "Cutting" },
                { id: 3, code: "PRT", name: "Printing" },
              ]
            : undefined,
          isLoading: false,
          mutate: async () => {},
        };
      },
    },
    "next/navigation": { useSearchParams: () => new URLSearchParams() },
    "lucide-react": Object.fromEntries([
      "AlertCircle", "ArrowRight", "CheckCircle2", "Keyboard", "Loader2", "Printer", "QrCode",
      "RefreshCw", "RotateCcw", "ScanLine", "Search",
    ].map((name) => [name, name])),
    "@/lib/api": {
      api: {
        get: async () => {
          if (lookupError) throw lookupError;
          return lookupResult;
        },
        post: async () => ({}),
        openLabel() {},
      },
      fetcher() {},
    },
    "@/lib/orderRef": { formatOrderReference: (value) => value },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/FabricThumbnail": { default: "fabric-thumbnail" },
    "@/components/Modal": { default: "modal" },
    "@/components/StagePipeline": { statusLabel: (value) => value },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/lib/auth": {
      can: () => true,
      useMe: () => ({ me: { id: 1, factory_code: "MIL" } }),
    },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);

  return {
    requests,
    render() {
      stateCursor = 0;
      refCursor = 0;
      return loadedModule.exports.default({ scope: "all" });
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

function find(tree, predicate) {
  let result;
  visit(tree, (node) => {
    if (result === undefined && typeof node === "object" && predicate(node)) result = node;
  });
  return result;
}

function textContent(tree) {
  const values = [];
  visit(tree, (node) => {
    if (typeof node === "string" || typeof node === "number") values.push(String(node));
  });
  return values.join(" ");
}

async function scan(harness, code) {
  let tree = harness.render();
  const input = find(tree, (node) => node.type === "input" && node.props.id === "bundle-scan-all");
  assert.ok(input, "the real scan input must render");
  input.props.onChange({ target: { value: code } });
  tree = harness.render();
  const form = find(tree, (node) => node.type === "form" && typeof node.props.onSubmit === "function");
  assert.ok(form, "the real scan form must render");
  form.props.onSubmit({ preventDefault() {} });
  await new Promise((resolve) => setTimeout(resolve, 0));
  return harness.render();
}

globalThis.window = {
  location: { origin: "http://localhost", href: "http://localhost/bundles/scan" },
  setTimeout(callback) { callback(); },
};

const successful = createHarness({
  lookupResult: {
    id: 10,
    bundle_no: "B-10",
    model_code: "MODEL-10",
    status: "created",
    quantity: 20,
    current_department_id: 2,
    next_department_id: 3,
  },
});
let successfulTree = successful.render();
assert.equal(successful.requests.filter((key) => key === departmentKey).length, 0);
assert.match(textContent(successfulTree), /page\.bundleScan\.waitingTitle/);
successfulTree = await scan(successful, "B-10");
assert.equal(successful.requests.filter((key) => key === departmentKey).length, 1);
assert.match(textContent(successfulTree), /B-10/);
assert.match(textContent(successfulTree), /CUT - Cutting/);
assert.match(textContent(successfulTree), /PRT - Printing/);

const denied = createHarness({ lookupError: new Error("403 forbidden") });
const deniedTree = await scan(denied, "DENIED");
assert.equal(denied.requests.filter((key) => key === departmentKey).length, 0);
assert.match(textContent(deniedTree), /403 forbidden/);
assert.doesNotMatch(textContent(deniedTree), /CUT - Cutting|PRT - Printing/);

console.log("Bundle scan departments: empty/denied key 1 -> 0; scanned referenced-department key remains exactly 1.");
