import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const exports = {};
const helper = fs.readFileSync(new URL("../src/lib/stocktakeRecovery.ts", import.meta.url), "utf8");
new Function("exports", ts.transpile(helper, { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS }))(exports);
const { stocktakePendingPrefix, addStocktakePending, removeStocktakePending, readStocktakePending, migrateStocktakePending, stocktakeSelectionKey, readStocktakeSelection } = exports;

class MemoryStorage {
  values = new Map();
  get length() { return this.values.size; }
  key(index) { return [...this.values.keys()][index] ?? null; }
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}
const storage = new MemoryStorage();
const prefix = stocktakePendingPrefix(7, 11);
const scan = (id, code = id, createdAt = 1) => ({ id, code, createdAt });

// Independent tabs append and acknowledge individual keys without writing stale queue copies.
addStocktakePending(storage, prefix, scan("a", "PACK-A"));
const tabA = readStocktakePending(storage, prefix);
addStocktakePending(storage, prefix, scan("b", "PACK-B", 2));
removeStocktakePending(storage, prefix, tabA[0].id);
assert.deepEqual(readStocktakePending(storage, prefix).map(row => row.code), ["PACK-B"]);
addStocktakePending(storage, prefix, scan("c", "PACK-C", 3));
const reloaded = readStocktakePending(storage, prefix);
assert.deepEqual(reloaded.map(row => row.code), ["PACK-B", "PACK-C"]);
assert.deepEqual(readStocktakePending(storage, stocktakePendingPrefix(8, 11)), []);
assert.deepEqual(readStocktakePending(storage, stocktakePendingPrefix(7, 12)), []);
removeStocktakePending(storage, prefix, "a");
assert.equal(readStocktakePending(storage, prefix).length, 2, "duplicate acknowledgements cannot remove the next scan");

// The previous session-only queue is migrated once and survives a partial storage failure.
const legacy = new MemoryStorage();
legacy.setItem("erp:stocktake:7:12:pending", JSON.stringify(["OLD-A", "OLD-B"]));
const durable = new MemoryStorage();
const originalSet = durable.setItem.bind(durable);
let writes = 0;
durable.setItem = (key, value) => { if (++writes === 2) throw new Error("quota"); originalSet(key, value); };
assert.throws(() => migrateStocktakePending(durable, legacy, 7, 12), /quota/);
assert(legacy.getItem("erp:stocktake:7:12:pending"));
durable.setItem = originalSet;
migrateStocktakePending(durable, legacy, 7, 12);
migrateStocktakePending(durable, legacy, 7, 12);
assert.equal(legacy.getItem("erp:stocktake:7:12:pending"), null);
assert.deepEqual(readStocktakePending(durable, stocktakePendingPrefix(7, 12)).map(row => row.code), ["OLD-A", "OLD-B"]);
durable.setItem(stocktakePendingPrefix(7, 12) + "bad", '{"id":"different","code":"BAD","createdAt":1}');
assert.throws(() => readStocktakePending(durable, stocktakePendingPrefix(7, 12)), /Invalid/);
assert.equal(durable.length, 3, "invalid storage is retained, not silently discarded");

storage.setItem(stocktakeSelectionKey(7), "11");
assert.equal(readStocktakeSelection(storage, 7), 11);
assert.equal(readStocktakeSelection(storage, 8), null);
for (const value of ["-1", "0", "1.5", "NaN", "9007199254740992"]) {
  storage.setItem(stocktakeSelectionKey(7), value);
  assert.equal(readStocktakeSelection(storage, 7), null);
}

// Exercise the actual async drain handler, including a tab removing its in-flight entry.
const component = fs.readFileSync(new URL("../src/components/StocktakeSession.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("StocktakeSession.tsx", component, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let drainSource;
function visit(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === "drain") drainSource = node.getText(ast);
  ts.forEachChild(node, visit);
}
visit(ast);
assert(drainSource);
const js = ts.transpile(drainSource, { target: ts.ScriptTarget.ES2020 });
async function runDrain({ reject = false, unmount = false, completed = false } = {}) {
  const store = new MemoryStorage();
  addStocktakePending(store, prefix, scan("first", "PACK-FIRST"));
  const queue = { current: readStocktakePending(store, prefix) };
  const mounted = { current: true }, saving = { current: false }, failed = { current: false };
  const calls = [], feedback = [], failures = [];
  let release;
  const response = new Promise((resolve, rejectPromise) => { release = reject ? () => rejectPromise(new Error("offline")) : () => resolve({ duplicate: false, row: { id: 1, scan_snapshot: { model_code: "XJ5614", quantity: 24 }, scanned_pieces: 24 } }); });
  const env = {
    queue, mounted, saving, failed, completed, localStorage: store, storageKey: prefix, base: "/api/warehouse-stocktakes/11",
    removeStocktakePending, refreshQueue: () => { queue.current = readStocktakePending(store, prefix); },
    api: { post: (path, body) => { calls.push({ path, body }); return calls.length === 1 ? response : Promise.resolve({ duplicate: false, row: { id: 2 } }); } },
    setFeedback: value => feedback.push(value), setPending() {}, setUnsaved() {}, setFailure: value => failures.push(value), mutate() {},
  };
  const drain = new Function(...Object.keys(env), `${js}; return drain;`)(...Object.values(env));
  const running = drain();
  if (!completed) {
    if (!reject) removeStocktakePending(store, prefix, "first");
    addStocktakePending(store, prefix, scan("second", "PACK-SECOND", 2));
    queue.current = readStocktakePending(store, prefix);
    if (unmount) mounted.current = false;
    release();
  }
  await running;
  return { calls, feedback, failures, saving, failed, remaining: readStocktakePending(store, prefix) };
}
const success = await runDrain();
assert.deepEqual(success.calls.map(row => row.body.code), ["PACK-FIRST", "PACK-SECOND"]);
assert.equal(success.feedback[0].row.scan_snapshot.model_code, "XJ5614");
assert.equal(success.feedback[0].row.scanned_pieces, 24);
assert.deepEqual(success.remaining, []);
assert.equal(success.saving.current, false);
const offline = await runDrain({ reject: true });
assert.equal(offline.calls.length, 1);
assert.equal(offline.failed.current, true);
assert.deepEqual(offline.remaining.map(row => row.code), ["PACK-FIRST", "PACK-SECOND"]);
const gone = await runDrain({ unmount: true });
assert.equal(gone.calls.length, 1, "unmounted/user-switched session must stop draining");
assert.deepEqual(gone.feedback, []);
assert.deepEqual(gone.remaining.map(row => row.code), ["PACK-SECOND"]);
assert.equal((await runDrain({ completed: true })).calls.length, 0);
console.log("PASS: stocktake durable user/count recovery, cross-tab acknowledgements, interrupted migration, saved selection, immediate scan evidence and async unmount/failure guards.");
