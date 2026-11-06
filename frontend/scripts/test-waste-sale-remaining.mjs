import assert from 'node:assert/strict';
import fs from 'node:fs';
import { test } from 'node:test';
import React from 'react';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';

const source = fs.readFileSync(process.env.WASTE_PAGE_SOURCE || new URL('../src/app/(app)/waste/page.tsx', import.meta.url), 'utf8');
function render(remaining, failure) {
  const posted = [], messages = [];
  let refreshes = 0;
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  const deps = {
    react: { ...React, useState: value => [value, next => messages.push(next)] },
    'react/jsx-runtime': jsx,
    swr: { default: key => ({ data: key === '/api/waste' ? [{ id: 7, quantity: 10,
      remaining_quantity: remaining, unit: 'kg', status: 'received_by_waste_department', sellable: true,
      estimated_value: 1, waste_type: 'fabric' }] : [], mutate: () => { refreshes += 1; } }) },
    '@/lib/api': { fetcher() {}, api: { post: async (...args) => { posted.push(args); if (failure) throw new Error(failure); } } },
    '@/components/PageHeader': { default: () => null },
    '@/components/StagePipeline': { statusLabel: value => value },
    '@/lib/i18n': { useT: () => ({ t: key => key }) },
    '@/components/DialogProvider': { useDialogs: () => ({ ask: async () => true }) },
    '@/lib/numberInput': { numberOrZero: Number, parseNumberInput: value => value },
  };
  new Function('exports', 'require', code)(exports, name => {
    assert.ok(name in deps, `Unexpected dependency ${name}`); return deps[name];
  });
  const nodes = [];
  function visit(node) {
    if (Array.isArray(node)) { node.forEach(visit); return; }
    if (node && typeof node === 'object' && node.props) { nodes.push(node); visit(node.props.children); }
  }
  visit(exports.default());
  const sell = nodes.find(node => node.type === 'button' && node.props.children === 'page.waste.sellPrice');
  return { posted, messages, sell, refreshes: () => refreshes };
}
for (const remaining of [10, 6]) test(`actual sale button submits remaining ${remaining}`, async () => {
  const ui = render(remaining); assert.ok(ui.sell);
  await ui.sell.props.onClick();
  assert.deepEqual(ui.posted, [['/api/waste/7/sell', { buyer_name: 'Buyer', quantity: remaining, unit_price: 0.1 }]]);
  assert.equal(ui.refreshes(), 1);
});
for (const remaining of [null, 0, -1]) test(`unknown or unavailable remainder ${remaining} cannot be sold`, () => {
  const ui = render(remaining); assert.equal(ui.sell, undefined); assert.deepEqual(ui.posted, []);
});
test('stale sale refusal is shown without claiming a successful refresh', async () => {
  const ui = render(6, 'Sale quantity exceeds remaining waste quantity 4.0000');
  await ui.sell.props.onClick();
  assert.ok(ui.messages.includes('Sale quantity exceeds remaining waste quantity 4.0000'));
  assert.equal(ui.refreshes(), 0);
});
