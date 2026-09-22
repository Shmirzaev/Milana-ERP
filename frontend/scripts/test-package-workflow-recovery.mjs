import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const storage = new Map();
const events = [];
const calls = [];
let response = { id: 8, run_no: "RUN-8" };
let labelError = null;
const api = {
  post: async (path, body) => { calls.push({ path, body }); return response; },
  openLabel: async () => { if (labelError) throw new Error(labelError); },
};
const packageSource = ts.transpileModule(fs.readFileSync(new URL("../src/lib/packageWorkflow.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const packageModule = { exports: {} };
new Function("require", "exports", "module", packageSource)(id => id === "@/lib/api" ? { api } : {}, packageModule.exports, packageModule);
const packageWorkflow = packageModule.exports;
const react = {
  useState: initial => [typeof initial === "function" ? initial() : initial, () => {}],
  useEffect: effect => effect(),
};
const jsx = (type, props) => ({ type, props: props || {} });
const componentSource = ts.transpileModule(fs.readFileSync(new URL("../src/components/PendingPackageWorkflow.tsx", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
const componentModule = { exports: {} };
new Function("require", "exports", "module", componentSource)(id => {
  if (id === "react") return react;
  if (id === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "fragment" };
  if (id === "@/lib/api") return { api };
  if (id === "@/lib/auth") return { useMe: () => ({ me: { id: 7 } }) };
  if (id === "@/lib/i18n") return { useT: () => ({ lang: "en" }) };
  if (id === "@/lib/packageWorkflow") return packageWorkflow;
  throw new Error(`unexpected import ${id}`);
}, componentModule.exports, componentModule);
const PendingPackageWorkflow = componentModule.exports.default;
const path = "/api/packages/print-runs";
const body = { packages: [1], requestKey: "request-1" };
storage.set(`package-request:7:${path}`, JSON.stringify({ requestKey: body.requestKey, body }));
globalThis.sessionStorage = { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
globalThis.window = { dispatchEvent: event => events.push(event.type), addEventListener() {}, removeEventListener() {} };

async function click(onResolved = async () => {}) {
  const tree = PendingPackageWorkflow({ path, onResolved });
  const button = tree.props.children.find(child => child?.type === "button");
  assert(button, "pending component must render its retry handler");
  await button.props.onClick();
}

response = { status: "completed" };
await click();
assert(storage.has(`package-request:7:${path}`), "incomplete response restores the pending request");
assert.equal(calls.length, 1);

response = { id: 9, run_no: "RUN-9" };
labelError = "403: forbidden";
await click();
assert.equal(calls.length, 2, "label permission failure must not repost the receipt");
assert.equal(storage.has(`package-request:7:${path}`), false, "committed receipt clears retry state");
labelError = null;

storage.set(`package-request:7:${path}`, JSON.stringify({ requestKey: "request-3", body }));
response = { id: 10, run_no: "RUN-10" };
await click();
assert.equal(calls.length, 3, "normal retry posts once");
assert.equal(storage.has(`package-request:7:${path}`), false);

storage.set(`package-request:7:${path}`, JSON.stringify({ requestKey: "request-4", body }));
response = { id: 11, run_no: "RUN-11" };
await click(async () => { throw new Error("refresh failed"); });
assert.equal(calls.length, 4, "refresh failure after commit must not repost the receipt");
assert.equal(storage.has(`package-request:7:${path}`), false, "refresh failure must keep the committed receipt resolved");
console.log("PASS: package workflow recovery handler restores incomplete responses, clears committed receipts after label denial without reposting, and preserves normal success.");
