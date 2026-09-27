import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const page = readFileSync(
  new URL("../src/app/(app)/sales-orders/new/page.tsx", import.meta.url),
  "utf8",
);
const localeSources = ["en", "ru", "uz"].map((language) => readFileSync(
  new URL(`../src/lib/i18n/locales/${language}-base.ts`, import.meta.url),
  "utf8",
));

assert.match(
  page,
  /<SearchableSelect<number>[\s\S]*options=\{availableModelSelectOptions\}/,
  "Branded-stock models must use the typed searchable selector.",
);
assert.match(
  page,
  /searchText: `\$\{group\.label\} \$\{modelOrderLabel\(item\.model\)\}`/,
  "Branded-stock searches must include the model-family and variant identity.",
);
assert.doesNotMatch(
  page,
  /<optgroup key=\{group\.key\}/,
  "The unsearchable native branded-stock model list must not return.",
);
assert.match(
  page,
  /canCreateCustomer = can\(me, "sales\.customers"\)/,
  "The add-customer action must follow the backend customer permission.",
);
assert.match(
  page,
  /api\.post<Customer>\("\/api\/customers", customerDraft\)/,
  "The sales-order form must create customers through the authorized customer endpoint.",
);
assert.match(
  page,
  /setCustomerId\(created\.id\)/,
  "A newly created customer must be selected without discarding the order draft.",
);
assert.match(
  page,
  /async function selectLineModel[\s\S]*`\/api\/models\/\$\{modelId\}\/selling-price`[\s\S]*line\.model_id === modelId[\s\S]*unit_price: parsedPrice/,
  "Selecting an exact model variant must fetch and autofill only that variant's selling price.",
);
assert.match(
  page,
  /unit_price: submittedUnitPrice\(line\)/,
  "Sales Order submission must preserve whether the user explicitly edited the price.",
);
const priceSource = readFileSync(new URL("../src/lib/salesOrderPriceProvenance.ts", import.meta.url), "utf8");
const priceExports = {};
new Function("exports", ts.transpileModule(priceSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText)(priceExports);
assert.equal(priceExports.submittedUnitPrice({ unit_price: "", price_edited: false }), null);
assert.equal(priceExports.submittedUnitPrice({ unit_price: "12.5", price_edited: false }), null);
assert.equal(priceExports.submittedUnitPrice({ unit_price: "12.5", price_edited: true }), 12.5);
assert.equal(priceExports.submittedUnitPrice({ unit_price: 0, price_edited: true }), 0);
for (const localeSource of localeSources) {
  assert.match(
    localeSource,
    /"newso\.addCustomer":/,
    "Every runtime locale must translate the add-customer action.",
  );
  assert.match(
    localeSource,
    /"newso\.customerCreateFailed":/,
    "Every runtime locale must translate customer-creation failures.",
  );
}

console.log("Sales-order searchable selection contract passed.");
