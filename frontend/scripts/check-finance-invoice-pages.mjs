import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/finance/page.tsx", import.meta.url), "utf8");
assert.doesNotMatch(source, /\/api\/finance\/invoices\?limit=50/);
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

const state = [];
let cursor = 0;
let pageCount = 1;
let invoiceKeys = [];
const payments = [];
const hooks = {
  ...React,
  useMemo(factory) { return factory(); },
  useState(initial) {
    const slot = cursor++;
    if (!(slot in state)) state[slot] = typeof initial === "function" ? initial() : initial;
    return [state[slot], next => { state[slot] = typeof next === "function" ? next(state[slot]) : next; }];
  },
};
const Modal = () => null;
const exports = {};
new Function("exports", "require", output)(exports, name => ({
  react: hooks,
  "react/jsx-runtime": jsxRuntime,
  swr: { default: () => ({ data: undefined, mutate: async () => {} }) },
  "swr/infinite": { default: getKey => {
    const pages = [];
    invoiceKeys = [];
    for (let page = 0; page < pageCount; page++) {
      const key = getKey(page, pages.at(-1) || null);
      invoiceKeys.push(key);
      if (!key) break;
      const rows = Array.from({ length: page === 10 ? 1 : 50 }, (_, row) => {
        const id = page * 50 + row + 1;
        return { id, invoice_no: `INV-${id}`, order_no: `SO-${id}`, customer: `Customer ${id}`, amount: 100, currency: "USD", status: "open", date: "2026-09-25" };
      });
      pages.push({ rows, total: 501, has_more: page < 10, page: page + 1, page_size: 50 });
    }
    return { data: pages, size: pageCount, setSize: next => { pageCount = next; }, mutate: async () => {}, isValidating: false };
  } },
  "@/lib/orderRef": { formatOrderReference: value => value },
  "@/lib/api": { api: { post: async (_path, payload) => { payments.push(payload); return {}; } }, fetcher() {} },
  "@/components/PageHeader": { default: () => null },
  "@/components/Modal": { default: Modal },
  "@/lib/i18n": { useT: () => ({ t: key => key }) },
  "@/components/StagePipeline": { statusLabel: value => value },
  "@/components/DialogProvider": { useDialogs: () => ({ ask: async () => true }) },
  "@/lib/numberInput": { numberOrZero: value => Number(value) || 0, parseNumberInput: value => value },
})[name]);

function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (Array.isArray(node)) {
    for (const child of node) {
      const match = find(child, predicate);
      if (match) return match;
    }
    return null;
  }
  if (predicate(node)) return node;
  for (const child of Array.isArray(node.props?.children) ? node.props.children : [node.props?.children]) {
    const match = find(child, predicate);
    if (match) return match;
  }
  return null;
}
function render() {
  cursor = 0;
  return exports.default();
}
function loadMore(tree) {
  return find(tree, node => node.type === "button" && String(node.props?.children).includes("common.loadMore"));
}

let tree = render();
assert.equal(invoiceKeys[0], "/api/finance/invoices?page=1&page_size=50");
assert.ok(loadMore(tree), "the first 50 invoices must expose Load more");
for (let page = 2; page <= 11; page++) {
  loadMore(tree)?.props.onClick();
  tree = render();
  assert.equal(invoiceKeys[page - 1], `/api/finance/invoices?page=${page}&page_size=50`);
}
assert.equal(loadMore(tree), null, "all 501 invoices must end pagination");
const lastRow = find(tree, node => node.type === "tr" && node.key === "501");
assert.ok(lastRow, "invoice 501 must be visible after paging");
const paymentButton = find(lastRow, node => node.type === "button" && node.props?.children === "page.finance.recordPayment");
assert.ok(paymentButton);
paymentButton.props.onClick();
tree = render();
const modal = find(tree, node => node.type === Modal && node.props.open);
assert.ok(modal, "the payment modal must retain the selected off-page invoice");
const form = find(modal, node => node.type === "form" && typeof node.props?.onSubmit === "function");
await form.props.onSubmit({ preventDefault() {} });
assert.equal(payments.at(-1)?.invoice_id, 501, "payment must target the off-page invoice");
console.log("Finance invoice pages reach row 501 and preserve its payment action.");
