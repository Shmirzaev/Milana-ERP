import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import * as React from "react";
import * as runtime from "react/jsx-runtime";
import { renderToStaticMarkup } from "react-dom/server";
import { runtimeMessages } from "./runtime-locales.mjs";

function load(path, dependencies = {}) {
  const exports = {};
  const compiled = ts.transpileModule(fs.readFileSync(path, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(compiled, { exports, URLSearchParams, require: name => {
    if (name === "react") return React;
    if (name === "react/jsx-runtime") return runtime;
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }});
  return exports;
}
const { packagingAvailabilityText } = load("src/lib/packagingAvailabilityText.ts");
const ProductInfo = load("src/components/WorkOrderProductInfo.tsx", {
  "@/lib/variantDisplay": { formatModelVariantCode: value => value },
  "@/lib/errorMessages": { localizeError: value => value },
  "@/lib/modelComposition": { formatModelComposition: () => "" },
  "@/lib/modelImages": { imagePreviewHref: value => value, isPreviewModelImage: () => false, storageThumbnailUrl: value => value },
  "@/lib/orderRef": { orderReference: () => "PO-TEST" },
}).default;
const expected = {
  en: ["Packaging input recorded", "Packaging output recorded", "Available for Packaging"],
  ru: ["Учтено на входе упаковки", "Учтённый выпуск упаковки", "Доступно для упаковки"],
  uz: ["Qadoqlashga kirim qayd etilgan", "Qadoqlash chiqimi qayd etilgan", "Qadoqlash uchun mavjud"],
};
for (const language of ["en", "ru", "uz"]) {
  const messages = runtimeMessages(language);
  const t = key => messages.get(key) || key;
  const renderInfo = wo => renderToStaticMarkup(React.createElement(ProductInfo, { t, wo }));
  for (const input of [0, 71]) {
    const html = renderInfo({ operation: "packaging", actual_input_qty: input, received_bundle_count: 2, received_bundle_qty: 17 });
    assert.ok(html.includes(expected[language][0]), `${language}: Packaging input must not be called received bundles`);
    assert.match(html, new RegExp(`<div class="font-medium">${input} `));
    assert.ok(!html.includes(`2 ${t("nav.bundles").toLowerCase()}`));
    assert.ok(!html.includes(`>${t("field.received")}<`));
  }
  // Genuine Sewing receipt and other receipt projections retain their values/text.
  for (const operation of ["sewing", "printing"]) {
    const html = renderInfo({ operation, actual_input_qty: 500, received_bundle_count: 2, received_bundle_qty: 70 });
    assert.ok(html.includes(`>${t("field.received")}<`));
    assert.ok(html.includes(`2 ${t("nav.bundles").toLowerCase()} / 70 ${t("field.qty").toLowerCase()}`));
    assert.ok(!html.includes(expected[language][0]));
  }
  const queueRows = [{ work_order_id: 8, production_order_id: 4, order_no: "PO-TEST", received_quantity: 240,
    packed_quantity: 75, remaining_quantity: 240, last_received_at: "2026-11-14T08:00:00Z" }];
  const Queue = load("src/app/(app)/packaging/queue/page.tsx", {
    "next/navigation": { useSearchParams: () => new URLSearchParams() },
    "next/link": { default: props => React.createElement("a", props) },
    swr: { default: () => ({ data: queueRows, isLoading: false }) },
    "lucide-react": Object.fromEntries(["Search", "PackageOpen", "RefreshCw", "ArrowRight"].map(key => [key, () => null])),
    "@/components/PageHeader": { default: props => React.createElement("p", null, props.subtitle) },
    "@/lib/i18n": { useT: () => ({ lang: language, t }) },
    "@/lib/auth": { useMe: () => ({ me: {} }) },
    "@/lib/access": { packagingDepartmentForSession: () => "PKG" },
    "@/lib/packagingAvailabilityText": { packagingAvailabilityText },
    "@/lib/api": {},
    "@/lib/variantDisplay": { formatVariantNumber: value => value },
    "@/lib/orderRef": { formatOrderReference: value => value },
    "@/lib/modelImages": {},
  }).default;
  const html = renderToStaticMarkup(React.createElement(Queue));
  assert.ok(html.includes(expected[language][1]));
  assert.ok(html.includes(expected[language][2]));
  assert.ok(html.includes(packagingAvailabilityText[language].output));
  assert.match(html, /awaiting labels|ожидающий этикеток|yorliq kutayotgan/);
  assert.match(html, /not yet packed|ещё не упакованные|hali qadoqlanmagan/);
  // Legacy 75 packed-but-unlabelled + 165 new input stays 240, not an inferred subtraction.
  assert.match(html, /tabular-nums">240<\/td>/);
  assert.match(html, /tabular-nums">75<\/td>/);
  assert.match(html, /text-\[#14110b\]">240<\/td>/);
  assert.doesNotMatch(html, /<td[^>]*>165<\/td>/);
}
console.log("PASS: EN/RU/UZ actual Packaging header/queue distinguish input, output and availability; Sewing receipts and all quantities preserved.");
