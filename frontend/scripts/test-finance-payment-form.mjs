import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

// Execute the actual page and its event handlers with deterministic SWR/API,
// dialog and hook adapters, following the existing script-render harness.
// This is component/interaction evidence, not connected-browser verification.
const read = path => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const pageSource = process.env.FINANCE_PAYMENT_PAGE
  ? fs.readFileSync(process.env.FINANCE_PAYMENT_PAGE, "utf8") : read("../src/app/(app)/finance/page.tsx");
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
const dictionaries = compile(read("../src/lib/i18n/dict.ts")).dict;
const messages = Object.fromEntries(["en", "ru", "uz"].map(lang => [lang,
  compile(read(`../src/lib/i18n/locales/${lang}-base.ts`)).default]));
const status = compile(read("../src/lib/invoiceStatus.ts"));
const numbers = compile(read("../src/lib/numberInput.ts"));

function harness({ lang = "en", balance = 175, missingBalance = false, statusValue = "partially_paid", source = pageSource } = {}) {
  const values = [];
  let cursor = 0;
  let nodes = [];
  let failure = null;
  let confirm = true;
  let inspectConfirmation = () => {};
  const posts = [], confirmations = [], mutations = [];
  const invoice = { id: 8, invoice_no: "INV-008", order_no: "SO-008", amount: 200,
    balance_due: missingBalance ? undefined : balance, status: statusValue };
  const t = (key, vars = {}) => Object.entries(vars).reduce(
    (text, [key, value]) => text.replaceAll(`{${key}}`, String(value)), messages[lang][key] ?? key);
  const deps = {
    react: { ...React, useMemo: fn => fn(), useState(initial) {
      const index = cursor++;
      if (!(index in values)) values[index] = typeof initial === "function" ? initial() : initial;
      return [values[index], next => { values[index] = typeof next === "function" ? next(values[index]) : next; }];
    } },
    "react/jsx-runtime": Object.fromEntries(Object.entries(jsxRuntime).map(([key, value]) => [key,
      ["jsx", "jsxs"].includes(key) ? (tag, props, ...rest) => {
        if (typeof tag === "string") nodes.push({ tag, props });
        return value(tag, props, ...rest);
      } : value])),
    swr: { default: key => ({ data: key.includes("/invoices?")
      ? { items: [invoice], total: 1, limit: 50, offset: 0 }
      : key.includes("revenue-by-period") ? [] : {}, mutate: async () => mutations.push(key) }) },
    "@/lib/api": { fetcher() {}, api: { post: async (url, payload) => {
      posts.push({ url, payload }); if (failure) throw new Error(failure); return {};
    } } },
    "@/lib/orderRef": { formatOrderReference: value => value ?? "-" },
    "@/lib/i18n": { useT: () => ({ t }) },
    "@/lib/invoiceStatus": status,
    "@/lib/numberInput": numbers,
    "@/components/PageHeader": { default: () => null },
    "@/components/Modal": { default: ({ open, children }) => open ? React.createElement("section", null, children) : null },
    "@/components/StagePipeline": { statusLabel: value => value },
    "@/components/DialogProvider": { useDialogs: () => ({ ask: async options => {
      confirmations.push(options); inspectConfirmation(); return confirm;
    } }) },
  };
  const Page = compile(source, deps).default;
  function render() { cursor = 0; nodes = []; return renderToStaticMarkup(Page()); }
  function field(kind) {
    return nodes.find(node => kind === "method" ? node.tag === "select" : node.tag === "input" && node.props.type === kind)?.props;
  }
  function open() {
    render(); nodes.find(node => node.tag === "button" && node.props.children === t("page.finance.recordPayment")).props.onClick();
    return render();
  }
  function change(kind, value) { field(kind).onChange({ target: { value } }); return render(); }
  async function submit() { await nodes.find(node => node.tag === "form").props.onSubmit({ preventDefault() {} }); return render(); }
  return { render, open, change, submit, field, posts, confirmations, mutations, t,
    fail: message => { failure = message; }, confirm: value => { confirm = value; },
    onConfirm: fn => { inspectConfirmation = fn; } };
}

for (const [balance, expected] of [[200, 200], [175, 175], [0, 0], [0.01, 0.01], [undefined, ""]]) {
  test(`opening uses remaining due ${String(balance)} without inventing a balance`, () => {
    // Explicitly missing fields simulate a rolling old-server response.
    const ui = harness({ balance, missingBalance: balance === undefined });
    ui.open(); assert.equal(ui.field("number").value, expected);
  });
}

for (const lang of ["en", "ru", "uz"]) {
  test(`${lang}: partial/full/overpayment confirmations describe the exact submitted amount`, async () => {
    assert.equal(messages[lang]["page.finance.recordPaymentConfirm"], dictionaries[lang]["page.finance.recordPaymentConfirm"]);
    for (const amount of [25, 175, 200]) {
      const ui = harness({ lang });
      ui.open(); ui.change("number", String(amount)); await ui.submit();
      assert.equal(ui.confirmations[0].message,
        ui.t("page.finance.recordPaymentConfirm", { invoice: "INV-008", amount: `$${amount.toFixed(2)}` }));
      assert.ok(ui.confirmations[0].message.includes(`$${amount.toFixed(2)}`));
      assert.doesNotMatch(ui.confirmations[0].message, /mark .* as paid|как оплаченный|to'langan deb/);
      assert.equal(ui.posts.length, 1);
      assert.equal(ui.posts[0].url, "/api/finance/payments");
      assert.equal(ui.posts[0].payload.amount, amount);
      assert.equal(ui.posts[0].payload.invoice_id, 8);
      assert.equal(ui.posts[0].payload.payment_method, "bank_transfer");
      assert.deepEqual(ui.mutations.map(key => key.split("?")[0]), ["/api/finance/invoices", "/api/finance/dashboard"]);
    }
  });
}

for (const [kind, value] of [["number", "25"], ["date", "2026-10-27"], ["method", "cash"]]) {
  test(`changing ${kind} clears the previous API validation message`, async () => {
    const ui = harness(); ui.open(); ui.fail("422 amount must be positive");
    assert.match(await ui.submit(), /422 amount must be positive/);
    assert.doesNotMatch(ui.change(kind, value), /422 amount must be positive/);
    ui.fail(null); await ui.submit();
    assert.equal(ui.posts.length, 2);
    assert.equal(ui.posts[1].payload[kind === "number" ? "amount" : kind === "date" ? "paid_at" : "payment_method"],
      kind === "number" ? 25 : kind === "date" ? "2026-10-27T00:00:00.000Z" : "cash");
  });
}

test("retry clears stale validation before opening confirmation, including cancellation", async () => {
  const ui = harness(); ui.open(); ui.fail("old 422");
  assert.match(await ui.submit(), /old 422/);
  ui.confirm(false); ui.onConfirm(() => assert.doesNotMatch(ui.render(), /old 422/));
  assert.doesNotMatch(await ui.submit(), /old 422/);
  assert.equal(ui.posts.length, 1);
});

test("paid action visibility and backend validation remain unchanged", async () => {
  const paid = harness({ statusValue: "paid" });
  assert.ok(!paid.render().includes(paid.t("page.finance.recordPayment")));
  const ui = harness(); ui.open(); ui.change("number", "0"); ui.fail("amount must be positive");
  assert.match(await ui.submit(), /amount must be positive/);
  assert.equal(ui.posts[0].payload.amount, 0);
});
