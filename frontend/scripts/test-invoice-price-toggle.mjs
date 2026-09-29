import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

function load(file, modules = {}) {
  const source = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  vm.runInNewContext(source, { exports, require: name => {
    assert.ok(name in modules, `Unexpected dependency ${name}`);
    return modules[name];
  }});
  return exports;
}
const translations = load('src/lib/shipmentReviewText.ts');
for (const lang of ['en', 'ru', 'uz']) {
  let visible = true;
  const element = (type, props) => ({ type, props });
  const Component = load('src/components/ShipmentInvoiceActions.tsx', {
    react: { useState: () => [visible, update => { visible = update(visible); }] },
    'react/jsx-runtime': { jsx: element, jsxs: element, Fragment: 'fragment' },
    '@/lib/i18n': { useT: () => ({ lang }) },
    '@/lib/shipmentReviewText': translations,
    '@/lib/shipmentDisplay': { shipmentDisplayText: { [lang]: { excel: 'Excel' } } },
  }).default;
  for (const expected of [true, false, true]) {
    const [toggle, print, excel] = Component({ shipmentId: 42 }).props.children;
    assert.equal(toggle.type, 'button');
    assert.equal(toggle.props.type, 'button');
    assert.equal(toggle.props.children, translations.shipmentReviewText[lang][expected ? 'hidePrices' : 'showPrices']);
    assert.equal(print.props.href, `/api/shipments/42/invoice/print?lang=${lang}&show_prices=${expected}`);
    assert.equal(excel.props.href, `/api/shipments/42/invoice.xlsx?lang=${lang}&show_prices=${expected}`);
    toggle.props.onClick();
  }
}
console.log('Invoice toggle preserves language and controls both exports.');
