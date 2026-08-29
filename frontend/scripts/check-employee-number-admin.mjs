import fs from "node:fs";

const page = fs.readFileSync("src/app/(app)/hr/employees/page.tsx", "utf8");
const dict = fs.readFileSync("src/lib/i18n/dict.ts", "utf8");
const locales = [
  fs.readFileSync("src/lib/i18n/locales/en-base.ts", "utf8"),
  fs.readFileSync("src/lib/i18n/locales/ru-base.ts", "utf8"),
  fs.readFileSync("src/lib/i18n/locales/uz-base.ts", "utf8"),
];

const requiredPageFragments = [
  "employee_no: string | null",
  "function effectiveEmployeeNumber",
  't("field.employeeNo")',
  'pattern="[0-9]+"',
  "employee_no: edit.employee_no.trim() || null",
  "EMP-${String(employee.id).padStart(4, \"0\")}",
];

for (const fragment of requiredPageFragments) {
  if (!page.includes(fragment)) {
    throw new Error(`Employees page is missing employee-number contract: ${fragment}`);
  }
}

for (const source of [dict, ...locales]) {
  if (!source.includes('"field.employeeNo"')) {
    throw new Error("An i18n source is missing field.employeeNo");
  }
}

console.log("Employee number admin UI contract passed.");
