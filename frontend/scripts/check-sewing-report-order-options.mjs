import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync("src/app/(app)/payroll/reports/sewing-production/page.tsx", "utf8");
const types = fs.readFileSync("src/lib/sewingProductionReport.ts", "utf8");

assert.match(page, /useSWRInfinite<SewingProductionReportOrderOptionPage>/, "order options should load incrementally");
assert.match(page, /new URLSearchParams\(\{ limit: "50", offset: String\(index \* 50\) \}\)/, "order requests should be capped at 50 options");
assert.match(page, /reports\/sewing-production\/orders\?\$\{params\.toString\(\)\}/, "order options should use the searchable page endpoint");
assert.match(page, /params\.set\("selected_value", draft\.orderNo\)/, "the selected historical option should be retained by the server");
assert.match(page, /selectedOrderOption/, "the selected option should be merged into the visible order choices");
assert.match(page, /serverFilter\s+loading=\{isOrderOptionsLoading \|\| isOrderOptionsValidating\}/, "order search should use server filtering and expose request state");
assert.match(page, /include_orders: "false"/, "other option requests should skip order history");
assert.match(types, /selected_option\?: ReportOption \| null/, "the page contract should carry retained selected values");

console.log("PASS: sewing production order options are server-searched, paged, and retain historical selections.");
