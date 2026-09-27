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
const loadedModule = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "swr") return { default: useSWR };
  if (name === "@/lib/api") return { fetcher: async () => [] };
  throw new Error(`Unexpected dependency: ${name}`);
}, loadedModule.exports, loadedModule);

const useHrCalendarEmployees = loadedModule.exports.useHrCalendarEmployees;
function CalendarProbe(open) {
  return useHrCalendarEmployees(open);
}
assert.equal(CalendarProbe(false).data, undefined);
assert.equal(calls.at(-1).key, null, "closed calendar modal must not fetch employees");
assert.deepEqual(CalendarProbe(true).data, [{ id: 7, full_name: "Ada" }]);
assert.equal(calls.at(-1).key, "/api/employees", "open calendar modal must load employee choices");
assert.equal(CalendarProbe(false).data, undefined);
assert.equal(calls.at(-1).key, null, "closing the modal must disable the employee fetch again");
assert.deepEqual(CalendarProbe(true).data, [{ id: 7, full_name: "Ada" }]);
assert.equal(calls.at(-1).key, "/api/employees", "reopening the modal must restore employee choices");
assert.equal(calls.length, 4, "each modal state transition should execute exactly one hook call");
console.log("PASS: HR calendar employee directory fetch is gated by the add-event modal and hook behavior executes.");
