import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import * as React from "react";
import * as jsx from "react/jsx-runtime";
import { renderToStaticMarkup as render } from "react-dom/server";

function load(path, dependencies = {}) {
  const exports = {};
  const compiled = ts.transpileModule(fs.readFileSync(path, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText;
  vm.runInNewContext(compiled, { exports, URLSearchParams, Intl, require: name => {
    if (name === "react") return React;
    if (name === "react/jsx-runtime") return jsx;
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }});
  return exports;
}
const nil = { default: () => null };
const card = { default: ({ children }) => React.createElement("article", null, children) };
const { priceWorkflowMessages } = load("src/lib/priceWorkflowMessages.ts");
const { localizeError } = load("src/lib/errorMessages.ts");
const printError = "Finance must enter the printing cost before confirmation";
assert.equal(localizeError(printError, 409, "en"), printError);
for (const lang of ["ru", "uz"]) {
  assert.notEqual(localizeError(printError, 409, lang), printError);
  assert.notEqual(localizeError(printError, 409, lang), localizeError("Unknown detail", 409, lang));
}
const request = { id: 1, revision: 2, workflow_state: "awaiting_finance", materials: [], accessories: [],
  printing_required: true, printing_cost: null, calculation_issues: ["printing_costs"], selling_price: 6, can_approve: true };
const pricing = {
  "@/components/PageHeader": nil, "@/components/price-calculation/PriceRequestCard": card, "./PriceRequestCard": card,
  "@/components/price-calculation/PriceRequestPagination": nil, "./PriceRequestPagination": nil,
  "@/components/price-calculation/PriceCostDetails": nil, "@/components/price-calculation/VariantPriceRegister": nil,
  "@/hooks/usePriceRequests": { usePriceRequests: () => ({ data: [request] }) }, "@/lib/api": { api: {} },
  "@/lib/auth": { useMe: () => ({ me: {} }), can: () => true },
  "@/lib/i18n": { useT: () => ({ lang: "en", t: value => value }) },
  "@/lib/priceCalculationRequests": { numberInputValue: value => value == null ? "" : String(value) },
  "@/lib/priceWorkflowMessages": { priceWorkflowMessages },
};
const Department = load("src/components/price-calculation/DepartmentPriceQueue.tsx", pricing).default;
const Finance = load("src/app/(app)/finance/price-calculation/page.tsx", pricing).default;
assert.ok(!render(React.createElement(Department, { team: "purchasing" })).includes("Printing USD"));
assert.ok(render(React.createElement(Finance)).includes("Printing USD / piece"));
assert.match(render(React.createElement(Finance)), /disabled=""[^>]*>Confirm price/);
request.printing_required = false;
assert.ok(!render(React.createElement(Finance)).includes("Printing USD"));

const deps = {
  "next/link": { default: ({ children, ...props }) => React.createElement("a", props, children) },
  "next/navigation": { useSearchParams: () => new URLSearchParams("stock_kind=second_grade") },
  swr: { default: () => ({ data: { cells: [], placements: [
    { id: 1, model_id: 42, model_code: "FG202001-V-6752", model_name: "No image", total_quantity: 576, package_count: 3, package_no: "PK-1" },
    { id: 2, model_id: null, model_code: "LEGACY-1", model_name: "Legacy", total_quantity: 1, package_no: "PK-2" },
  ] }, isLoading: false }) },
  "lucide-react": Object.fromEntries(["Boxes", "Grid2X2", "ImageOff", "PackageSearch", "Search", "Warehouse"].map(key => [key, () => null])),
  "@/lib/packageIdentity": { packageIdentityText: { en: {} }, sewingFactoryLabel: () => "" },
  "@/lib/variantDisplay": { formatModelVariantCode: value => value }, "@/lib/api": { fetcher: () => {} },
  "@/lib/auth": { useMe: () => ({ me: {} }), can: () => true },
  "@/lib/i18n": { useT: () => ({ lang: "en", t: value => value }) },
  "@/lib/firstGradeText": { firstGradeText: { en: {} } }, "@/lib/modelImages": { storageThumbnailUrl: value => value },
  "@/lib/warehouseWorkspace": { warehouseMatches: rows => rows, warehouseVariantKey: row => String(row.model_id || row.model_code), warehouseWorkspaceText: { en: {} } },
  "@/lib/orderRef": { formatOrderReference: () => "", rawOrderReference: () => "" },
  "@/components/StagePipeline": { statusLabel: value => value },
};
for (const name of ["SewingFactoryFilter", "DeleteWarehousePackage", "ReleasePackageCustomer", "PageHeader", "StocktakeLink", "WarehouseReportDownload", "WarehouseStockMap", "SearchableSelect"]) deps[`@/components/${name}`] = nil;
const Warehouse = load("src/app/(app)/warehouse-stock/page.tsx", deps).default;
const cards = [...render(React.createElement(Warehouse)).matchAll(/<article[\s\S]*?<\/article>/g)].map(match => match[0]);
assert.equal(cards.length, 2);
const known = cards.find(value => value.includes("No image"));
assert.match(known, /<a[^>]*href="\/warehouse-stock\/models\/42\?stock_kind=second_grade"/);
assert.ok(known.includes("absolute inset-0") && known.includes("focus-visible:-outline-offset-2"));
assert.ok(!known.includes("<button"));
const legacy = cards.find(value => value.includes("Legacy"));
assert.ok(!legacy.includes("/warehouse-stock/models/") && legacy.includes("<button"));
console.log("Finance print ownership, missing-print approval block and picture-less/legacy card navigation passed.");
