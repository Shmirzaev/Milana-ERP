import assert from 'node:assert/strict';
import fs from 'node:fs';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as jsx from 'react/jsx-runtime';
import ts from 'typescript';

const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
function compile(source, deps = {}) {
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  new Function('exports', 'require', code)(exports, name => {
    assert.ok(name in deps, `Unexpected dependency ${name}`); return deps[name];
  });
  return exports;
}
const enums = compile(read('../src/lib/salesOrderEnums.ts'));
const source = process.env.SALES_LIST_PAGE ? fs.readFileSync(process.env.SALES_LIST_PAGE,'utf8') : read('../src/app/(app)/sales-orders/page.tsx');
const records = [
  { id: 5, order_no:'SO-0005', customer_id:1, order_type:'client_order', status:'draft', total_amount:60, total_quantity:6 },
  { id: 4, order_no:'SO-0004', customer_id:1, order_type:'client_order', status:'confirmed', total_amount:20, total_quantity:2 },
];
function render(rows, lang='en') {
  const text=compile(read(`../src/lib/i18n/locales/${lang}-base.ts`)).default;
  const t=(key)=>text[key]??key;
  const Page=compile(source,{
    react:{...React,useState:x=>[x,()=>{}],useMemo:f=>f(),useEffect:()=>{}},
    'react/jsx-runtime':jsx,
    'next/navigation':{useSearchParams:()=>new URLSearchParams()},
    swr:{default:()=>({data:[{id:1,name:'Synthetic customer'}]})},
    '@/lib/useLoadMore':{default:()=>({data:{rows,total:rows.length},isLoading:false,mutate(){}})},
    '@/lib/salesOrderEnums':enums,'@/lib/orderRef':{formatOrderReference:x=>x},
    '@/lib/api':{api:{},fetcher(){}}, '@/lib/i18n':{useT:()=>({t})},
    '@/components/StagePipeline':{statusLabel:x=>x},
    '@/components/DialogProvider':{useDialogs:()=>({})},
    '@/components/PageHeader':{default:()=>null},'@/components/PaginationControls':{default:()=>null},
    'lucide-react':Object.fromEntries(['Download','Filter','MoreHorizontal','Plus','Search','X'].map(k=>[k,()=>null])),
  }).default;
  const html=renderToStaticMarkup(Page());
  return {html,t,articles:[...html.matchAll(/<article\b[^>]*>([\s\S]*?)<\/article>/g)].map(m=>m[1]),
    rows:[...html.matchAll(/<tbody>([\s\S]*?)<\/tbody>/g)][0][1].match(/<tr\b[^>]*>[\s\S]*?<\/tr>/g)??[]};
}
for(const reverse of [false,true]) test(`actual piece counts survive row reorder=${reverse} in desktop and mobile`,()=>{
  const input=reverse?[...records].reverse():records;
  const ui=render(input);
  for(const group of [ui.articles,ui.rows]) input.forEach((record,i)=>{
    assert.match(group[i],new RegExp(record.order_no));
    assert.match(group[i],new RegExp(`class="mono (?:font-semibold|text-right)">${record.total_quantity}<`));
    assert.doesNotMatch(group[i],/4,800|9,600|62%|47%|mini-bar/);
  });
});
test('zero and empty-line quantities stay zero, never fallback examples',()=>{
  const ui=render([{...records[0],total_quantity:0}]);
  for(const group of [ui.articles,ui.rows]) assert.match(group[0],/class="mono (?:font-semibold|text-right)">0</);
});
test('missing old-server quantity is unknown rather than a fabricated zero',()=>{
  const {total_quantity,...old}=records[0]; const ui=render([old]);
  for(const group of [ui.articles,ui.rows]) assert.match(group[0],/class="mono (?:font-semibold|text-right)">—</);
});
for(const lang of ['en','ru','uz']) test(`${lang} progress unavailable is translated in both layouts without a numeric percentage`,()=>{
  const ui=render(records,lang);const label=ui.t('sales.progressUnavailable');
  assert.notEqual(label,'sales.progressUnavailable');
  for(const group of [ui.articles,ui.rows]) for(const row of group){assert.ok(row.includes(label));assert.doesNotMatch(row,/\d+%|mini-bar/);}
});
