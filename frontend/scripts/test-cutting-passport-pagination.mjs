import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const hookSource = fs.readFileSync(new URL("../src/lib/useCuttingPassportPages.ts", import.meta.url), "utf8");
const pageSource = fs.readFileSync(new URL("../src/app/(app)/cutting-passports/page.tsx", import.meta.url), "utf8");
const backendTest = fs.readFileSync(new URL("../../backend/app/tests/test_cutting_passport_list_query_growth.py", import.meta.url), "utf8");
assert.match(pageSource, /useCuttingPassportPages<Passport>\(cuttingDepartment, q\)/, "screen must use the paged query");
assert.match(pageSource, /setPassportPageCount\(passportPageCount \+ 1\)/, "visible Load more must request the next page");
assert.doesNotMatch(pageSource, /cutting-passports\?[^"`]*limit=500/, "screen must not use the capped legacy list");
assert.match(backendTest, /for count in \(1, 50, 401\)/, "SQL page regression must cover more than one page");
assert.match(backendTest, /assert len\(statements\) == 5/, "server page reads must stay query bounded");

const output = ts.transpileModule(hookSource, { compilerOptions: {
  module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2020,
  jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const all = Array.from({ length: 401 }, (_, index) => ({ id: 401 - index, passport_no: `CP-${401 - index}` }));
let size = 1;
let previousScope = "";
const keys = [];
let mutated = false;
const exports = {};
new Function("exports", "require", output)(exports, name => ({
  react: { useMemo: factory => factory() },
  "swr/infinite": { default: keyFactory => {
    const first = keyFactory(0, null);
    const parsed = new URL(first, "http://local");
    const scope = `${parsed.searchParams.get("cutting_department_code")}:${parsed.searchParams.get("q")}`;
    if (scope !== previousScope) { size = 1; previousScope = scope; }
    const search = parsed.searchParams.get("q")?.toLowerCase() || "";
    const filtered = all.filter(row => row.passport_no.toLowerCase().includes(search));
    const pages = [];
    for (let index = 0; index < size; index += 1) {
      const key = keyFactory(index, pages.at(-1) || null);
      if (!key) break;
      keys.push(key);
      pages.push({
        rows: filtered.slice(index * 50, (index + 1) * 50),
        total: filtered.length,
        page: index + 1,
        page_size: 50,
        has_more: (index + 1) * 50 < filtered.length,
      });
    }
    return {
      data: pages, size,
      setSize(next) { size = next; },
      mutate() { mutated = true; },
      isLoading: false, isValidating: false,
    };
  } },
  "@/lib/api": { fetcher() {} },
})[name]);

let result = exports.useCuttingPassportPages("CUT", "");
assert.equal(result.rows.length, 50);
assert.equal(result.total, 401);
assert.equal(result.hasMore, true);
assert.equal(keys.length, 1);
assert.match(keys[0], /cutting_department_code=CUT&page=1&page_size=50$/);
result.setSize(result.size + 1);
keys.length = 0;
result = exports.useCuttingPassportPages("CUT", "");
assert.equal(result.rows.length, 100);
assert.equal(result.rows[50].id, 351);
assert.equal(keys.length, 2);
assert.match(keys[1], /page=2&page_size=50$/);
result.mutate();
assert.equal(mutated, true, "save/delete must still be able to revalidate loaded pages");

keys.length = 0;
result = exports.useCuttingPassportPages("ECT", " CP-397 ");
assert.deepEqual(result.rows.map(row => row.id), [397]);
assert.equal(result.total, 1);
assert.equal(result.hasMore, false);
assert.equal(keys.length, 1, "a new factory/search scope must reset to the first page");
assert.match(keys[0], /cutting_department_code=ECT&page=1&page_size=50&q=CP-397$/);

console.log("PASS: cutting passports use exact 50-row pages, query-scoped search, and bounded load more.");
