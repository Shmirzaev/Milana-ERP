import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const access = fs.readFileSync("src/lib/access.ts", "utf8");
const gate = fs.readFileSync("src/components/AuthGate.tsx", "utf8");
const sidebar = fs.readFileSync("src/components/Sidebar.tsx", "utf8");
const flowsPage = fs.readFileSync("src/app/(app)/sewing/flows/page.tsx", "utf8");
const bundleScan = fs.readFileSync("src/components/BundleScanPanel.tsx", "utf8");

const compiledAccess = ts.transpileModule(access, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const accessExports = {};
vm.runInNewContext(compiledAccess, { exports: accessExports, module: { exports: accessExports } });

const { isSewingWorkspacePath, sewingWorkspaceHome } = accessExports;
const expectedHomes = [
  [{ factory_code: "MIL" }, "/sewing/flows"],
  [{ factory_code: "BST" }, "/departments/BST"],
  [{ factory_code: "ECO" }, "/departments/ECO"],
];
for (const [me, expected] of expectedHomes) {
  const actual = sewingWorkspaceHome(me);
  if (actual !== expected) {
    throw new Error(`Wrong Sewing home for ${me.factory_code}: ${actual} (expected ${expected})`);
  }
}

for (const route of ["/departments/SEW", "/departments/MIL", "/departments/BST", "/departments/ECO"]) {
  if (!isSewingWorkspacePath(route)) {
    throw new Error(`Sewing department route is denied by the workspace guard: ${route}`);
  }
}
if (isSewingWorkspacePath("/departments/ECT")) {
  throw new Error("The Sewing workspace guard must not admit Eco Cotton Cutting.");
}

const requiredWorkspaceRoutes = [
  '"/departments/SEW"',
  '"/departments/MIL"',
  '"/departments/BST"',
  '"/departments/ECO"',
];
for (const route of requiredWorkspaceRoutes) {
  if (!access.includes(route)) {
    throw new Error(`Sewing workspace route is missing: ${route}`);
  }
}

const requiredAccessFragments = [
  "export function sewingWorkspaceHome",
  'me?.factory_code === "BST"',
  'return "/departments/BST"',
  'me?.factory_code === "ECO"',
  'return "/departments/ECO"',
  "return SEWING_WORKSPACE_HOME",
];
for (const fragment of requiredAccessFragments) {
  if (!access.includes(fragment)) {
    throw new Error(`Factory-aware Sewing home contract is missing: ${fragment}`);
  }
}

const requiredGateFragments = [
  "const restrictedSewingHome = sewingWorkspaceHome(me)",
  "? restrictedSewingHome",
  "router.replace(restrictedSewingHome)",
  'searchParams.get("factory") || me?.factory_code || "MIL"',
  '{ prefix: "/sewing/flows", perms: ["sewing.workspace", "sewing.flows"] }',
];
for (const fragment of requiredGateFragments) {
  if (!gate.includes(fragment)) {
    throw new Error(`Sewing login redirect contract is missing: ${fragment}`);
  }
}

if (!sidebar.includes("isSewingWorkspaceNavItem(i.href)")) {
  throw new Error("Sewing-role navigation must remain restricted to factory-safe workspace routes.");
}
for (const factory of ["MIL", "BST", "ECO"]) {
  const flowItem = `{ href: "/sewing/flows?factory=${factory}", labelKey: "nav.sewingFlows", perms: ["sewing.workspace", "sewing.flows"]`;
  if (!sidebar.includes(flowItem)) {
    throw new Error(`Sewing Flows navigation must accept the narrow sewing.flows permission for ${factory}.`);
  }
}
for (const factory of ["MIL", "BST", "ECO"]) {
  const dailyItem = `{ href: "/sewing/daily-report?factory=${factory}", labelKey: "nav.sewingDailyReport", perms: ["sewing.workspace", "sewing.daily_reports.view"]`;
  if (!sidebar.includes(dailyItem)) {
    throw new Error(`Daily Sewing Report permissions changed unexpectedly for ${factory}.`);
  }
}
if (!sidebar.includes('searchParams.get("factory") || me?.factory_code || "MIL"')) {
  throw new Error("Sewing navigation must highlight the signed-in factory when the URL omits a factory query.");
}
if (!flowsPage.includes('searchParams.get("factory") || me?.factory_code || "MIL"')) {
  throw new Error("Sewing Flows must inherit the signed-in factory when an old/direct URL omits the query.");
}
if (!bundleScan.includes('searchParams.get("factory") || me?.factory_code || "MIL"')) {
  throw new Error("Sewing bundle scanning must inherit the signed-in factory when the URL omits the query.");
}

// Execute the scanner's actual action selection for every factory pairing.
const actionStart = bundleScan.indexOf("  const nextDept =");
const actionEnd = bundleScan.indexOf("\n  return (", actionStart);
if (actionStart < 0 || actionEnd < 0) throw new Error("Scanner action selection was not found.");
const actionCode = ts.transpileModule(
  `${bundleScan.slice(actionStart, actionEnd)}\nglobalThis.actions = availableActions;`,
  { compilerOptions: { target: ts.ScriptTarget.ES2020 } },
).outputText;
for (const sessionFactory of ["MIL", "BST", "ECO"]) {
  for (const bundleFactory of ["MIL", "BST", "ECO"]) {
    for (const status of ["created", "sent_to_sewing", "received_sewing"]) {
      for (const permitted of [true, false]) {
        const context = {
          me: { factory_code: sessionFactory },
          bundle: { status, sewing_factory_code: bundleFactory, next_department_id: 1 },
          // Even a URL claiming the bundle's factory must not change session access.
          factoryCode: bundleFactory,
          departmentById: new Map([[1, { code: bundleFactory }]]),
          SEWING_DEPARTMENT_CODES: new Set(["SEW", "MIL", "BST", "ECO"]),
          canSewingScan: permitted, canCuttingScan: false, canPrintingScan: false,
          includeSewing: true, includeCutting: false, includePrinting: false,
          scope: "sewing", isLookingUp: false, sewingBatch: null, messageTone: "info", msg: "",
          factoryLabel: (value) => value, t: (key) => key,
        };
        vm.runInNewContext(actionCode, context);
        const shown = context.actions.some((action) => action.key === "receive-sewing");
        const expected = permitted && sessionFactory === bundleFactory && status !== "received_sewing";
        if (shown !== expected) {
          throw new Error(`Incorrect receive action: ${sessionFactory}/${bundleFactory}/${status}/${permitted}`);
        }
      }
    }
  }
}

console.log("Factory-aware Sewing workspace access contract passed (54 scanner action cases).");
