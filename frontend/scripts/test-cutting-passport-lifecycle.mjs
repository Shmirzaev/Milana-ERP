import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
const ast = ts.createSourceFile("page.tsx", fs.readFileSync("src/app/(app)/cutting-passports/page.tsx", "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const effects = [];
function visit(n) { if (ts.isCallExpression(n) && n.expression.getText(ast) === "useEffect") effects.push(n); ts.forEachChild(n, visit); } visit(ast);
function effect(name) { const e = effects.find(n => n.arguments[0].getText(ast).includes(name)); assert.ok(e); return ts.transpileModule(`(${e.arguments[0].getText(ast)})`, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText; }
let timers = new Map(), id = 0, applied = "";
const c = vm.createContext({ q: "", setAppliedSearch: value => { applied = value; }, setTimeout: (fn, ms) => { assert.equal(ms, 300); timers.set(++id, fn); return id; }, clearTimeout: key => timers.delete(key) });
const debounce = vm.runInContext(effect("setAppliedSearch"), c);
c.q = " a "; let cleanup = debounce(); c.q = " ab "; cleanup(); cleanup = debounce(); assert.equal(applied, ""); assert.equal(timers.size, 1); [...timers.values()][0](); assert.equal(applied, "ab"); cleanup();
let opens = 0, selections = [], pending = [];
Object.assign(c, { cuttingDepartment: "CUT", requestedOrder: "42", requestedPassport: null, openedRequest: { current: "" }, pendingOrderRevision: { current: 0 }, pendingOrderInitial: { current: null }, EMPTY_FORM: {}, businessDate: () => "2026-11-17", draftRevision: { current: 0 }, orderRequest: { current: 0 }, mounted: { current: true }, showForm: false, prodOrders: undefined, ordersError: undefined, openCreate: () => { opens++; }, setForm: () => {}, selectProductionOrder: (...args) => selections.push(args), api: { get: () => new Promise(resolve => pending.push(resolve)) }, openEdit: value => { c.edited = value; }, setErr: () => {} });
const initialize = vm.runInContext(effect("openedRequest"), c);
initialize(); assert.equal(opens, 1); c.showForm = true; initialize(); assert.equal(selections.length, 0); c.draftRevision.current++; c.prodOrders = [{ id: 42 }]; initialize(); assert.deepEqual(selections, [["42", true]]); initialize(); assert.equal(selections.length, 1);
c.openedRequest.current = ""; c.requestedOrder = null; c.requestedPassport = "7"; initialize(); c.orderRequest.current++; pending.shift()({ id: 7 }); await new Promise(resolve => setImmediate(resolve)); assert.equal(c.edited, undefined);
console.log("Search debounce and deep-link initialization lifecycle pass.");
