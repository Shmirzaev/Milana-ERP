import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/departments/[code]/page.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

function render(code, fixtures) {
  const requested = [];
  const buttons = [];
  const widgets = {};
  const mutations = [];
  const sizes = [];
  const noop = () => null;
  const t = (key, vars = {}) => key + (Object.keys(vars).length ? JSON.stringify(vars) : "");
  const pageResponse = { ready_to_ship: [], ready_to_ship_total: 0, ...fixtures.inbox };
  const dependencies = {
    react: React,
    "react/jsx-runtime": Object.fromEntries(Object.entries(jsxRuntime).map(([name, value]) => [name,
      ["jsx", "jsxs"].includes(name) ? (tag, props, ...rest) => {
        if (tag === "button") buttons.push(props);
        return value(tag, props, ...rest);
      } : value,
    ])),
    "next/link": { default: ({ children, href, ...props }) => React.createElement("a", { href, ...props }, children) },
    "next/navigation": { useParams: () => ({ code }), useRouter: () => ({ push() {} }) },
    swr: { default: key => ({ data: pageResponse, isLoading: false, mutate: () => mutations.push(key) }) },
    "swr/infinite": { default: getKey => {
      const first = getKey(0, null);
      const kind = !first ? "inactive" : first.includes("/cutting-orders") ? "cutting"
        : first.includes("/department-orders") ? "department"
        : first.includes("/awaiting-packaging") ? "awaiting"
        : first.includes("status=pending") ? "pending"
        : first.includes("status=ready") ? "ready" : "shipping";
      const data = first ? fixtures[kind] ?? [{ rows: [], total: 0, has_more: false, ...pageResponse }] : undefined;
      requested.push({ kind, first, getKey });
      return { data, isLoading: false, isValidating: false, size: data?.length ?? 1,
        setSize: size => sizes.push([kind, typeof size === "function" ? size(data?.length ?? 1) : size]),
        mutate: () => mutations.push(kind) };
    } },
    "@/lib/variantDisplay": { formatVariantNumber: value => value },
    "@/lib/errorMessages": { localizeError: value => value },
    "@/lib/api": { api: { post() {} }, fetcher() {} },
    "@/lib/auth": { useMe: () => ({ me: { factory_code: "MIL" } }) },
    "@/components/sewing/BandFloor": { default: noop },
    "@/lib/i18n": { useT: () => ({ t }) },
    "@/lib/modelImages": { imagePreviewHref: value => value, storageThumbnailUrl: value => value },
    "@/lib/orderRef": { orderReference: (row, fallback) => row.order_no || row.production_no || fallback },
    "@/components/StagePipeline": { statusLabel: value => value },
    "@/components/PageHeader": { default: noop },
    "@/components/StocktakeLink": { default: noop },
    "@/components/ImageThumbnail": { default: noop },
    "@/components/ReturnPackages": { default: props => { widgets.returns = props; return null; } },
    "@/components/ShipmentItemLines": { default: noop },
    "@/components/CuttingOrderList": { default: props => {
      widgets.cutting = props;
      return React.createElement("div", null, `Cutting ${props.total}: ${props.rows.map(row => row.production_no).join(",")}`);
    } },
    "@/components/DepartmentOrderList": { default: props => {
      widgets.department = props;
      return React.createElement("div", null, props.title);
    } },
  };
  const exports = {};
  new Function("exports", "require", compiled)(exports, name => {
    assert.ok(name in dependencies, `Unexpected dependency: ${name}`);
    return dependencies[name];
  });
  const html = renderToStaticMarkup(React.createElement(exports.default));
  return { requested, widgets, buttons, sizes, mutations, html };
}

for (const code of ["CUT", "ECT"]) {
  const result = render(code, { cutting: [
    { rows: [{ production_no: "First" }], total: 57, has_more: true },
    { rows: [{ production_no: "Second" }], total: 57, has_more: true },
  ] });
  assert.equal(result.widgets.cutting.total, 57);
  assert.equal(result.widgets.cutting.rows.length, 2);
  assert.equal(typeof result.widgets.cutting.onSearch, "function");
  const key = result.requested.find(row => row.kind === "cutting");
  assert.ok(key.first.includes(`dept=${code}&limit=50&offset=0&q=`));
  assert.ok(key.getKey(1, { has_more: true }).includes("offset=50"));
  assert.equal(key.getKey(2, { has_more: false }), null);
  assert.ok(!result.requested.some(row => row.kind === "department"));
  result.buttons.find(button => button.children === "common.loadMore").onClick();
  assert.deepEqual(result.sizes, [["cutting", 3]]);
}

