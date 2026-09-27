import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync("src/app/(app)/payroll/reports/sewing-production/page.tsx", "utf8");

assert.match(page, /params\.set\("include_options", "false"\)/, "the report page should skip embedded filter options");
assert.equal((page.match(/params\.set\("include_options", "false"\)/g) || []).length, 2, "both paged report reads and print reads should skip embedded options");
assert.match(page, /reports\/sewing-production\/options\$\{optionQuery\}/, "the page should retain its separate factory-scoped options request");

console.log("PASS: sewing production report reads avoid duplicate embedded options while keeping the options request.");
