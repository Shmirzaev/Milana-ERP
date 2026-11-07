import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

// Actual component/controller and actual localized contracts with deterministic
// hook/SWR/API adapters. This is not connected-browser or physical visual proof.
const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
function compile(source, dependencies = {}) {
  const output = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  new Function("exports", "require", output)(exports, name => {
    assert.ok(name in dependencies, `Unexpected dependency: ${name}`);
    return dependencies[name];
  });
  return exports;
}
const source = read("../src/components/PlanningCuttingFactoryAction.tsx");
const contract = compile(read("../src/lib/cuttingFactory.ts"));
const authSource = read("../src/lib/auth.ts");
const authTree = ts.createSourceFile("auth.ts", authSource, ts.ScriptTarget.Latest, true);
const canNode = authTree.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === "can");
assert.ok(canNode);
const { can } = compile(canNode.getText(authTree));

function walk(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(walk);
  if (typeof tree.type === "function") return walk(tree.type(tree.props));
  return [tree, ...walk(tree.props?.children)];
}

function harness({ lang = "en", permissions = ["planning.production"], order } = {}) {
  let values = [], cursor = 0, tree, response, failure, refreshFailure, validating = false, loading = false;
  let granted = permissions;
  const writes = [], reads = [], refreshes = [];
  let changed = 0;
  const data = id => ({ production_order_id: id, cutting_department_code: "CUT", available_departments: ["CUT", "ECT"], can_change: true, lock_reason: null, changed: false });
  response = data(71);
  const copy = contract.cuttingFactoryMessages[lang];
  const t = key => ({ "common.save": "Save", "common.close": "Close", "common.saving": "Saving", "common.refresh": "Refresh", "common.loading": "Loading", "common.noData": "No data" })[key] || key;
  const deps = {
    react: { useState(initial) {
      const index = cursor++;
      if (!(index in values)) values[index] = initial;
      return [values[index], value => { values[index] = value; }];
    } },
    "react/jsx-runtime": awaitImportJsx(),
    swr: { default: key => {
      reads.push(key);
      return { data: key && !loading ? response : undefined, error: failure && key ? new Error(failure) : undefined,
        isLoading: loading && Boolean(key), isValidating: validating && Boolean(key), mutate: async (next, options) => {
          refreshes.push({ key, next, options });
          if (refreshFailure) throw new Error(refreshFailure);
          if (next) response = next;
          return response;
        } };
    } },
    "@/lib/api": { fetcher() {}, api: { patch: async (url, payload) => {
      writes.push({ url, payload });
      if (failure) throw new Error(failure);
      response = { ...data(Number(url.split("/")[3])), cutting_department_code: payload.cutting_department_code, changed: true };
      return response;
    } } },
    "@/lib/auth": { can },
    "@/lib/i18n": { useT: () => ({ lang, t }) },
    "@/lib/orderRef": { formatOrderReference: value => value },
    "@/lib/cuttingFactory": contract,
    "./Modal": { default: ({ open, children }) => open ? React.createElement("section", null, children) : null },
    "./SearchableSelect": { default: props => React.createElement("input", { "data-order-select": true, value: props.value || "", disabled: props.disabled, onChange: props.onChange, readOnly: true }) },
  };
  const Component = compile(source, deps).default;
  const render = () => { cursor = 0; tree = Component({ me: granted ? { permissions: granted } : undefined,
    orders: [{ id: 71, order_no: "SO-0071", production_no: "PO-0071" }, { id: 72, production_no: "PO-0072" }], order, onChanged: async () => { changed++; } }); return renderToStaticMarkup(tree); };
  const nodes = () => walk(tree);
  const button = label => nodes().find(node => node.type === "button" && node.props.children === label)?.props;
  const selectOrder = id => { nodes().find(node => node.props["data-order-select"]).props.onChange(id); return render(); };
  const open = () => { render(); button(copy.title).onClick(); const html = render(); return order ? html : selectOrder(71); };
  const target = value => { nodes().find(node => node.props.id === "cutting-factory-target").props.onChange({ target: { value } }); return render(); };
  const submit = async () => { await button("Save").onClick(); return render(); };
  return { render, open, selectOrder, target, submit, button, writes, reads, refreshes, copy, changed: () => changed,
    response: value => { response = value; }, fail: value => { failure = value; }, refreshFail: value => { refreshFailure = value; },
    pending: value => { loading = value; }, validating: value => { validating = value; }, permissions: value => { granted = value; },
  };
}

// Load the real JSX runtime once; keep the synchronous component harness simple.
import * as jsxRuntime from "react/jsx-runtime";
function awaitImportJsx() { return jsxRuntime; }

test("unprivileged or unknown actors have no action and trigger no capability read", () => {
  for (const permissions of [[], undefined]) {
    const ui = harness({ permissions: permissions ?? null });
    assert.equal(ui.render(), "");
    assert.deepEqual(ui.reads, [null]);
  }
  assert.match(harness({ permissions: ["*"] }).render(), /Change cutting factory/);
});

