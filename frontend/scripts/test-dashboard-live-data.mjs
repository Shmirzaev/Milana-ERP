import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

function load(relative, dependencies = {}) {
  const output = ts.transpileModule(fs.readFileSync(new URL(relative, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  new Function("exports", "require", output)(exports, name => {
    assert.ok(name in dependencies, `Unexpected dependency: ${name}`);
    return dependencies[name];
  });
  return exports;
}

const base = "../src/components/dashboard/";
const types = load(`${base}types.ts`);
const demo = load(`${base}demoData.ts`, { "./types": types });
const messages = load(`${base}messages.ts`);
const escaped = value => renderToStaticMarkup(React.createElement("span", null, value)).slice(6, -7);
assert.equal(demo.dashboardDemoEnabled, false, "ERP dashboard must use live APIs, not forced demo figures");

for (const lang of ["en", "ru", "uz"]) {
  for (const scenario of ["success", "unknown-currency", "loading", "error", "denied", "no-finance"]) {
    const keys = [];
    const fixture = {
      ...demo.demoOverview("2026-09-14", "2026-09-20", "ALL", "2026-09-20"),
      active_orders: 917, planned_quantity: 12345, late_orders: 0, orders: [],
    };
    const { default: Dashboard } = load(`${base}ManagementDashboard.tsx`, {
      react: React, "react/jsx-runtime": jsxRuntime,
      swr: { default: key => {
        keys.push(key);
        const overview = key?.startsWith("/api/dashboard/overview?");
        return {
          data: !key || ["loading", "error"].includes(scenario) ? undefined
            : overview ? fixture : scenario === "unknown-currency"
              ? { revenue_total: 987654, revenue_currency: null, payments_received: 123456, payments_currency: null }
              : { revenue_total: 987654, revenue_currency: "UZS", payments_received: 123456, payments_currency: "UZS" },
          error: key && scenario === "error" ? new Error("Network unavailable") : undefined,
          isLoading: Boolean(key) && scenario === "loading", isValidating: false, mutate() {},
        };
      } },
      "lucide-react": Object.fromEntries(["ArrowRight", "Download", "Plus", "RefreshCw", "Search"].map(key => [key, () => null])),
      "@/lib/api": { fetcher() { throw new Error("No network in render test"); } },
      "@/lib/auth": { useMe: () => ({ me: { id: 1 } }), can: (_me, ...permissions) => scenario !== "denied"
        && !(scenario === "no-finance" && permissions.includes("finance.view")) },
      "@/lib/i18n": { useT: () => ({ lang, t: key => key }) },
      "./messages": messages, "./types": types, "./demoData": demo,
      "./DashboardCharts": { DepartmentBars: () => null, OrderDonut: () => null },
      "./FactoryComparison": { default: () => null }, "./ActivityLineChart": { default: () => null },
    });
    const html = renderToStaticMarkup(React.createElement(Dashboard));
    assert.ok(!html.includes(demo.demoMessages[lang].note));
    assert.ok(!html.includes(demo.demoMessages[lang].generated));
    assert.ok(!html.includes(demo.demoFinance.revenue_total.toLocaleString()));
    if (scenario === "denied") {
      assert.deepEqual(keys, [null, null]);
    } else {
      assert.match(keys[0], /^\/api\/dashboard\/overview\?start=.*&end=.*&factory=ALL$/);
      assert.equal(keys[1], scenario === "no-finance" ? null : "/api/dashboard/finance");
      if (["success", "unknown-currency", "no-finance"].includes(scenario)) {
        assert.match(html, />917</);
        assert.ok(html.includes(messages.messages[lang].updated));
        assert.equal(html.includes("987654.00 UZS"), scenario === "success");
        assert.equal(html.includes("123456.00 UZS"), scenario === "success");
        if (scenario === "unknown-currency") {
          assert.equal(html.includes("987654.00"), false, "unknown or mixed currency totals must not display as bare money");
          assert.equal(html.includes("123456.00"), false, "unknown or mixed currency totals must not display as bare money");
        }
      } else if (scenario === "loading") {
        assert.ok(html.includes(escaped(messages.messages[lang].loading)));
      } else {
        assert.ok(html.includes('role="alert"'));
        assert.ok(html.includes(escaped(messages.messages[lang].error)));
      }
    }
  }
}
console.log("Management dashboard: live values, permissions, loading and failures pass in EN/RU/UZ; no demo fallback");
