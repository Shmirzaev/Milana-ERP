import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/useHrCalendarEmployees.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const calls = [];
function useSWR(key, fetcher) {
  calls.push({ key, fetcher });
  return { data: key ? [{ id: 7, full_name: "Ada" }] : undefined };
}
const module = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "swr") return { default: useSWR };
  if (name === "@/lib/api") return { fetcher: async () => [] };
  throw new Error(`Unexpected dependency: ${name}`);
}, module.exports, module);

const useHrCalendarEmployees = module.exports.useHrCalendarEmployees;
assert.equal(useHrCalendarEmployees(false).data, undefined);
assert.equal(calls.at(-1).key, null, "closed calendar modal must not fetch employees");
assert.deepEqual(useHrCalendarEmployees(true).data, [{ id: 7, full_name: "Ada" }]);
assert.equal(calls.at(-1).key, "/api/employees", "open calendar modal must load employee choices");
assert.equal(useHrCalendarEmployees(false).data, undefined);
assert.equal(calls.at(-1).key, null, "closing the modal must disable the employee fetch again");
assert.deepEqual(useHrCalendarEmployees(true).data, [{ id: 7, full_name: "Ada" }]);
assert.equal(calls.at(-1).key, "/api/employees", "reopening the modal must restore employee choices");
assert.equal(calls.length, 4, "each modal state transition should execute exactly one hook call");
console.log("PASS: HR calendar employee directory fetch is gated by the add-event modal and hook behavior executes.");
