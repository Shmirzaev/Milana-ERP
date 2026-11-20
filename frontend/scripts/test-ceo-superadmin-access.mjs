// Exercise the real gate, menu, shell, report entry, and shared access predicates.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import * as runtime from "react/jsx-runtime";
import * as icons from "lucide-react";
import { renderToStaticMarkup } from "react-dom/server";

const compile = source => ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const authTree = ts.createSourceFile("auth.ts", fs.readFileSync("src/lib/auth.ts", "utf8"), ts.ScriptTarget.Latest, true);
const names = new Set(["isCeo", "can", "canViewCeoDashboard"]);
const helpers = authTree.statements.filter(node => ts.isFunctionDeclaration(node) && names.has(node.name?.text));
assert.equal(helpers.length, names.size);
const predicates = {};
vm.runInNewContext(compile(helpers.map(node => node.getText(authTree)).join("\n")), { exports: predicates });

let me, pathname = "/ceo-dashboard", effects = [], redirects = [];
const cache = new Map();
function load(file) {
  if (cache.has(file)) return cache.get(file);
  const exports = {};
  vm.runInNewContext(compile(fs.readFileSync(file, "utf8")), {
    exports, module: { exports }, URLSearchParams, console,
    require: name => {
      if (name === "react/jsx-runtime") return runtime;
      if (name === "react") return {
        useState: initial => [typeof initial === "function" ? initial() : initial, () => {}],
        useEffect: effect => effects.push(effect), useLayoutEffect: effect => effects.push(effect),
        useMemo: fn => fn(), useRef: initial => ({ current: initial }),
      };
      if (name === "next/navigation") return {
        usePathname: () => pathname, useSearchParams: () => new URLSearchParams(),
        useRouter: () => ({ replace: value => redirects.push(value) }),
      };
      if (name === "next/link") return { default: props => runtime.jsx("a", props) };
      if (name === "lucide-react") return icons;
      if (name === "@/lib/auth") return {
        ...predicates, CEO_DASHBOARD_PATH: "/ceo-dashboard",
        useMe: () => ({ me, loading: false, hasToken: true, refresh: async () => {} }), logout: () => {},
      };
      if (name === "@/lib/i18n") return { useT: () => ({ lang: "en", t: key => key }) };
      if (name === "@/lib/api") return { api: { post: () => { throw Error("Unexpected write"); } } };
      if (name === "@/lib/priceCalculationRequests") return { isAbbosbekPricingUser: () => false, isAccessoryPricingUser: () => false };
      if (["@/components/BrandLogo", "@/components/LangSwitcher", "@/components/sewing/BandWorkspace"].includes(name)) return { default: () => null };
      if (name === "swr") return { SWRConfig: "div" };
      if (file.endsWith("CeoDashboard.tsx") && (name.startsWith("./") || name === "@/lib/errorMessages")) return {};
      if (name.startsWith("@/")) {
        const base = "src/" + name.slice(2);
        return load(base + (fs.existsSync(base + ".tsx") ? ".tsx" : ".ts"));
      }
      throw Error("Unexpected dependency " + name);
    },
  });
  cache.set(file, exports);
  return exports;
}
const Gate = load("src/components/AuthGate.tsx").default;
const Sidebar = load("src/components/Sidebar.tsx").default;
const Shell = load("src/components/CeoShell.tsx").default;
const Report = load("src/components/ceo-dashboard/CeoDashboard.tsx").default;
for (const factory of ["MIL", "BST", "ECO"]) {
  for (const [role, permissions, capability, allowed] of [
    ["Super Admin", ["*", "admin.super"], true, true],
    ["Custom role", ["admin.super"], true, true],
    ["Super Admin", ["admin.super"], false, false], // Server revocation wins.
    ["Admin", ["*"], false, false],
    ["Management", ["management.view"], false, false],
    ["Super Admin", ["*"], undefined, false], // No client role-name escalation.
    ["CEO", [], true, true],
  ]) {
    me = { id: 17, role, permissions, factory_code: factory, available_factories: [factory], can_view_ceo_dashboard: capability };
    pathname = "/ceo-dashboard"; effects = []; redirects = [];
    assert.equal(predicates.canViewCeoDashboard(me), allowed, role);
    assert.equal(renderToStaticMarkup(Gate({ children: "report-body" })).includes("report-body"), allowed, role);
    assert.equal(Report() !== null, allowed, role);
    const shell = renderToStaticMarkup(Shell({ children: "report-body" }));
    assert.equal(shell.includes("nav.backToErp"), allowed && role !== "CEO", role);
    if (role !== "CEO") {
      const menu = renderToStaticMarkup(Sidebar());
      assert.equal(menu.includes('href="/ceo-dashboard"'), allowed, factory + "/" + role);
      if (factory !== "MIL") assert.equal(menu.includes('href="/processes"'), false);
    }
    if (role === "Super Admin" && capability) {
      pathname = "/"; redirects = []; effects = [];
      Gate({ children: "operations" }); effects.forEach(fn => fn());
      assert.equal(redirects.includes("/ceo-dashboard"), false);
      assert.equal(predicates.can(me, "sales.orders"), true);
    }
  }
}
assert.equal(predicates.canViewCeoDashboard(undefined), false);
assert.equal(predicates.can({ role: "CEO", permissions: ["*"] }, "sales.orders"), false);
console.log("CEO access: actual components pass 21 role/factory contexts; operational access and CEO restrictions retained.");
