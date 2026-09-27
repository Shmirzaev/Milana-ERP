import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const orderKey = "/api/usluga/orders/12";
const modelKey = "/api/usluga/models/4";
const source = fs.readFileSync(new URL("../src/app/(app)/usluga/orders/[id]/edit/page.tsx", import.meta.url), "utf8");

assert.match(
  source,
  /const orderKey = id && canManage \? `\/api\/usluga\/orders\/\$\{id\}` : null;/,
  "the order detail must depend on edit authorization",
);
assert.match(
  source,
  /const selectedModelKey = canManage && modelId \? `\/api\/usluga\/models\/\$\{modelId\}` : null;/,
  "the dependent model detail must stop when edit authorization is absent",
);
assert.match(
  source,
  /if \(!me\)[\s\S]*?if \(!canManage\)[\s\S]*?if \(isLoading\)/,
  "authentication and denial must resolve before authorized request loading state",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function createHarness({ authorized, me = { id: 7 } }) {
  const jsx = (type, props) => ({ type, props: props || {} });
  const states = [];
  const refs = [];
  let stateCursor = 0;
  let refCursor = 0;
  let dirty = false;
  let requests = [];

  function useState(initial) {
    const index = stateCursor++;
    if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
    return [states[index], (next) => {
      const value = typeof next === "function" ? next(states[index]) : next;
      if (!Object.is(value, states[index])) dirty = true;
      states[index] = value;
    }];
  }

  function useRef(initial) {
    const index = refCursor++;
    if (!(index in refs)) refs[index] = { current: initial };
    return refs[index];
  }

  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      useEffect: (effect) => effect(),
      useMemo: (calculate) => calculate(),
      useRef,
      useState,
    },
    "next/link": { default: "link" },
    "next/navigation": {
      useParams: () => ({ id: "12" }),
      useRouter: () => ({ push() {}, refresh() {} }),
    },
    swr: {
      default: (key) => {
        requests.push(key);
        return {
          data: key === orderKey
            ? {
              id: 12,
              order_no: "USL-12",
              customer_name: "Client A",
              customer_reference: null,
              model_id: 4,
              planned_quantity: 10,
              deadline: null,
              material_description: null,
              material_usage_kg: null,
              material_notes: null,
              handed_over_at: null,
              items: [{ id: 1, color: "blue", size: "48", planned_quantity: 10 }],
              }
            : key === modelKey
              ? {
                id: 4,
                code: "MODEL-4",
                name: "Model 4",
                sizes: [{ id: 1, size: "48" }],
                colors: [{ id: 1, color_name: "blue" }],
                }
              : undefined,
          error: undefined,
          isLoading: false,
        };
      },
    },
    "lucide-react": { ArrowLeft: "arrow-left", Plus: "plus", Save: "save", Trash2: "trash" },
    "@/components/ModelAsyncSelect": { default: "model-select" },
    "@/components/PageHeader": { default: "page-header" },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/lib/auth": { can: () => authorized, useMe: () => ({ me }) },
    "@/lib/garmentSizes": { GARMENT_SIZE_OPTIONS: ["46", "48", "50"] },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/lib/orderRef": { formatOrderReference: (value) => value },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);
  const Page = loadedModule.exports.default;

  function render() {
    stateCursor = 0;
    refCursor = 0;
    dirty = false;
    requests = [];
    const tree = Page();
    return { tree, requests: requests.filter(Boolean), dirty };
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

function textContent(tree) {
  const values = [];
  visit(tree, (node) => {
    if (typeof node === "string" || typeof node === "number") values.push(String(node));
  });
  return values.join(" ");
}

const authorized = createHarness({ authorized: true });
authorized.render();
const settled = authorized.render();
assert.deepEqual(settled.requests, [orderKey, modelKey], "authorized editing must retain both dependent detail keys");
assert.match(textContent(settled.tree), /USL-12/);
assert.doesNotMatch(textContent(settled.tree), /usluga\.accessDenied/);

const denied = createHarness({ authorized: false }).render();
assert.deepEqual(denied.requests, [], "denied editing must not request hidden order or model details");
assert.match(textContent(denied.tree), /usluga\.accessDenied/);
assert.doesNotMatch(textContent(denied.tree), /USL-12|Client A|MODEL-4/);

const unresolved = createHarness({ authorized: false, me: null }).render();
assert.deepEqual(unresolved.requests, [], "unresolved authentication must not start protected detail requests");
assert.match(textContent(unresolved.tree), /common\.loading/);

console.log("Usluga edit details: denied keys 2 -> 0; authorized keys remain 2; unresolved auth remains 0.");
