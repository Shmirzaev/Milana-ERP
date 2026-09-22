import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const warehouseKey = "/api/inventory/warehouses";
const source = fs.readFileSync(new URL("../src/app/(app)/inventory/page.tsx", import.meta.url), "utf8");
assert.match(
  source,
  /useSWR<any\[\]>\(\s*canEditItems && editingBatch \? "\/api\/inventory\/warehouses" : null,\s*fetcher,\s*\)/,
  "the warehouse directory must depend on an open batch editor",
);
assert.equal(
  [...source.matchAll(/\bwarehouses\b/g)].length,
  3,
  "warehouses must remain limited to the SWR binding, endpoint, and batch-editor selector",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

const item = {
  id: 1,
  sku: "FAB-1",
  name: "Cotton",
  category: "fabric",
  unit: "kg",
  default_cost: 2,
  reorder_level: 0,
  track_batch: true,
  is_active: true,
  composition: [],
};
const stockRow = {
  item_id: 1,
  item_sku: item.sku,
  item_name: item.name,
  category: item.category,
  unit: item.unit,
  quantity: 10,
  reserved_quantity: 2,
  available_quantity: 8,
};
const batch = {
  id: 11,
  item_id: 1,
  item_sku: item.sku,
  item_name: item.name,
  batch_no: "BATCH-11",
  quantity: 10,
  reserved_quantity: 2,
  available_quantity: 8,
  unit: "kg",
  cost_per_unit: 2,
  warehouse_id: 5,
  warehouse_name: "Stored Warehouse",
  qc_status: "pending",
};

function createHarness(withBatch) {
  const jsx = (type, props) => ({ type, props: props || {} });
  const states = [];
  const refs = [];
  const savedEffectDeps = [];
  let stateCursor = 0;
  let refCursor = 0;
  let effectCursor = 0;
  let pendingEffects = [];
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

  function useEffect(effect, deps) {
    const index = effectCursor++;
    const previous = savedEffectDeps[index];
    const changed = !previous || deps.some((value, itemIndex) => !Object.is(value, previous[itemIndex]));
    savedEffectDeps[index] = deps;
    if (changed) pendingEffects.push(effect);
  }

  function useSWR(key) {
    requests.push(key);
    const base = { error: undefined, isLoading: false, mutate: async () => {} };
    if (typeof key === "string" && key.startsWith("/api/inventory/stock?group=materials")) {
      return { ...base, data: { rows: [stockRow], total: 1 } };
    }
    if (key === "/api/inventory/items?group=materials&page_size=500") return { ...base, data: [item] };
    if (typeof key === "string" && key.startsWith("/api/inventory/batches?")) {
      return { ...base, data: { rows: withBatch ? [batch] : [], total: withBatch ? 1 : 0 } };
    }
    if (key === "/api/suppliers") return { ...base, data: [] };
    if (key === warehouseKey) return { ...base, data: [{ id: 5, name: "Directory Warehouse" }] };
    return { ...base, data: undefined };
  }

  const router = { push() {}, replace() {} };
  const searchParams = { get: () => null };
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: { useEffect, useMemo: (calculate) => calculate(), useRef, useState },
    "next/link": { default: "link" },
    "next/navigation": { useRouter: () => router, useSearchParams: () => searchParams },
    "lucide-react": Object.fromEntries(
      ["Archive", "Download", "Edit3", "PackageCheck", "Plus", "QrCode", "Search", "Trash2", "X"]
        .map((icon) => [icon, icon]),
    ),
    swr: { default: useSWR },
    "@/components/Modal": { default: "modal" },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/lib/useModelOptions": { modelOptionsByIdsFetcher() {}, modelOptionsByIdsKey: () => null },
    "@/lib/auth": { can: () => true, useMe: () => ({ me: { id: 7 } }) },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/PaginationControls": { default: "pagination" },
    "@/lib/i18n": { useT: () => ({ lang: "en", t: (key) => key }) },
    "@/lib/materialComposition": { compositionTotal: () => 0 },
    "@/lib/modelImages": { imagePreviewHref: (value) => value, storageThumbnailUrl: (value) => value },
    "@/lib/orderRef": { orderReference: () => "PO-1" },
    "@/components/DialogProvider": { useDialogs: () => ({ ask: async () => true, notify: async () => {} }) },
    "@/components/MaterialQrStickerModal": { default: "qr-modal" },
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
      assert.ok(pass++ < 10, "inventory component state did not settle");
      dirty = false;
      stateCursor = 0;
      refCursor = 0;
      effectCursor = 0;
      pendingEffects = [];
      requests = [];
      tree = Page();
      for (const effect of pendingEffects) effect();
    } while (dirty);
    return { tree, requests: [...requests] };
  }

  return { renderUntilStable };
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

function openEditor(withBatch) {
  const harness = createHarness(withBatch);
  const closed = harness.renderUntilStable();
  assert.equal(closed.requests.filter((key) => key === warehouseKey).length, 0);
  assert.doesNotMatch(textContent(closed.tree), /Directory Warehouse/);
  const editButton = find(closed.tree, (node) => node.type === "button" && node.props?.title === "btn.edit");
  assert.ok(editButton, "the actual inventory edit action must render");
  editButton.props.onClick();
  return harness.renderUntilStable();
}

const itemEditor = openEditor(false);
assert.equal(
  itemEditor.requests.filter((key) => key === warehouseKey).length,
  0,
  "item editing must not request a batch-only warehouse directory",
);
assert.ok(find(itemEditor.tree, (node) => node.type === "modal" && node.props?.open === true));

const batchEditor = openEditor(true);
assert.equal(
  batchEditor.requests.filter((key) => key === warehouseKey).length,
  1,
  "batch editing must request the warehouse directory exactly once",
);
assert.match(textContent(batchEditor.tree), /Directory Warehouse/);

console.log("Inventory warehouses: closed/item editor requests 1 -> 0; batch editor remains exactly 1.");
