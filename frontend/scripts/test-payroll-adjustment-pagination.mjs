import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/payroll/page.tsx", import.meta.url), "utf8");
const schema = fs.readFileSync(new URL("../../backend/app/schemas/payroll.py", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../../backend/app/api/routes/payroll.py", import.meta.url), "utf8");

assert.match(page, /useSWRInfinite<PayrollAdjustmentPage>/, "adjustments should use paged SWR loading");
assert.match(page, /const params = new URLSearchParams\(summaryQuery\)/, "adjustment pages should preserve current payroll filters");
assert.match(page, /params\.set\("page_size", "50"\)/, "adjustments should request 50 rows per page");
assert.match(page, /previousPage && !previousPage\.has_more/, "paging should stop when the backend has no more rows");
assert.match(page, /adjustmentPages\?\.flatMap\(\(page\) => page\.rows\)/, "only returned rows should be rendered");
assert.match(page, /adjustmentPages\?\.\[0\]\?\.total/, "the exact backend total should remain visible");
assert.match(page, /setAdjustmentSize\(\(size\) => size \+ 1\)/, "Load more should request the next page");
assert.match(page, /await setAdjustmentSize\(1\)[\s\S]*await mutateAdjustmentPages\(\)/, "refreshes after mutations should return to page one and revalidate");
assert.doesNotMatch(page, /useSWR<PayrollAdjustment\[\]>/, "the initial render must not fetch an unpaged adjustment array");
assert.match(schema, /class PayrollAdjustmentPageOut[\s\S]*?rows: list\[PayrollAdjustmentRowOut\][\s\S]*?total: int[\s\S]*?has_more: bool/, "backend page envelope should expose labeled rows, exact total, and has_more");
assert.match(route, /@router\.get\("\/adjustments"[\s\S]*?page_size: Annotated\[int \| None, Query\(ge=1, le=500\)\]/, "legacy-compatible endpoint should accept optional paging");

console.log("PASS: payroll adjustments use filtered 50-row lazy pages with exact totals and mutation refresh.");
