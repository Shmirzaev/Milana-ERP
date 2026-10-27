import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = fs.readFileSync(path.join(root, "src/app/(app)/payroll/scan/page.tsx"), "utf8");

const required = [
  ["immediate save after scan", "await saveRecordsToPayroll([nextRecord], true);"],
  ["numeric work scan resolves and saves in one request", "/api/payroll/scan/numeric-work"],
  ["numeric scanner tokens submit without the legacy pause", "NUMERIC_AUTO_SUBMIT_DELAY_MS = 0"],
  ["automatic single-row fallback avoids the bulk endpoint", "rows.length === 1"],
  ["single-row fallback uses the record endpoint", '"/api/payroll/records"'],
  ["restored multi-row recovery retains the bulk endpoint", '"/api/payroll/records/bulk"'],
  ["session history persists during browser idle time", "requestIdleCallback"],
  ["new scan enters saving state", "? { ...record, saveStatus: \"saving\", saveError: null }"],
  ["automatic success feedback", "page.payrollScan.autoSavedRecord"],
  ["restored pending scans resume automatically", "if (restoredPending.length > 0) void saveRecordsToPayrollRef.current(restoredPending);"],
  ["failed scan retains retry", "record.saveStatus === \"error\""],
  ["saved records cannot be locally undone", "record.saveStatus !== \"saved\" && record.saveStatus !== \"saving\""],
  ["typed employee number resolves through payroll API", "/api/payroll/employees/resolve?employee_no="],
  ["selected employee shows the real employee number", "currentEmployee.employee_no ||"],
  ["scanner input explains employee-number entry", "page.payrollScan.scanPlaceholder"],
];

for (const [name, contract] of required) {
  if (!source.includes(contract)) throw new Error(`Missing ${name} contract`);
}

const forbidden = [
  "page.payrollScan.saveToPayroll",
  "page.payrollScan.saveAllTitle",
  "page.payrollScan.saveAll\")}</span>",
];
for (const contract of forbidden) {
  if (source.includes(contract)) throw new Error(`Manual-save UI remains: ${contract}`);
}

console.log("Payroll scan autosave contract passed.");
