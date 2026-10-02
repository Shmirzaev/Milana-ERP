import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function load(path) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, { exports });
  return exports;
}
const access = load("src/lib/access.ts");
const storage = load("src/lib/payrollScanStorage.ts");
const values = new Map();
const store = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
const milKey = storage.payrollScanStorageKey("MIL");
const ecoKey = storage.payrollScanStorageKey("ECO");
assert.notEqual(milKey, ecoKey);
assert.equal(milKey, storage.PAYROLL_SCAN_STORAGE_KEY);
const bstKey = storage.payrollScanStorageKey("BST");
assert.notEqual(bstKey, milKey);
assert.notEqual(bstKey, ecoKey);
store.setItem(bstKey, JSON.stringify([{ scanUid: "shared-label" }, { scanUid: "bst-keep" }]));
store.setItem(milKey, JSON.stringify([{ scanUid: "shared-label" }]));
store.setItem(ecoKey, JSON.stringify([{ scanUid: "shared-label" }, { scanUid: "eco-keep" }]));
assert.equal(storage.removePayrollScanHistoryForLabel("shared-label", store, "ECO"), 1);
assert.equal(JSON.parse(store.getItem(milKey)).length, 1);
assert.equal(JSON.parse(store.getItem(ecoKey))[0].scanUid, "eco-keep");
assert.equal(JSON.parse(store.getItem(bstKey)).length, 2);
assert.equal(storage.removePayrollScanHistoryForLabel("shared-label", store, "BST"), 1);
assert.equal(JSON.parse(store.getItem(bstKey))[0].scanUid, "bst-keep");
assert.equal(JSON.parse(store.getItem(milKey)).length, 1);
assert.equal(storage.removePayrollScanHistoryForLabel("eco-keep", store, "MIL"), 0);
assert.equal(access.factoryWorkspaceHome({ factory_code: "ECO", permissions: ["payroll.view"] }), "/payroll");
assert.equal(access.factoryWorkspaceHome({ factory_code: "ECO", permissions: ["payroll.scan"] }), "/payroll/scan");
assert.equal(access.factoryWorkspaceHome({ factory_code: "MIL", permissions: ["payroll.view"] }), "/");
assert.equal(access.factoryWorkspaceHome({ factory_code: "BST", permissions: ["payroll.view"] }), "/payroll");

// Evaluate the actual sidebar's section and item filtering for each session.
const source = fs.readFileSync("src/components/Sidebar.tsx", "utf8");
const ast = ts.createSourceFile("sidebar.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const sectionDecl = ast.statements.find(node => ts.isVariableStatement(node) && node.declarationList.declarations.some(d => d.name.getText(ast) === "SECTIONS"));
const sidebar = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === "Sidebar");
const visibleDecl = sidebar.body.statements.find(node => ts.isVariableStatement(node) && node.declarationList.declarations.some(d => d.name.getText(ast) === "visibleSections"));
const program = ts.transpileModule(`${sectionDecl.getText(ast)}\n${visibleDecl.getText(ast)}\nJSON.stringify(visibleSections);`, {
  compilerOptions: { target: ts.ScriptTarget.ES2020 },
}).outputText;
const icons = Object.fromEntries([...source.matchAll(/icon: (\w+)/g)].map(m => [m[1], () => null]));
const expected = ["/payroll", "/payroll/reports/sewing-production", "/payroll/reports/order-qr-status", "/process-qr", "/payroll/scan", "/payroll/qr-control"];
function links(factory, permissions) {
  const me = { factory_code: factory, permissions };
  const sections = JSON.parse(vm.runInNewContext(program, {
    ...icons, me, useMemo: fn => fn(), ...access, isSuperAdmin: () => false,
    isAbbosbekPricingUser: () => false, isAccessoryPricingUser: () => false,
    can: (user, ...perms) => user.permissions.includes("*") || perms.some(p => user.permissions.includes(p)),
  }));
  return sections.find(s => s.titleKey === "section.payroll")?.items.map(i => i.href) ?? [];
}
assert.deepEqual(links("ECO", ["*"]), expected);
assert.deepEqual(links("MIL", ["*"]), expected);
assert.deepEqual(links("BST", ["*"]), expected);
assert.deepEqual(links("BST", ["sewing.records"]), []);
assert.deepEqual(links("BST", ["payroll.scan"]), ["/process-qr", "/payroll/scan"]);
assert.equal(access.factoryWorkspaceHome({ factory_code: "BST", permissions: ["payroll.scan"] }), "/payroll/scan");
assert.deepEqual(links("ECO", ["cutting.records"]), []);
assert.deepEqual(links("ECO", ["payroll.scan"]), ["/process-qr", "/payroll/scan"]);

