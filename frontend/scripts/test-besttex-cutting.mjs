// Actual component/route consumers: backend scope is covered by API regressions.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import * as runtime from "react/jsx-runtime";
import { renderToStaticMarkup } from "react-dom/server";
import * as icons from "lucide-react";

let me, effects, redirects, requests, opened;
const path = "/besttex/cutting-orders";
const can = (user, ...perms) => Boolean(user?.permissions.some(p => p === "*" || perms.includes(p)));
const t = (key, values = {}) => key + Object.values(values).join(" ");
const cache = new Map();
function load(file) {
  if (cache.has(file)) return cache.get(file);
  const exports = {};
  const compiled = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(compiled, {
    exports, module: { exports }, URLSearchParams, console,
    require: (name) => {
      if (name === "react/jsx-runtime") return runtime;
      if (name === "react") return {
        useState: initial => [initial, () => {}], useEffect: fn => effects.push(fn), useMemo: fn => fn(),
      };
      if (name === "next/navigation") return {
        usePathname: () => path, useSearchParams: () => new URLSearchParams(),
        useRouter: () => ({ replace: value => redirects.push(value) }),
      };
      if (name === "next/link") return { default: props => runtime.jsx("a", props) };
      if (name === "lucide-react") return icons;
      if (name === "@/lib/auth") return { can, useMe: () => ({ me, loading: false, hasToken: true }) };
      if (name === "@/lib/i18n") return { useT: () => ({ lang: "en", t }) };
      if (name === "@/lib/api") return { fetcher: () => {}, api: { openLabel: async url => opened.push(url) } };
      if (name === "@/lib/priceCalculationRequests") return { isAbbosbekPricingUser: () => false, isAccessoryPricingUser: () => false };
      if (name === "@/components/BrandLogo") return { default: () => null };
      if (name === "@/components/ImageThumbnail") return { default: ({ imageUrl, label }) => runtime.jsx("img", { src: imageUrl || undefined, alt: label }) };
      if (name === "@/components/sewing/BandWorkspace") return { default: () => null };
      if (name === "swr") return { default: key => { requests.push(key); return { data: key ? { items: rows, total: 2, page_size: 30 } : undefined }; }, SWRConfig: "div" };
      if (name.startsWith("@/")) {
        const base = "src/" + name.slice(2);
        return load(base + (fs.existsSync(base + ".tsx") ? ".tsx" : ".ts"));
      }
      throw new Error("Unexpected dependency: " + name);
    },
  });
  cache.set(file, exports);
  return exports;
}
function reset(factory, permissions, role = "Reader") {
  me = { id: 7, role, factory_code: factory, available_factories: [factory], permissions };
  effects = []; redirects = []; requests = []; opened = [];
}
const { default: AuthGate } = load("src/components/AuthGate.tsx");
const { default: Sidebar } = load("src/components/Sidebar.tsx");
const { default: Page } = load("src/app/(app)/besttex/cutting-orders/page.tsx");
const { default: List } = load("src/components/BesttexCutOrderList.tsx");
const rows = [1, 2].map(id => ({
  cutting_record_id: id, cutting_batch_no: `CUT-${id}`, production_no: `PO-${id}`, order_no: `SO-${id}`,
  batch_no: null, model_code: "PIC100-123", model_name: "Garment", planning_order_id: 55,
  planning_order_no: "BSO-TEST", planning_order_name: "Besttex customer", model_no: "PIC100", variant_no: "123",
  model_image_url: `/garment-${id}.jpg`, variant_image_url: `/fabric-123-${id}.jpg`, size_summary: "46–50 (3)",
  material_label: "MAT-COTTON", deadline: "2026-11-01T00:00:00Z", cut_pieces: 6, passed_pieces: 5,
  created_at: "2026-10-26T00:00:00Z",
}));
for (const [factory, permissions, allowed, role] of [
  ["BST", ["besttex.cutting_sheets"], true, "Reader"],
  ["BST", ["besttex.cutting_sheets", "sewing.workspace"], true, "Sewing"],
  ["BST", [], false, "Reader"],
  ["MIL", ["besttex.cutting_sheets"], false, "Reader"],
  ["ECO", ["besttex.cutting_sheets"], false, "Reader"],
  ["MIL", ["*"], true, "Admin"],
]) {
  reset(factory, permissions, role);
  const gate = AuthGate({ children: "cutting workspace" });
  effects.forEach(fn => fn());
  assert.deepEqual(redirects, [], `${factory}/${role} must not unexpectedly redirect`);
  assert.equal(gate.props.children, allowed ? "cutting workspace" : "auth.accessDenied");
  const nav = renderToStaticMarkup(Sidebar());
  assert.equal(nav.includes('href="/besttex/cutting-orders"'), allowed, `${factory}/${role} navigation scope`);
  const page = Page();
  assert.equal(requests.at(-1), allowed ? "/api/besttex/cutting-orders?page=1&q=" : null);
  if (!allowed) assert.equal(page.props.children, "auth.accessDenied");
}
reset("BST", ["besttex.cutting_sheets"]);
const markup = renderToStaticMarkup(runtime.jsx(List, { rows, total: 2, lang: "en", t, printing: null, onPrint: () => {} }));
assert.equal((markup.match(/BSO-TEST/g) || []).length, 1, "same planning order forms one group");
assert.match(markup, /Besttex customer/);
assert.match(markup, /garment-1\.jpg/);
assert.match(markup, /fabric-123-2\.jpg/);
assert.match(markup, /46–50 \(3\)/);
assert.match(markup, /MAT-COTTON/);
assert.doesNotMatch(markup, /Delete|Complete cutting|Save/);
const printing = renderToStaticMarkup(runtime.jsx(List, { rows, total: 2, lang: "en", t, printing: 1, onPrint: () => {} }));
assert.equal((printing.match(/disabled=""/g) || []).length, 2, "one active print disables all duplicate requests");
function findList(node) {
  if (!node || typeof node !== "object") return undefined;
  if (node.type === List) return node;
  const children = node.props?.children;
  for (const child of (Array.isArray(children) ? children : [children])) {
    const found = findList(child); if (found) return found;
  }
}
await findList(Page()).props.onPrint(2);
assert.deepEqual(opened, ["/api/besttex/cutting-orders/2/sheet"]);
console.log("Besttex: real AuthGate, Sidebar, page query/print and grouped-photo components passed six access contexts.");
