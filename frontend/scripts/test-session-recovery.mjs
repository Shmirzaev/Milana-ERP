import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

// Exercise the actual hook against SWR states without a server or real session.
const source = fs.readFileSync(new URL("../src/lib/auth.ts", import.meta.url), "utf8");
function run(state) {
  const exports = {};
  let options;
  const dependencies = {
    react: { useEffect() {}, useState: () => [true, () => {}] },
    swr: { default: (_key, _fetcher, config) => { options = config; return state; } },
    "./api": { fetcher() {}, api: {} },
  };
  new Function("exports", "require", ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }))(
    exports, (name) => dependencies[name],
  );
  return { result: exports.useMe(), options };
}
const identity = { id: 1, permissions: ["inventory.receive"] };
for (const error of [new Error("503: Service unavailable"), new TypeError("Failed to fetch"), new Error("429: Too Many Requests")]) {
  const { result } = run({ data: identity, error, isLoading: false });
  assert.equal(result.hasToken, true, "temporary failure must preserve a confirmed session");
  assert.equal(result.me, identity);
  assert.equal(run({ error, isLoading: false }).result.hasToken, undefined, "unknown session is not a rejected session");
}
for (const status of [401, 403]) {
  const { result, options } = run({ data: identity, error: new Error(`${status}: rejected`), isLoading: false });
  assert.equal(result.hasToken, false);
  assert.equal(result.me, undefined, "rejected session cannot expose cached identity");
  assert.equal(options.shouldRetryOnError(new Error(`${status}: rejected`)), false);
}
assert.equal(run({ data: identity, isLoading: false }).result.hasToken, true);
assert.equal(run({ isLoading: true }).result.hasToken, undefined);
assert.equal(run({ error: new Error("503: unavailable"), isLoading: false }).options.shouldRetryOnError(new Error("503: unavailable")), true);
console.log("Session recovery: temporary failures retained; genuine rejection blocked; retries bounded.");

const runtime = await import("react/jsx-runtime");
const gateSource = ts.transpile(fs.readFileSync(new URL("../src/components/AuthGate.tsx", import.meta.url), "utf8"), {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
});
for (const [hasToken, me] of [[undefined, undefined], [true, { ...identity, factory_code: "MIL", available_factories: ["MIL"] }], [false, undefined], [true, { ...identity, factory_code: "ECO", available_factories: ["ECO"], sewing_band_id: 64 }]]) {
  const effects = [], redirects = [], exports = {};
  let logouts = 0;
  new Function("exports", "require", gateSource)(exports, name => {
    if (name === "react/jsx-runtime") return runtime;
    if (name === "react") return { useEffect: fn => effects.push(fn), useState: initial => [initial, () => {}] };
    if (name === "swr") return { SWRConfig: "SWRConfig" };
    if (name === "next/navigation") return { usePathname: () => "/", useSearchParams: () => new URLSearchParams(), useRouter: () => ({ replace: path => redirects.push(path) }) };
    if (name === "@/lib/auth") return { useMe: () => ({ me, hasToken, error: new Error("503: unavailable"), loading: false, refresh: async () => {} }), can: () => true };
    if (name === "@/lib/api") return { api: { logout: async () => { logouts++; } } };
    if (name === "@/lib/access") return { isSewingRole: () => false, sewingWorkspaceHome: () => "/", factoryWorkspaceHome: () => "/", hasInventoryPathAccess: () => true };
    if (name === "@/lib/i18n") return { useT: () => ({ t: key => key }) };
    if (name === "@/lib/priceCalculationRequests") return {};
    throw new Error(name);
  });
  const rendered = exports.default({ children: "workspace" });
  effects.forEach(fn => fn());
  assert.equal(logouts, 0);
  assert.deepEqual(redirects, hasToken === false ? ["/login"] : []);
  if (hasToken === undefined) assert.equal(rendered.props.role, "alert");
  if (hasToken === true) assert.equal(rendered.props.children, "workspace");
}
console.log("AuthGate: outage retry, cached workspace, and definitive rejection passed.");