const runtime = await import("react/jsx-runtime");
const gateCode = ts.transpileModule(fs.readFileSync("src/components/AuthGate.tsx", "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
for (const factory of ["ECO", "MIL", "BST"]) {
  for (const pathname of expected) {
    const exports = {};
    const me = { id: 1, factory_code: factory, available_factories: [factory], permissions: ["*"] };
    vm.runInNewContext(gateCode, { exports, URLSearchParams, require: name => {
      if (name === "react/jsx-runtime") return runtime;
      if (name === "react") return { useEffect: () => {}, useState: initial => [initial, () => {}] };
      if (name === "swr") return { SWRConfig: "SWRConfig" };
      if (name === "next/navigation") return { usePathname: () => pathname, useSearchParams: () => new URLSearchParams(), useRouter: () => ({ replace() {} }) };
      if (name === "@/lib/access") return access;
      if (name === "@/lib/auth") return { useMe: () => ({ me, hasToken: true }), can: () => true };
      if (name === "@/lib/api" || name === "@/lib/priceCalculationRequests") return {};
      if (name === "@/lib/i18n") return { useT: () => ({ t: x => x }) };
      throw Error(name);
    } });
    const rendered = exports.default({ children: "payroll" });
    assert.equal(rendered.type === "SWRConfig", factory !== "MIL");
    if (factory !== "MIL") {
      assert.equal(rendered.key, `${factory}:1`);
      const first = rendered.props.value.provider(), second = rendered.props.value.provider();
      first.set("/api/payroll/records", [{ factory_code: "MIL" }]);
      assert.equal(second.size, 0, "Each factory session starts with its own response cache");
    }
  }
}

const processSource = fs.readFileSync("src/app/(app)/process-qr/page.tsx", "utf8");
const processAst = ts.createSourceFile("process.tsx", processSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const processPage = processAst.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === "ProcessQrPage");
const names = ["processUrl", "manualModelApiBase", "manualModelsUrl", "modelApiBase"];
const declarations = processPage.body.statements.filter(node => ts.isVariableStatement(node)
  && node.declarationList.declarations.some(d => names.includes(d.name.getText(processAst))));
const queryProgram = ts.transpileModule(declarations.map(n => n.getText(processAst)).join("\n") + "\nJSON.stringify({processUrl, manualModelsUrl, modelApiBase});", {
  compilerOptions: { target: ts.ScriptTarget.ES2020 },
}).outputText;
for (const factory of ["ECO", "MIL", "BST"]) {
  for (const sourceMode of ["erp", "manual"]) {
    for (const source_type of ["standard", "usluga"]) {
      const result = JSON.parse(vm.runInNewContext(queryProgram, {
        me: { factory_code: factory }, processSearch: "", manualModelSearch: "model", sourceMode,
        selectedTrackedProcess: { source_type },
      }));
      assert.equal(result.processUrl.includes("&factory=ECO"), factory === "ECO");
      const ecoCatalog = factory === "ECO" && (sourceMode === "manual" || source_type === "usluga");
      assert.equal(result.modelApiBase, ecoCatalog ? "/api/usluga" : "/api");
      if (sourceMode === "manual") assert.equal(result.manualModelsUrl.startsWith("/api/usluga/"), factory === "ECO");
    }
  }
}
console.log("Eco/Besttex payroll: six routes, permission filtering, factory landing, and isolated scan/return history passed.");