const department = render("PRT", { department: [
  { rows: [{ production_order_id: 1, queue_kind: "pending" }], total: 61, has_more: true },
  { rows: [{ production_order_id: 2, queue_kind: "in_progress" }], total: 61, has_more: true },
] });
assert.match(department.widgets.department.title, /61/);
assert.deepEqual(department.widgets.department.rows.map(row => row.queueKind), ["pending", "in_progress"]);
department.buttons.find(button => button.children === "common.loadMore").onClick();
assert.deepEqual(department.sizes, [["department", 3]]);

const packaging = render("PKG", { awaiting: [
  { rows: [{ production_order_id: 1, production_batch_id: 11, batch_no: "Batch A", ready_qty: 5 }], total: 53, has_more: true },
  { rows: [{ production_order_id: 1, production_batch_id: 12, batch_no: "Batch B", ready_qty: 8 }], total: 53, has_more: true },
] });
assert.match(packaging.html, /Batch A/);
assert.match(packaging.html, /Batch B/);
assert.match(packaging.html, /2 \/ 53/);
assert.ok(packaging.requested.find(row => row.kind === "awaiting").first.includes("page_size=50"));
packaging.buttons.find(button => button.children === "common.loadMore").onClick();
assert.deepEqual(packaging.sizes, [["awaiting", 3]]);

const fgs = render("FGS", { shipping: [{ ready_to_ship: [{
  sales_order_id: 1, order_no: "SO-1", packages: 1, quantity: 5,
  shipment_id: 1, shipment_no: "SH-1", item_lines: [], package_lines: [],
}], ready_to_ship_total: 52 }], pending: [{ rows: [{ id: 1, production_order_id: 1, total_quantity: 5 }], total: 1, has_more: false }] });
assert.match(fgs.html, /52/);
const shipping = fgs.requested.find(row => row.kind === "shipping");
assert.ok(shipping.first.includes("ready_to_ship_limit=50&ready_to_ship_offset=0"));
assert.ok(shipping.getKey(1, { ready_to_ship_total: 52 }).includes("ready_to_ship_offset=50"));
assert.equal(shipping.getKey(2, { ready_to_ship_total: 52 }), null);
fgs.buttons.find(button => button.children === "common.loadMore").onClick();
assert.deepEqual(fgs.sizes, [["shipping", 2]]);
fgs.widgets.returns.onReturned();
assert.ok(fgs.mutations.includes("pending") && fgs.mutations.includes("shipping"));

console.log("Department React pages preserve exact totals, bounded keys, batch rows, load-more actions and mutation refresh.");

const cuttingSource = fs.readFileSync(new URL("../src/components/CuttingOrderList.tsx", import.meta.url), "utf8");
const cuttingCompiled = ts.transpileModule(cuttingSource, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
for (const serverSearch of [true, false]) {
  let stateIndex = 0;
  let searchForm;
  const queries = [];
  const deps = {
    react: { ...React, useState: initial => React.useState(stateIndex++ < 2 ? "needle" : initial) },
    "react/jsx-runtime": Object.fromEntries(Object.entries(jsxRuntime).map(([name, value]) => [name,
      ["jsx", "jsxs"].includes(name) ? (tag, props, ...rest) => {
        if (tag === "form") searchForm = props;
        return value(tag, props, ...rest);
      } : value,
    ])),
    "next/link": { default: ({ children, href, ...props }) => React.createElement("a", { href, ...props }, children) },
    "lucide-react": { Check: () => null },
    "@/lib/auth": { useMe: () => ({ me: { id: 1 } }), can: () => false },
    "@/lib/variantDisplay": { formatVariantNumber: value => value },
    "@/components/ImageThumbnail": { default: () => null },
    "@/components/StagePipeline": { statusLabel: value => value },
    "@/lib/orderRef": { orderReference: (row, fallback) => row.production_no || fallback },
  };
  const exports = {};
  new Function("exports", "require", cuttingCompiled)(exports, name => {
    assert.ok(name in deps, `Unexpected CuttingOrderList dependency: ${name}`);
    return deps[name];
  });
  const html = renderToStaticMarkup(React.createElement(exports.default, {
    rows: [{ id: 1, production_order_id: 1, production_no: "needle-order" },
      { id: 2, production_order_id: 2, production_no: "server-matched-alias" }],
    cuttingDepartment: "CUT", total: 57,
    ...(serverSearch ? { onSearch: query => queries.push(query) } : {}),
    t: (key, vars = {}) => key + JSON.stringify(vars),
  }));
  assert.match(html, /needle-order/);
  if (serverSearch) {
    assert.match(html, /server-matched-alias/);
    assert.match(html, /57/);
    searchForm.onSubmit({ preventDefault() {} });
    assert.deepEqual(queries, ["needle"]);
  } else {
    assert.ok(!html.includes("server-matched-alias"));
  }
}
console.log("Cutting list delegates whole-directory search while retaining its standalone local search behavior.");
