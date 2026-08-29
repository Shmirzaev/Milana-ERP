import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const helperSource = fs.readFileSync("src/lib/sewingDailyReportSections.ts", "utf8");
const pageSource = fs.readFileSync("src/app/(app)/sewing/daily-report/page.tsx", "utf8");
const sidebarSource = fs.readFileSync("src/components/Sidebar.tsx", "utf8");

const compiledHelper = ts.transpileModule(helperSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const helperExports = {};
vm.runInNewContext(compiledHelper, { exports: helperExports, module: { exports: helperExports } });

const { supportsDynamicSewingReportSections } = helperExports;
for (const lineCode of ["BST-BAND-01", "BST-BAND-08", "BST-BAND-16", "CUSTOM-BST-LINE"]) {
  if (!supportsDynamicSewingReportSections("BST", lineCode)) {
    throw new Error(`Besttex line must support report sections: ${lineCode}`);
  }
}
for (const lineCode of ["ECO-BAND-01", "ECO-BAND-10", "ECO-BAND-20", "CUSTOM-ECO-LINE"]) {
  if (!supportsDynamicSewingReportSections("ECO", lineCode)) {
    throw new Error(`Eco Cotton line must support report sections: ${lineCode}`);
  }
}
for (const lineCode of ["SEW-01", "SEW-06", "SEW-07", "SEW-09", "SEW-10", "SEW-12", "SEW-13"]) {
  if (!supportsDynamicSewingReportSections("MIL", lineCode)) {
    throw new Error(`Existing Milana sectioned line lost support: ${lineCode}`);
  }
}
if (supportsDynamicSewingReportSections("MIL", "SEW-02")) {
  throw new Error("Ordinary Milana lines must retain their existing single-entry form.");
}

const requiredPageFragments = [
  "supportsDynamicSewingReportSections(selectedFlow.factory_code, selectedFlow.code)",
  't("page.sewingDailyReport.addSection")',
  't("page.sewingDailyReport.twoPartGarment")',
  't("page.sewingDailyReport.topQty")',
  't("page.sewingDailyReport.bottomQty")',
  "sectionEntries.length < MAX_SECTION_COUNT",
];
for (const fragment of requiredPageFragments) {
  if (!pageSource.includes(fragment)) {
    throw new Error(`Eco daily-report UI contract is missing: ${fragment}`);
  }
}
if (!sidebarSource.includes('/sewing/daily-report?factory=ECO')) {
  throw new Error("Eco Cotton Daily Sewing Report is missing from the sidebar.");
}

console.log("Factory daily sewing sections contract passed.");
