import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const runtime = fs.readFileSync("src/lib/i18n.tsx", "utf8");
const keys = [
  "cutting.not_started", "cutting.partial", "cutting.completed", "modelNumber",
  "searchModelNumber", "variantNumber", "selectVariant", "noApprovedVariants", "modelLoadFailed", "variantApprovalRequired",
];
for (const lang of ["en", "ru", "uz"]) {
  const path = `src/lib/i18n/locales/${lang}-supplemental.ts`;
  assert(runtime.includes(`./i18n/locales/${lang}-supplemental`), `${lang} must be loaded by the runtime`);
  const source = fs.readFileSync(path, "utf8");
  const exports = {};
  vm.runInNewContext(ts.transpile(source, { module: ts.ModuleKind.CommonJS }), { exports });
  for (const suffix of keys) {
    const key = `page.planning.${suffix}`;
    assert.equal(typeof exports.default[key], "string", `${lang}: missing runtime translation ${key}`);
    assert(exports.default[key].trim() && exports.default[key] !== key);
  }
}
console.log("Branded order dialog runtime translations passed.");

// Render the actual components with deterministic hook data. Mixed approval
// states must remain visible, while neither mouse nor Enter can choose a draft.
const jsx = (type, props) => ({ type, props });
const variants = [
  { id: 8048, variant_no: "V-6120", status: "draft" },
  { id: 8049, variant_no: "V-6121", status: "approved" },
  { id: 8051, variant_no: "V-6123", status: "approved" },
];
const group = { id: 8047, group_key: "pj1236", group_model_no: "PJ1236", variants };
const hooks = {
  useEffect() {}, useMemo: (fn) => fn(), useCallback: (fn) => fn,
  useState: (value) => [value, () => {}], useRef: () => ({ current: null }), useId: () => "test",
};
function component(path, dependencies) {
  const exports = {};
  vm.runInNewContext(ts.transpile(fs.readFileSync(path, "utf8"), {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  }), { exports, require: (name) => dependencies[name] || {}, document: {}, window: {}, URLSearchParams });
  return exports.default;
}
function descendants(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(descendants);
  return [node, ...descendants(node.props?.children)];
}
const dependencies = {
  react: hooks, "react/jsx-runtime": { jsx, jsxs: jsx },
  "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
  "@/lib/modelCode": { modelCodeParts: () => ({ modelNo: "PJ1236" }), normalizeModelSearch: (value) => value.toLowerCase() },
  "@/lib/modelImages": { storageThumbnailUrl: () => "" },
  swr: { default: (key) => ({ data: key.includes("variant-groups") ? { rows: [group] } : {} }) },
  "swr/infinite": { default: () => ({ data: [{ rows: [group] }], size: 1 }) },
  "@/components/SearchableSelect": { default: "Select" },
};
const BrandedSelect = component("src/components/BrandedModelVariantSelect.tsx", dependencies);
const tree = BrandedSelect({ value: 8049, onChange() {} });
const variantSelect = descendants(tree).find((node) => node.props?.inputId === "branded-variant-number");
assert.deepEqual(Array.from(variantSelect.props.options, (option) => option.value), [8048, 8049, 8051]);
assert.equal(variantSelect.props.options[0].disabled, true);
assert.equal(variantSelect.props.options[0].metaText, "page.planning.variantApprovalRequired");
assert.equal(variantSelect.props.options[1].disabled, false);
assert.equal(variantSelect.props.value, 8049);

let calls = 0;
const SearchableSelect = component("src/components/SearchableSelect.tsx", {
  ...dependencies,
  react: { ...hooks, useState: (value) => [value === false ? true : value === null ? {} : value, () => {}] },
  "react-dom": { createPortal: (node) => node },
});
const options = [{ value: 1, label: "Draft", disabled: true }, { value: 2, label: "Approved" }];
const selectTree = SearchableSelect({ value: null, options, onChange: () => { calls += 1; }, placeholder: "Variant", noResultsText: "Empty" });
const nodes = descendants(selectTree);
const rows = nodes.filter((node) => node.props?.role === "option");
assert.equal(rows[0].props.disabled, true);
assert.equal(rows[0].props["aria-disabled"], true);
rows[0].props.onClick();
nodes.find((node) => node.props?.role === "combobox").props.onKeyDown({ key: "Enter", preventDefault() {} });
assert.equal(calls, 0, "Disabled variants cannot be selected by click or Enter");
rows[1].props.onClick();
assert.equal(calls, 1, "Approved variants remain selectable");
console.log("Mixed-status branded variants and disabled selection passed.");

// The single family action follows the approval permission in both catalogs.
let pagePath = "/models";
let permissions = [];
let familyStatus = "draft";
const ModelsPage = component("src/app/(app)/models/page.tsx", {
  ...dependencies,
  "next/navigation": { useRouter: () => ({}), usePathname: () => pagePath, useSearchParams: () => new URLSearchParams() },
  "@/components/DialogProvider": { useDialogs: () => ({ notify() {} }) },
  "@/lib/modelComposition": { formatModelComposition: () => "" },
  "@/lib/auth": { useMe: () => ({ me: { permissions } }), can: (me, ...wanted) => me.permissions.includes("*") || wanted.some((permission) => me.permissions.includes(permission)) },
  swr: { default: () => ({ data: { rows: [{ id: 1, code: "MODEL1", name: "Model", status: familyStatus }] } }) },
});
for (const [path, allowed] of [["/models", "modeling.approve"], ["/usluga/models", "usluga.manage"]]) {
  pagePath = path;
  for (const [grants, status, expected] of [[[], "draft", 0], [["modeling.models"], "draft", 0], [[allowed], "draft", 1], [[allowed], "approved", 0], [["*"], "draft", 1]]) {
    permissions = grants;
    familyStatus = status;
    const buttons = descendants(ModelsPage()).filter((node) => node.type === "button" && node.props?.children === "btn.approve");
    assert.equal(buttons.length, expected, `${path}: ${grants} / ${status}`);
  }
}
console.log("Model-family approval visibility and permissions passed.");
