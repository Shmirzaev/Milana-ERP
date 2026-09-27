import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/payroll/page.tsx", import.meta.url), "utf8");
const schema = fs.readFileSync(new URL("../../backend/app/schemas/payroll.py", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../../backend/app/api/routes/payroll.py", import.meta.url), "utf8");

assert.match(page, /useSWRInfinite<PayrollRecordPage>/, "record history must request pages");
assert.match(page, /\/api\/payroll\/records\?\$\{recordsQuery\}&page=\$\{index \+ 1\}&page_size=50/, "each request must preserve filters and advance the page");
assert.match(page, /previousPage && !previousPage\.has_more/, "loading must stop after the final page");
assert.match(page, /recordPages\?\.flatMap\(\(page\) => page\.rows\)/, "loaded records must accumulate across pages");
assert.match(page, /setRecordSize\(\(size\) => size \+ 1\)/, "Load more must reach records beyond the first page");
assert.match(page, /recordPages\?\.\[0\]\?\.total/, "the table must use the exact backend total");
assert.doesNotMatch(page, /limit["', ]+300|useSWR<PayrollRecord\[\]>/, "the former 300-row ceiling must be removed");
assert.match(schema, /class PayrollRecordPageOut[\s\S]*?rows: list\[PayrollRecordOut\][\s\S]*?total: int[\s\S]*?has_more: bool/, "the API must expose a paged envelope");
assert.match(route, /@router\.get\("\/records"[\s\S]*?page_size: Annotated\[int \| None, Query\(ge=1, le=500\)\]/, "the API must accept bounded page sizes");

console.log("PASS: Payroll records use filtered 50-row pages with exact totals and Load more.");
