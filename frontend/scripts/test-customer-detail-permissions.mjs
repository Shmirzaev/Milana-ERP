import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsx from "react/jsx-runtime";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const original = readFileSync(path.join(root, "src/app/(app)/customers/[id]/page.tsx"), "utf8");
const authSource = readFileSync(path.join(root, "src/lib/auth.ts"), "utf8");
function compile(source) {
  return ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
}
const authTree = ts.createSourceFile("auth.ts", authSource, ts.ScriptTarget.Latest, true);
const canDeclaration = authTree.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === "can");
assert.ok(canDeclaration, "Use the real permission predicate");
const authExports = {};
new Function("exports", compile(canDeclaration.getText(authTree)))(authExports);
const customer = { name: "Permission fixture", phone: "123", email: "qa@example.test", address: "Fixture street", notes: "Keep visible" };
const order = { id: 7, order_no: "SO-0007", status: "confirmed", total: 20, invoice_total: 0, paid_total: 0, balance_due: 20, payment_status: "no_invoice", invoices: [] };
const payment = { id: 8, row_key: "payment-8", amount: 25, payment_method: "bank_transfer", paid_at: "2026-10-26T00:00:00.000Z", is_advance: true };
const moduleDefault = value => ({ __esModule: true, default: value });
const event = { preventDefault() {} };

