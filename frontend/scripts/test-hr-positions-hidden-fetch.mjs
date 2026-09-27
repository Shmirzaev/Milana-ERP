import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/usePositionDepartments.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const calls = [];
function useSWR(key, fetcher) { calls.push({ key, fetcher }); return { data: key ? [{ id: 4, name: "Cutting" }] : undefined }; }
const module = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "swr") return { default: useSWR };
  if (name === "@/lib/api") return { fetcher: async () => [] };
  throw new Error(`Unexpected dependency: ${name}`);
}, module.exports, module);

const hook = module.exports.usePositionDepartments;
assert.equal(hook(null).data, undefined);
assert.equal(calls.at(-1).key, null, "closed position modal must not fetch departments");
assert.deepEqual(hook("new").data, [{ id: 4, name: "Cutting" }]);
assert.equal(calls.at(-1).key, "/api/departments", "open position modal must load department choices");
assert.deepEqual(hook({ id: 9 }).data, [{ id: 4, name: "Cutting" }]);
assert.equal(calls.at(-1).key, "/api/departments", "editing a position must retain department choices");
assert.equal(hook(null).data, undefined);
assert.equal(calls.at(-1).key, null, "closing the modal must disable the department fetch again");
assert.equal(calls.length, 4);
console.log("PASS: HR position department directory fetch is gated by the edit modal and hook transitions execute.");
