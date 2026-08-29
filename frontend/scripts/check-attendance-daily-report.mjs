import assert from "node:assert/strict";
import { readFileSync } from "node:fs";


const page = readFileSync(new URL("../src/app/(app)/attendance/page.tsx", import.meta.url), "utf8");
const route = readFileSync(new URL("../../backend/app/api/routes/attendance.py", import.meta.url), "utf8");
const report = readFileSync(new URL("../../backend/app/services/attendance_reports.py", import.meta.url), "utf8");

for (const field of ["arrival_at", "departure_at", "worked_minutes", "attendance_status"]) {
  assert.ok(page.includes(field), `Attendance page is missing ${field}`);
  assert.ok(route.includes(`"${field}"`), `Attendance API is missing ${field}`);
}
assert.ok(page.includes("/api/attendance/reports/daily.xlsx"), "Attendance Excel action is missing");
assert.ok(route.includes('@router.get("/reports/daily.xlsx")'), "Attendance Excel endpoint is missing");
assert.ok(route.includes('"single_scan"'), "Single-scan handling is missing");
assert.ok(report.includes("build_daily_attendance_xlsx"), "Attendance workbook builder is missing");

const requiredLocaleKeys = [
  "attendance.arrival",
  "attendance.departure",
  "attendance.timeBetweenScans",
  "attendance.completeDay",
  "attendance.singleScan",
  "attendance.absent",
  "attendance.excelReport",
  "attendance.reportDownloadFailed",
];
for (const language of ["en", "ru", "uz"]) {
  const locale = readFileSync(new URL(`../src/lib/i18n/locales/${language}-supplemental.ts`, import.meta.url), "utf8");
  for (const key of requiredLocaleKeys) {
    assert.ok(locale.includes(`"${key}"`), `${language} locale is missing ${key}`);
  }
}

console.log("Attendance daily arrival/departure and Excel report contract passed.");
