import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

function load(relative, dependencies = {}) {
  const source = fs.readFileSync(new URL(relative, import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  new Function("exports", "require", output)(exports, name => {
    assert.ok(name in dependencies, `Unexpected dependency: ${name}`);
    return dependencies[name];
  });
  return exports;
}

for (const lang of ["en", "ru", "uz"]) {
  const messages = load(`../src/lib/i18n/locales/${lang}-base.ts`).default;
  assert.ok(messages["home.stageActivity"]);
  assert.ok(messages["home.stageActivityHint"]);
  const { default: HomePage } = load("../src/app/(app)/page.tsx", {
    react: React, "react/jsx-runtime": jsxRuntime,
    swr: { default: key => ({ data: key?.startsWith("/api/dashboard/production")
      ? { cutting_output: 100, printing_output: 100, sewing_output: 100, packaging_output: 100 }
      : key === "/api/dashboard/active-production" ? [] : undefined }) },
    "lucide-react": { CalendarDays: () => null, Download: () => null, Factory: () => null, Plus: () => null, TrendingDown: () => null, TrendingUp: () => null },
    "@/lib/orderRef": { formatOrderReference: value => value },
    "@/lib/api": { fetcher() {} },
    "@/lib/auth": { useMe: () => ({ me: { id: 1 }, loading: false }), can: () => false },
    "@/lib/i18n": { useT: () => ({ t: key => messages[key] ?? key }) },
    "@/components/PageHeader": { default: () => null },
    "@/components/StagePipeline": { statusLabel: value => value },
    "@/components/dashboard/ManagementDashboard": { default: () => null },
  });
  const html = renderToStaticMarkup(React.createElement(HomePage));
  assert.ok(html.includes(messages["home.stageActivity"]));
  assert.ok(html.includes(messages["home.stageActivityHint"]));
  assert.match(html, />400</);
  assert.ok(!html.includes(messages["dash.production"]), "Stage totals must not be labeled finished output");
}
console.log("Home stage KPI: actual React page renders explicit activity label and warning in EN/RU/UZ");