function harness(source, permissions, payments = []) {
  let me = permissions === undefined ? undefined : { permissions };
  let index = 0;
  let mounted = false;
  let actions;
  const state = [];
  const effects = [];
  const calls = [];
  const react = { ...React, useMemo: fn => fn(), useEffect: fn => { if (!mounted) effects.push(fn); },
    useState(initial) {
      const slot = index++;
      if (!(slot in state)) state[slot] = typeof initial === "function" ? initial() : initial;
      return [state[slot], value => { state[slot] = typeof value === "function" ? value(state[slot]) : value; }];
    } };
  function requireModule(name) {
    if (name === "react") return react;
    if (name === "react/jsx-runtime") return jsx;
    if (name === "@/lib/auth") return { can: authExports.can, useMe: () => ({ me }) };
    if (name === "next/navigation") return { useParams: () => ({ id: "2" }) };
    if (name === "next/link") return moduleDefault(({ children, ...props }) => React.createElement("a", props, children));
    if (name === "swr") return moduleDefault(key => ({ data: key.endsWith("/orders") ? [order] : key.endsWith("/payments") ? payments : customer, mutate() {} }));
    if (name === "@/lib/i18n") return { useT: () => ({ t: key => key }) };
    if (name === "@/lib/orderRef") return { formatOrderReference: (value, fallback = "") => value || fallback };
    if (name === "@/lib/numberInput") return { numberOrZero: Number, parseNumberInput: value => value === "" ? "" : Number(value) };
    if (name === "@/components/StagePipeline") return { statusLabel: value => value };
    if (name === "lucide-react") return { Plus: () => React.createElement("span") };
    if (name === "@/components/PageHeader") return moduleDefault(({ title, subtitle }) => React.createElement("header", null, title, subtitle));
    if (name === "@/components/Modal") return moduleDefault(({ open, children }) => open ? React.createElement("aside", null, children) : null);
    if (name === "@/lib/api") return { fetcher() {}, api: {
      async patch(url, payload) { calls.push({ method: "PATCH", url, payload }); },
      async post(url, payload) { calls.push({ method: "POST", url, payload }); return { ...payment, ...payload }; },
    } };
    throw Error(`Unmocked dependency ${name}`);
  }
  // Expose the actual handlers to challenge direct unauthorized invocation,
  // including a modal that had been open before permission loss.
  const marker = '  if (!customer) return <div>{t("common.loading")}</div>;';
  assert.ok(source.includes(marker));
  const instrumented = source.replace(marker, `  capture({ save, openPayment, recordPayment });\n${marker}`);
  const exports = {};
  new Function("exports", "require", "capture", compile(instrumented))(exports, requireModule, value => { actions = value; });
  function render() {
    index = 0;
    const tree = exports.default();
    if (!mounted) {
      mounted = true;
      for (const effect of effects) effect();
      return render();
    }
    return tree;
  }
  return { render, calls, actions: () => actions, setPermissions: permissions => { me = permissions === undefined ? undefined : { permissions }; } };
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (typeof tree.type === "function") return nodes(tree.type(tree.props));
  return [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (typeof tree === "string") return tree;
  if (Array.isArray(tree)) return tree.map(text).join("");
  return tree?.props ? text(tree.props.children) : "";
}
function buttons(tree, label) { return nodes(tree).filter(node => node.type === "button" && text(node) === label); }

async function assertRole(source, permissions, manage, pay, payments = []) {
  const app = harness(source, permissions, payments);
  let tree = app.render();
  const html = renderToStaticMarkup(tree);
  assert.ok(html.includes(customer.name) && html.includes(customer.notes), "Customer profile remains readable");
  assert.ok(html.includes(order.order_no), "Order history remains readable");
  assert.ok(html.includes("page.customerDetail.paymentHistory"), "Payment history remains readable");
  if (payments.length) assert.ok(html.includes("$25.00") && html.includes("page.customerDetail.advanceCredit"), "Advance credit remains readable");
  assert.equal(buttons(tree, "btn.save").length, manage ? 1 : 0, "Profile Save permission");
  const fields = nodes(tree).filter(node => ["input", "textarea"].includes(node.type));
  assert.equal(fields.length, 5, "All profile fields retained");
  for (const field of fields) assert.equal(Boolean(field.props.readOnly), !manage, "Profile edit permission");
  assert.equal(buttons(tree, "page.customerDetail.addPayment").length, pay ? (payments.length ? 2 : 3) : 0, "Every payment action permission");
  await app.actions().save(event);
  assert.equal(app.calls.filter(call => call.method === "PATCH").length, manage ? 1 : 0, "Profile handler permission");
  if (manage) assert.deepEqual(app.calls[0], { method: "PATCH", url: "/api/customers/2", payload: customer });
  app.actions().openPayment(order);
  tree = app.render();
  assert.equal(nodes(tree).filter(node => node.type === "aside").length, pay ? 1 : 0, "Payment form permission");
  await app.actions().recordPayment(event);
  assert.equal(app.calls.filter(call => call.method === "POST").length, pay ? 1 : 0, "Payment handler permission");
  if (pay) {
    const payload = app.calls.find(call => call.method === "POST").payload;
    assert.equal(payload.amount, 20);
    assert.equal(payload.sales_order_id, 7);
    assert.equal(payload.payment_method, "bank_transfer");
    assert.equal(payload.notes, null);
  }
}

for (const [name, permissions, manage, pay] of [
  ["loading", undefined, false, false], ["denied", [], false, false],
  ["Sales", ["sales.orders", "sales.customers"], true, false],
  ["Sales viewer", ["sales.orders"], false, false],
  ["Finance viewer", ["finance.view"], false, false],
  ["Finance payment", ["finance.view", "finance.payment"], false, true],
  ["combined", ["sales.customers", "finance.payment"], true, true],
  ["wildcard", ["*"], true, true],
]) for (const payments of [[], [payment]]) test(`${name}: ${payments.length ? "credit history" : "empty history"}`, () => assertRole(original, permissions, manage, pay, payments));

test("permission loss hides an open payment form and blocks its actual handler", async () => {
  const app = harness(original, ["finance.payment"]);
  app.render(); app.actions().openPayment(order);
  assert.equal(nodes(app.render()).filter(node => node.type === "aside").length, 1);
  app.setPermissions(["finance.view"]);
  assert.equal(nodes(app.render()).filter(node => node.type === "aside").length, 0);
  await app.actions().recordPayment(event);
  assert.deepEqual(app.calls, []);
});

test("authorized unallocated advance retains its payload", async () => {
  const app = harness(original, ["finance.payment"]);
  let tree = app.render();
  buttons(tree, "page.customerDetail.addPayment")[1].props.onClick();
  tree = app.render();
  nodes(tree).find(node => node.type === "input" && node.props.type === "number").props.onChange({ target: { value: "12.5" } });
  tree = app.render();
  await nodes(tree).filter(node => node.type === "form")[1].props.onSubmit(event);
  assert.equal(app.calls.length, 1);
  assert.equal(app.calls[0].payload.amount, 12.5);
  assert.ok(!("sales_order_id" in app.calls[0].payload));
});

test("authorized profile editing retains changed fields", async () => {
  const app = harness(original, ["sales.customers"]);
  let tree = app.render();
  nodes(tree).find(node => node.type === "input" && node.props.value === customer.name).props.onChange({ target: { value: "Updated fixture" } });
  tree = app.render();
  await nodes(tree).find(node => node.type === "form").props.onSubmit(event);
  assert.deepEqual(app.calls, [{ method: "PATCH", url: "/api/customers/2", payload: { ...customer, name: "Updated fixture" } }]);
});

for (const [name, before, after] of [
  ["payment visibility", '{canRecordPayment && <button', '{true && <button'],
  ["modal visibility", '{canRecordPayment && <Modal', '{true && <Modal'],
  ["profile Save", '{canManageCustomer && <div', '{true && <div'],
  ["profile readonly", 'readOnly={!canManageCustomer}', 'readOnly={false}'],
  ["profile handler", 'if (!canManageCustomer) return;', ''],
  ["payment handler", '    if (!canRecordPayment) return;\n    const targetOrder', '    const targetOrder'],
]) test(`reject regression: ${name}`, async () => {
  const source = original.replace(/\r\n/g, "\n");
  assert.ok(source.includes(before), "Mutation must match actual source");
  const mutated = source.replace(before, after);
  assert.notEqual(mutated, source);
  if (name === "modal visibility" || name === "payment handler") {
    const app = harness(mutated, ["finance.payment"]);
    app.render(); app.actions().openPayment(order); app.render();
    app.setPermissions([]);
    const tree = app.render();
    await app.actions().recordPayment(event);
    assert.ok(nodes(tree).some(node => node.type === "aside") || app.calls.length > 0, "The mutation must expose the original permission defect");
  } else {
    await assert.rejects(() => assertRole(mutated, [], false, false));
  }
});