for (const lang of ["en", "ru", "uz"]) {
  test(`${lang}: real rendered labels, narrow payload, refresh, reopen and saved routing`, async () => {
    const ui = harness({ lang });
    assert.match(ui.open(), /Milana/);
    assert.equal(ui.button("Save").disabled, true);
    const ready = ui.target("ECT");
    assert.ok(ready.includes(ui.copy.destination));
    assert.equal(ui.button("Save").disabled, false);
    const saved = await ui.submit();
    assert.ok(saved.includes(ui.copy.saved));
    assert.match(saved, /Eco Cotton/);
    assert.deepEqual(ui.writes, [{ url: "/api/production-orders/71/cutting-factory", payload: { cutting_department_code: "ECT" } }]);
    assert.equal(ui.changed(), 1);
    assert.equal(ui.refreshes.length, 2);
    assert.equal(ui.button("Save").disabled, true);
    ui.button("Close").onClick(); ui.render();
    ui.open();
    assert.match(ui.render(), /Eco Cotton/);
    for (const reason of Object.values(ui.copy.reasons)) assert.ok(reason.length > 10);
  });
}

test("changing order ignores stale capability belonging to previous order", async () => {
  const ui = harness(); ui.open(); ui.target("ECT");
  const pending = ui.selectOrder(72);
  assert.doesNotMatch(pending, /New cutting factory/);
  assert.equal(ui.button("Save").disabled, true);
  await ui.submit();
  assert.equal(ui.writes.length, 0);
  ui.response({ production_order_id: 72, cutting_department_code: "ECT", available_departments: ["CUT", "ECT"], can_change: true, lock_reason: null });
  assert.match(ui.render(), /Eco Cotton/);
  ui.target("CUT"); await ui.submit();
  assert.equal(ui.writes[0].url, "/api/production-orders/72/cutting-factory");
});

for (const lang of ["en", "ru", "uz"]) {
  test(`${lang}: order-detail action targets its own order without an order picker`, async () => {
    const ui = harness({ lang, order: { id: 72, production_no: "PO-0072" } });
    const pending = ui.open();
    assert.match(pending, /PO-0072/);
    assert.doesNotMatch(pending, /data-order-select/);
    assert.equal(ui.reads.at(-1), "/api/production-orders/72/cutting-factory");
    // Cached options for a different order cannot enable this order's write.
    assert.equal(ui.button("Save").disabled, true);
    await ui.submit();
    assert.equal(ui.writes.length, 0);
    ui.response({ production_order_id: 72, cutting_department_code: "CUT", available_departments: ["CUT", "ECT"], can_change: true, lock_reason: null });
    ui.render(); ui.target("ECT"); await ui.submit();
    assert.deepEqual(ui.writes, [{ url: "/api/production-orders/72/cutting-factory", payload: { cutting_department_code: "ECT" } }]);
    assert.equal(ui.changed(), 1);
    assert.ok(ui.render().includes(ui.copy.saved));
  });
}

test("loading, revalidation and read errors disable writes even through direct invocation", async () => {
  for (const state of ["loading", "validating", "error"]) {
    const ui = harness(); ui.open(); ui.target("ECT");
    if (state === "loading") ui.pending(true);
    if (state === "validating") ui.validating(true);
    if (state === "error") ui.fail("403 outside factory scope");
    ui.render(); assert.equal(ui.button("Save").disabled, true);
    await ui.submit(); assert.equal(ui.writes.length, 0);
  }
});

test("server history refusal is localized and later successful retry sends only one further request", async () => {
  const ui = harness({ lang: "ru" }); ui.open(); ui.target("ECT");
  // The request was ready when clicked; mutate the API outcome without injecting a SWR read failure.
  const save = ui.button("Save").onClick;
  ui.fail("409 CUTTING_FACTORY_HISTORY_LOCKED");
  await save();
  const refused = ui.render();
  assert.ok(refused.includes(ui.copy.reasons.CUTTING_FACTORY_HISTORY_LOCKED));
  assert.equal(ui.writes.length, 1);
  ui.fail(null); ui.render(); await ui.submit();
  assert.equal(ui.writes.length, 2);
  assert.equal(ui.changed(), 1);
});

test("successful write with failed refresh stays saved, clears target and never resends automatically", async () => {
  const ui = harness(); ui.open(); ui.target("ECT"); ui.refreshFail("network failure");
  const html = await ui.submit();
  assert.ok(html.includes(ui.copy.saved));
  assert.ok(html.includes(ui.copy.refreshError));
  assert.equal(ui.writes.length, 1);
  assert.equal(ui.button("Save").disabled, true);
  await ui.submit(); assert.equal(ui.writes.length, 1);
});

test("blocked history and ungranted destinations cannot be submitted", async () => {
  for (const [reason, departments] of [["CUTTING_FACTORY_HISTORY_LOCKED", ["CUT", "ECT"]], ["CUTTING_FACTORY_DESTINATION_DENIED", ["CUT"]]]) {
    const ui = harness(); ui.open();
    ui.response({ production_order_id: 71, cutting_department_code: "CUT", available_departments: departments, can_change: false, lock_reason: reason });
    const html = ui.render();
    assert.ok(html.includes(ui.copy.reasons[reason]));
    assert.equal(ui.button("Save").disabled, true);
    await ui.submit(); assert.equal(ui.writes.length, 0);
  }
});
