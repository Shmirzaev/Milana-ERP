import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function load(path) {
  const exports = {};
  const compiled = ts.transpileModule(fs.readFileSync(path, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(compiled, { exports, module: { exports } });
  return exports;
}
const { changeAccess, accessText } = load("src/lib/userAccess.ts");
const access = load("src/lib/access.ts");
const { isSewingRole, factoryWorkspaceHome } = access;
let value = { MIL: { allow: ["finance.view"], deny: ["sales.orders"] } };
const original = JSON.stringify(value);
value = changeAccess(value, "ECO", "cutting.records", "allow");
assert.equal(JSON.stringify(value.MIL), JSON.stringify(JSON.parse(original).MIL));
value = changeAccess(value, "MIL", "sales.orders", "allow");
assert.equal(value.MIL.deny.includes("sales.orders"), false);
assert.equal(value.MIL.allow.includes("sales.orders"), true);
value = changeAccess(value, "MIL", "sales.orders", "deny");
assert.equal(value.MIL.allow.includes("sales.orders"), false);
value = changeAccess(value, "MIL", "sales.orders", "default");
assert.equal(value.MIL.deny.includes("sales.orders"), false);
assert.equal(value.ECO.allow[0], "cutting.records");
assert.equal(isSewingRole({ role: "Sewing", permissions: ["sewing.workspace"] }), true);
assert.equal(isSewingRole({ role: "Sewing", access_configured: true, permissions: ["finance.view"] }), false);
for (const language of ["en", "ru", "uz"]) {
  const text = accessText(language);
  assert.ok(text.title && text.allow && text.deny && text.inherit && text.scopeHelp);
  assert.equal(Object.keys(text.groups).length, 20);
}
console.log("User access: allow/deny/default, factory isolation, legacy and configured Sewing, and EN/RU/UZ labels passed.");

// Exercise the rendered checkbox controls with real policy updates and server previews.
const React = await import("react");
const source = ts.transpileModule(fs.readFileSync("src/components/UserAccessEditor.tsx", "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const runtime = await import("react/jsx-runtime");
// Run the real AuthGate with department-scoped sessions: root login, old
// bookmarked landings, intended destination, and unauthorized cross-factory URLs.
const gateSource = ts.transpileModule(fs.readFileSync("src/components/AuthGate.tsx", "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const packingPermissions = ["packaging.records", "packaging.packages", "traceability.view", "processes.view"];
for (const [factory, oldHome, packingHome] of [["BST", "/departments/BST", "/departments/BPK"], ["ECO", "/departments/ECT", "/departments/ECP"]]) {
  const me = { role: "Packaging", factory_code: factory, available_factories: [factory], permissions: packingPermissions };
  assert.equal(factoryWorkspaceHome(me), packingHome);
  assert.equal(factoryWorkspaceHome({ ...me, access_configured: true, permissions: ["packaging.packages"] }), packingHome);
  assert.equal(factoryWorkspaceHome({ ...me, permissions: [] }), oldHome);
  assert.equal(factoryWorkspaceHome({ ...me, permissions: ["*"] }), oldHome);
  assert.equal(factoryWorkspaceHome({ ...me, permissions: [...packingPermissions, "planning.production"] }), oldHome);
  for (const [pathname, redirect, denied] of [["/", packingHome, false], [oldHome, packingHome, false], [packingHome, null, false], ["/departments/PKG", null, true], [factory === "BST" ? "/departments/ECP" : "/departments/BPK", null, true]]) {
    const effects = [], redirects = [], gateExports = {};
    vm.runInNewContext(gateSource, {
      exports: gateExports, URLSearchParams,
      require: (name) => {
        if (name === "react/jsx-runtime") return runtime;
        if (name === "react") return { useEffect: (fn) => effects.push(fn), useState: (initial) => [initial, () => {}] };
        if (name === "next/navigation") return { usePathname: () => pathname, useRouter: () => ({ replace: (path) => redirects.push(path) }) };
        if (name === "@/lib/access") return access;
        if (name === "@/lib/auth") return { useMe: () => ({ me, loading: false, hasToken: true }), can: (user, ...perms) => user.permissions.some(p => p === "*" || perms.includes(p)) };
        if (name === "@/lib/api") return { api: { post: () => { throw new Error("Unexpected factory switch"); } } };
        if (name === "@/lib/i18n") return { useT: () => ({ t: (key) => key }) };
        if (name === "@/lib/priceCalculationRequests") return {};
        throw new Error(name);
      },
    });
    const rendered = gateExports.default({ children: "packaging workspace" });
    effects.forEach(fn => fn());
    assert.deepEqual(redirects, redirect ? [redirect] : [], `${factory} ${pathname}`);
    assert.equal(rendered?.props?.children === "auth.accessDenied", denied, `${factory} ${pathname}`);
    if (!redirect && !denied) assert.equal(rendered.props.children, "packaging workspace");
  }
}
assert.equal(factoryWorkspaceHome({ role: "Sewing", factory_code: "BST", permissions: ["sewing.workspace"] }), "/departments/BST");
assert.equal(factoryWorkspaceHome({ role: "Sewing", factory_code: "ECO", permissions: ["sewing.workspace"] }), "/departments/ECO");
assert.equal(factoryWorkspaceHome({ role: "Packaging", factory_code: "MIL", permissions: packingPermissions }), "/");
assert.match(fs.readFileSync("src/app/login/page.tsx", "utf8"), /window\.location\.href = "\/";/);
console.log("Packaging login and stale landing recovery passed; factory isolation and existing homes preserved.");
let selectedFactory = "MIL";
let effective = ["planning.view"];
let grantable = true;
let previewLoading = false;
let actor = { permissions: ["admin.super"], factory_code: "MIL" };
const componentExports = {};
vm.runInNewContext(source, { exports: componentExports, require: (name) => {
  if (name === "react/jsx-runtime") return runtime;
  if (name === "react") return { ...React, useId: () => "editor", useEffect: () => {}, useState: (initial) => [initial === "MIL" ? selectedFactory : initial, () => {}] };
  if (name === "swr") return { default: (key) => typeof key === "string"
    ? { data: [{ key: "planning.view", group: "Planning", label: { en: "Planning dashboard" }, grantable }, { key: "admin.super", group: "Administration", label: { en: "Super Admin" }, grantable: true }] }
    : { data: Object.fromEntries(["MIL", "BST", "ECO"].map(f => [f, { effective, available: true }])), isLoading: previewLoading } };
  if (name === "@/lib/api") return {};
  if (name === "@/lib/i18n") return { useT: () => ({ lang: "en" }) };
  if (name === "@/lib/auth") return { useMe: () => ({ me: actor }) };
  if (name === "@/lib/userAccess") return { changeAccess, accessText };
  throw new Error(name);
}});
let policy = null;
function controls() {
  const result = [];
  function walk(node) {
    if (Array.isArray(node)) return node.forEach(walk);
    if (!node?.props) return;
    if (node.type === "input" && node.props.type === "checkbox") result.push(node.props);
    walk(node.props.children);
  }
  walk(componentExports.default({ subject: { name: "Preview", email: "preview@example.com", factory_code: "MIL", role_id: 1, department_id: null }, value: policy, onChange: next => { policy = next; }, onReady: () => {} }));
  return result;
}
assert.equal(controls()[0].checked, true, "inherited access is checked");
controls()[0].onChange({ target: { checked: false } });
assert.equal(policy.MIL.deny[0], "planning.view", "unticking explicitly denies inherited access");
effective = [];
assert.equal(controls()[0].checked, false);
controls()[0].onChange({ target: { checked: true } });
assert.equal(policy.MIL.allow[0], "planning.view");
assert.equal(policy.MIL.deny.length, 0);
grantable = false;
assert.equal(controls()[0].disabled, true, "cannot grant a permission outside actor scope");
effective = ["planning.view"];
assert.equal(controls()[0].disabled, false, "existing access can still be revoked");
previewLoading = true;
assert.equal(controls()[0].disabled, true, "wait for authoritative access before another toggle");
previewLoading = false;
selectedFactory = "ECO";
assert.equal(controls()[1].disabled, true, "Super Admin tier is primary-factory only");
controls()[0].onChange({ target: { checked: false } });
assert.equal(policy.MIL.allow[0], "planning.view", "other factory policy remains intact");
assert.equal(policy.ECO.deny[0], "planning.view");
actor = { permissions: ["admin.users"], factory_code: "MIL" };
assert.equal(controls()[0].disabled, true, "ordinary admin cannot edit another factory");
console.log("Compact checkboxes: inherited revocation, grants, factory isolation, privilege guards and loading state passed.");
