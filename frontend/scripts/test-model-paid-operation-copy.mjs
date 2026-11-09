import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
import { test } from "node:test";

function compile(file, deps = {}) {
  const code = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  new Function("exports", "require", code)(exports, name => {
    assert.ok(name in deps, `Unexpected dependency ${name}`);
    return deps[name];
  });
  return exports;
}
const operations = compile("src/lib/modelPaidOperations.ts");
const sourceRow = { id: "original", selected: false, name: "Button sewing", code: "BTN", section: "buttons",
  sewingFactory: "besttex", rate: "123.456", currency: "UZS", duration: "0.75", sourceOrder: 7,
  sourceStage: "buttons", changeDirection: "increase", finalOperation: true, legacySourceId: "legacy-1",
  quantityMode: "custom", customQuantity: 900, copies: 2, splitMode: "custom", splitQuantities: [3, 4] };

test("copy preserves rates, disabled rows and provenance but resets model quantity", () => {
  const details = { paid_operations: [structuredClone(sourceRow)], general: { note: "source" } };
  const before = structuredClone(details);
  const rows = operations.paidOperationsForModelCopy(details, ["milana", "besttex", "eco_cotton"]);
  assert.deepEqual(rows, [{ ...sourceRow, quantityMode: "batch", customQuantity: 0 }]);
  rows[0].splitQuantities.push(8);
  assert.deepEqual(details, before);
  const target = { general: { note: "target" }, sewing: { note: "keep" } };
  const copied = operations.withPaidOperations(target, rows);
  assert.deepEqual(copied.general, { note: "target" });
  assert.deepEqual(copied.sewing, { note: "keep" });
  assert.equal(target.paid_operations, undefined);
});

test("empty and malformed sources never create default operations", () => {
  for (const details of [null, {}, { paid_operations: [] }, { paid_operations: null }, { paid_operations: "bad" }]) {
    assert.deepEqual(operations.paidOperationsForModelCopy(details, ["milana"]), []);
  }
  assert.deepEqual(operations.paidOperationsForModelCopy({ paid_operations: [sourceRow] }, ["eco_cotton"]), []);
});

test("shared legacy operations copy to allowed factories and remain isolated", () => {
  const shared = { ...sourceRow };
  delete shared.sewingFactory;
  delete shared.legacySourceId;
  const rows = operations.paidOperationsForModelCopy({ paidOperations: [shared] }, ["milana", "eco_cotton"]);
  assert.deepEqual(rows.map(row => [row.sewingFactory, row.rate, row.selected]), [["milana", "123.456", false], ["eco_cotton", "123.456", false]]);
  assert.equal(new Set(rows.map(row => row.id)).size, 2);
});

function walk(node, out = []) {
  if (Array.isArray(node)) node.forEach(child => walk(child, out));
  else if (node && typeof node === "object") { out.push(node); walk(node.props?.children, out); }
  return out;
}
function harness(isUsluga = false) {
  let cursor = 0, mounted = false;
  const state = [], cleanups = [], reads = [], copies = [];
  let respond = async () => ({ details_json: { paid_operations: [sourceRow] } });
  const element = (type, props) => ({ type, props: props || {} });
  const Component = compile("src/components/ModelPaidOperationsCopy.tsx", {
    react: {
      useState(initial) { const i = cursor++; if (!(i in state)) state[i] = initial;
        return [state[i], value => { state[i] = value; }]; },
      useRef(initial) { const i = cursor++; if (!(i in state)) state[i] = { current: initial }; return state[i]; },
      useEffect(effect) { if (!mounted) cleanups.push(effect()); },
    },
    "react/jsx-runtime": { jsx: element, jsxs: element },
    "lucide-react": { Copy: "icon" },
    "@/lib/api": { api: { get: async url => { reads.push(url); return respond(); } } },
    "@/lib/i18n": { useT: () => ({ lang: "en", t: key => key }) },
    "@/lib/errorMessages": { localizeError: x => x },
    "@/components/ModelAsyncSelect": { default: "selector" },
    "@/lib/modelPaidOperations": operations,
  }).default;
  function render() { cursor = 0; const nodes = walk(Component({ targetId: 2, isUsluga,
    factories: ["milana", "besttex", "eco_cotton"], onCopy: rows => copies.push(rows) })); mounted = true; return nodes; }
  function select(value) { render().find(n => n.type === "selector").props.onChange(value); }
  async function click() { render().find(n => n.type === "button").props.onClick(); await new Promise(setImmediate); }
  return { render, select, click, reads, copies, response: fn => { respond = fn; }, unmount: () => cleanups.forEach(fn => fn?.()) };
}

test("source read is namespace-scoped; empty/error preserve target; retry copies once", async () => {
  for (const usluga of [false, true]) {
    const h = harness(usluga);
    h.select(2); await h.click(); assert.equal(h.reads.length, 0);
    h.select(8); h.response(async () => { throw new Error("403: Refused"); });
    await h.click(); assert.equal(h.copies.length, 0);
    assert.ok(h.render().some(n => n.props.role === "alert"));
    h.response(async () => ({ details_json: { paid_operations: [] } }));
    await h.click(); assert.equal(h.copies.length, 0);
    h.response(async () => ({ details_json: { paid_operations: [sourceRow] } }));
    await h.click(); assert.equal(h.copies.length, 1);
    assert.ok(h.render().some(n => n.props.role === "status"));
    assert.ok(!h.render().some(n => n.props.role === "alert"));
    assert.deepEqual(h.reads, Array(3).fill(usluga ? "/api/usluga/models/8" : "/api/models/8"));
  }
});

test("duplicate clicks share a single read and unmount discards late source response", async () => {
  const h = harness(); let resolve;
  h.select(8); h.response(() => new Promise(done => { resolve = done; }));
  await h.click(); await h.click(); assert.equal(h.reads.length, 1);
  h.unmount(); resolve({ details_json: { paid_operations: [sourceRow] } });
  await new Promise(setImmediate); assert.equal(h.copies.length, 0);
});
