import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const readyStockKey = "/api/sales-orders/ready-stock-options";
const source = fs.readFileSync(new URL("../src/app/(app)/sales-orders/new/page.tsx", import.meta.url), "utf8");
assert.match(
  source,
  /useSWR<ReadyStockOption\[\]>\(\s*isBrandedOrder \? "\/api\/sales-orders\/ready-stock-options" : null,\s*fetcher,\s*\)/,
  "the ready-stock directory must be gated by the branded-order branch",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

const jsx = (type, props) => ({ type, props: props || {} });
const states = [];
const effectDeps = [];
let stateCursor = 0;
let effectCursor = 0;
let effects = [];
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

function useEffect(effect, deps) {
  const index = effectCursor++;
  const previous = effectDeps[index];
  const changed = !previous || deps.some((value, itemIndex) => !Object.is(value, previous[itemIndex]));
  effectDeps[index] = deps;
  if (changed) effects.push(effect);
}

function useSWR(key) {
  requests.push(key);
  if (key === "/api/brands") return { data: [] };
  if (key === readyStockKey) {
    return {
      data: [{ model_id: 4, brand_id: null, pack_count: 2, quantity: 120 }],
      error: undefined,
      isLoading: false,
    };
  }
  if (key === "model-options:4") {
    return { data: [{ id: 4, code: "MODEL-4", name: "Model 4" }] };
  }
  return { data: undefined, error: undefined, isLoading: false };
}

const dependencies = {
  "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
  react: { useEffect, useMemo: (calculate) => calculate(), useState },
  swr: { default: useSWR },
  "lucide-react": { ArrowLeft: "arrow-left", Plus: "plus", Trash2: "trash" },
  "@/lib/api": { api: {}, fetcher() {} },
  "@/lib/useModelOptions": {
    modelOptionsByIdsFetcher() {},
    modelOptionsByIdsKey(ids) {
      const selected = [...new Set(ids.map(Number).filter((id) => id > 0))];
      return selected.length ? `model-options:${selected.join(",")}` : null;
    },
  },
  "@/components/PageHeader": { default: "page-header" },
  "@/components/Modal": { default: "modal" },
  "@/components/ModelAsyncSelect": { default: "model-select" },
  "@/components/SearchableSelect": { default: "searchable-select" },
  "@/components/CustomerAsyncSelect": { default: "customer-select" },
  "@/lib/auth": { can: () => true, useMe: () => ({ me: { id: 1 } }) },
  "@/lib/i18n": { useT: () => ({ lang: "en", t: (key) => key }) },
  "@/lib/readySalesLocale": {
    readySalesText: () => new Proxy({}, { get: (_target, property) => String(property) }),
  },
  "@/lib/garmentSizes": { GARMENT_SIZE_OPTIONS: ["46", "48"] },
  "@/lib/numberInput": {
    numberOrZero: (value) => Number(value || 0),
    parseNumberInput: (value) => value,
  },
  "@/lib/modelVariants": {
    groupModelVariants: (models) => models.map((model) => ({
      key: `model-${model.id}`,
      variants: [model],
    })),
    modelGroupLabel: (group) => group.key,
    modelOrderLabel: (model) => model.code,
    modelVariantGroupKey: (model) => `model-${model.id}`,
    modelVariantLabel: (option) => option.label,
    modelVariantOption: (model) => ({ label: model.code }),
  },
};

const loadedModule = { exports: {} };
new Function("require", "exports", "module", compiled)((name) => {
  assert.ok(name in dependencies, `Unexpected dependency ${name}`);
  return dependencies[name];
}, loadedModule.exports, loadedModule);
const Page = loadedModule.exports.default;

function renderUntilStable() {
  let tree;
  let pass = 0;
  do {
    assert.ok(pass++ < 8, "component state did not settle");
    dirty = false;
    stateCursor = 0;
    effectCursor = 0;
    effects = [];
    requests = [];
    tree = Page();
    for (const effect of effects) effect();
  } while (dirty);
  return { tree, requests: [...requests] };
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

function findOrderTypeSelect(tree) {
  let match = null;
  visit(tree, (node) => {
    if (!match && node?.type === "select" && ["client_order", "branded_stock_sale"].includes(node.props?.value)) {
      match = node;
    }
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

const clientOrder = renderUntilStable();
assert.equal(
  clientOrder.requests.filter((key) => key === readyStockKey).length,
  0,
  "the default client-order branch must not request the hidden ready-stock directory",
);
assert.doesNotMatch(textContent(clientOrder.tree), /newso\.modelsInStorage/);

const orderTypeSelect = findOrderTypeSelect(clientOrder.tree);
assert.ok(orderTypeSelect, "the rendered order-type control must remain available");
orderTypeSelect.props.onChange({ target: { value: "branded_stock_sale" } });

const brandedOrder = renderUntilStable();
assert.equal(
  brandedOrder.requests.filter((key) => key === readyStockKey).length,
  1,
  "the branded-order branch must request the ready-stock directory exactly once",
);
assert.match(textContent(brandedOrder.tree), /newso\.modelsInStorage/);

console.log("Sales-order ready stock: client-order requests 1 -> 0; branded-order remains exactly 1.");
