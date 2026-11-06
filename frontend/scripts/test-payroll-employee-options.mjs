import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/payroll/page.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../../backend/app/api/routes/payroll.py", import.meta.url), "utf8");
const schema = fs.readFileSync(new URL("../../backend/app/schemas/payroll.py", import.meta.url), "utf8");

assert.doesNotMatch(page, /useSWR<Employee\[]>\("\/api\/employees"/, "payroll must not load the legacy capped directory");
assert.equal((page.match(/\/api\/payroll\/employees\/options/g) || []).length, 2, "filter and adjustment selectors use bounded employee options");
assert.match(page, /params\.set\("selected_id", filters\.employeeId\)/, "the current filter selection is hydrated outside the visible page");
assert.match(page, /params\.set\("selected_id", adjustmentForm\.employee_id\)/, "the current adjustment employee is hydrated across search changes");
assert.match(page, /data: adjustmentEmployeePages[\s\S]*?if \(!canManage\) return null;/, "read-only payroll viewers do not fetch options for the hidden adjustment form");
assert.match(page, /employeeFilterPagesAreCurrent[\s\S]*page\.search === debouncedEmployeeFilterSearch/, "stale filter pages are hidden after a query change");
assert.match(page, /adjustmentEmployeePagesAreCurrent[\s\S]*page\.search === debouncedAdjustmentEmployeeSearch/, "stale adjustment options are hidden after a query change");
assert.match(page, /onLoadMore=\{\(\) => void setEmployeeFilterSize\(\(size\) => size \+ 1\)\}/);
assert.match(page, /onLoadMore=\{\(\) => void setAdjustmentEmployeeSize\(\(size\) => size \+ 1\)\}/);
assert.match(page, /adjustment\.employee_name \|\| t\("page\.payroll\.employeeId"/, "adjustment rows use the page-scoped employee label");
assert.match(page, /record\.department_name \|\|[\s\S]*record\.department_id/, "record department fallback uses row projection, not employee directory");
assert.doesNotMatch(page, /employees\.find\(/, "payroll records must not resolve labels from an unbounded client directory");

assert.match(route, /@router\.get\("\/employees\/options"\)[\s\S]*Query\(ge=1, le=50\)[\s\S]*selected_id/, "employee options are capped at 50 and can retain a selected ID");
assert.match(route, /Employee\.factory_code == factory_code[\s\S]*Employee\.id == selected_id/, "selected employee lookup remains factory-scoped");
assert.match(route, /@router\.get\("\/adjustments"[\s\S]*employee_labels[\s\S]*"employee_name": row\.full_name/, "paged adjustments project employee names on returned rows");
assert.match(schema, /class PayrollAdjustmentPageOut[\s\S]*rows: list\[PayrollAdjustmentRowOut\]/, "only the paged adjustment schema adds row labels");
assert.match(schema, /class PayrollAdjustmentOut[\s\S]*?created_at: datetime[\s\S]*?class PayrollAdjustmentRowOut/, "legacy adjustment schema remains unchanged");

console.log("PASS: payroll employee lookup is bounded, searchable, selected-ID safe, and row labels do not depend on a 500-row directory.");
