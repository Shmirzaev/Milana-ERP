// Source-extracted behavioral characterization only; no browser, HTTP or DB.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';

assert.equal(process.argv.length,3,'supply exactly one explicit source root');
assert.ok(path.isAbsolute(process.argv[2]),'source root must be absolute');
const ROOT=fs.realpathSync(process.argv[2]);
console.log(`SOURCE_ROOT ${ROOT}`);
const read=p=>fs.readFileSync(path.join(ROOT,p),'utf8');
const sha=s=>crypto.createHash('sha256').update(s).digest('hex');
const sources={
  planning:read('frontend/src/app/(app)/planning/page.tsx'),
  detail:read('frontend/src/app/(app)/sales-orders/[id]/page.tsx'),
  api:read('frontend/src/lib/api.ts'),
  stage:read('frontend/src/components/StagePipeline.tsx'),
  enums:read('frontend/src/lib/salesOrderEnums.ts'),
  output:read('backend/app/libs/dto/sales/sales_order_output.py'),
  salesRoute:read('backend/app/api/routes/sales.py'),
  ordersService:read('backend/app/models/sales/orders_service.py'),
  contracts:read('frontend/src/lib/salesOrderContracts.ts'),
};
const required=(value,label)=>{assert.ok(value,label);return value};
const enumBody=required(sources.enums.match(/export enum SalesOrderStatus\s*\{([\s\S]*?)\n\}/),'enum')[1];
const values=Object.fromEntries([...enumBody.matchAll(/\b([A-Z_]+)\s*=\s*"([^"]+)"/g)].map(m=>[m[1],m[2]]));
assert.equal(Object.keys(values).length,19);
assert.deepEqual([values.CONFIRMED,values.PENDING_SALES_APPROVAL,values.PLANNING_APPROVED],['confirmed','pending_sales_approval','planning_approved']);

const extractedExpression=required(sources.planning.match(/const planningOrders\s*(?::\s*[^=;]+)?\s*=\s*([^;]+);/),'actual Planning filter')[1];
// Strip only an optional callback type annotation, not filter/business logic.
const expression=extractedExpression.replace(/\(o:\s*SalesOrderListRow\)/g,'(o)');
const filter=orders=>vm.runInNewContext(expression,{orders,SalesOrderStatus:values});
const rows=[...Object.values(values).map((status,id)=>({id,status})),{id:50,status:'CONFIRMED'},{id:51,status:' confirmed '},{id:52,status:null},{id:53},{id:54,status:'unknown'}];
assert.deepEqual(Array.from(filter(rows),r=>r.status),['pending_sales_approval','confirmed','planning_approved']);
assert.equal(filter(null).length,0);
assert.equal(filter([{status:'confirmed'}, {status:'CONFIRMED'}, {status:'confirmed '}]).length,1);
const altered=expression.includes('SalesOrderStatus.CONFIRMED')
  ? expression.replace('SalesOrderStatus.CONFIRMED','"__deliberate_fault__"')
  : expression.replace('"confirmed"','"__deliberate_fault__"');
assert.notEqual(altered,expression,'negative control target must exist');
assert.equal(vm.runInNewContext(altered,{orders:[{status:'confirmed'}],SalesOrderStatus:values}).length,0); // in-memory only
assert.throws(()=>assert.deepEqual(Array.from(vm.runInNewContext(altered,{orders:rows,SalesOrderStatus:values}),r=>r.status),
  ['pending_sales_approval','confirmed','planning_approved']),assert.AssertionError,'deliberate mutation must fail unchanged status vector');
const fetchUrl=required(sources.planning.match(/useSWR<[^>\n]+>\("([^"\n]*\/api\/sales-orders[^"\n]*)", fetcher\)/),'actual Sales list SWR URL')[1];
assert.equal(fetchUrl,'/api/sales-orders?order_type=client_order&page_size=200');
assert.equal(new URL(fetchUrl,'http://localhost').searchParams.has('page'),false);
assert.match(sources.salesRoute,/def list_sales_orders\([\s\S]*?page:\s*int\s*=\s*1,\s*page_size:\s*int\s*=\s*50/);
const listBody=required(sources.ordersService.match(/def list_sales_orders\([\s\S]*?\n(?=def )/),'actual Sales list service')[0];
assert.match(listBody,/safe_page = max\(1, page\)/);assert.match(listBody,/safe_size = max\(1, min\(page_size, 500\)\)/);
assert.match(listBody,/order_by\(SalesOrder\.id\.desc\(\)\)\.offset\(\(safe_page - 1\) \* safe_size\)\.limit\(safe_size\)/);
assert.equal((sources.planning.match(/\/api\/sales-orders\?order_type=client_order&page_size=200/g)||[]).length,1);

const table=required(sources.planning.match(/\{planningOrders\.map\(\(o\) => \(([\s\S]*?)\n\s*\)\)\}/),'Planning sales table')[1];
const orderExpr=required(table.match(/<td>\{(formatOrderReference\(o\.order_no\))\}<\/td>/),'order field')[1];
const customerExpr=required(table.match(/<td>\{(o\.customer\?\.name \|\| o\.customer_name \|\| o\.customer_id \|\| "-")\}<\/td>/),'customer fields')[1];
const totalExpr=required(table.match(/<td>\$\{(Number\(o\.total_amount\)\.toFixed\(2\))\}<\/td>/),'total field')[1];
const statusExpr=required(table.match(/<td>\{(statusLabel\(o\.status, t\))\}<\/td>/),'status field')[1];
assert.match(table,/key=\{o\.id\}/);assert.match(table,/busyOrderId === o\.id/);
assert.match(table,/openMaterialEstimateForSO\(o\)/);assert.match(table,/openBatchPlannerForSO\(o\.id\)/);
const evaluate=(expr,o)=>vm.runInNewContext(expr,{o,formatOrderReference:x=>`order:${x}`,statusLabel:x=>`status:${x}`,t:()=>null,Number});
assert.equal(evaluate(orderExpr,{order_no:'SO-42'}),'order:SO-42');
for(const [row,want] of [[{customer:{name:'Nested'},customer_name:'Flat',customer_id:9},'Nested'],[{customer:null,customer_name:'Flat',customer_id:9},'Flat'],[{customer_name:'',customer_id:9},9],[{customer:null,customer_name:null,customer_id:null},'-']]) assert.equal(evaluate(customerExpr,row),want);
assert.equal(evaluate(totalExpr,{total_amount:'12.3'}),'12.30');assert.equal(evaluate(totalExpr,{total_amount:null}),'0.00');assert.equal(evaluate(statusExpr,{status:'CONFIRMED'}),'status:CONFIRMED');

const extractedHandler=required(sources.detail.match(/async function confirmOrder\(\) \{([\s\S]*?)\n  \}/),'actual confirm handler')[0];
// Erase only an optional TypeScript generic on the same api.post call.
const handler=extractedHandler.replace(/api\.post<[A-Za-z_$][\w$]*>/g,'api.post');
const calls=[];let mutateCount=0;
const success=vm.runInNewContext(`(${handler})`,{id:42,api:{post:async (...args)=>{calls.push(args)}},mutate:()=>{mutateCount++;return Promise.resolve()}});
await success();assert.equal(JSON.stringify(calls),JSON.stringify([['/api/sales-orders/42/confirm']]));assert.equal(mutateCount,1);
let failures=0;const failed=vm.runInNewContext(`(${handler})`,{id:42,api:{post:async()=>{failures++;throw Error('synthetic')}},mutate:()=>assert.fail('mutate after failure')});
await assert.rejects(failed,/synthetic/);assert.equal(failures,1);
assert.match(sources.detail,/so\.status === SalesOrderStatus\.DRAFT\s*&&\s*<button[^>]+onClick=\{confirmOrder\}/);
const apiPost=required(sources.api.match(/post:\s*<T = any>\(p: string, body\?: any, timeoutMs\?: number\) =>\s*(request<T>\([^\n]+\))/),'actual api.post')[1].replace('request<T>','request');
let requestCalls=[];const post=vm.runInNewContext(`((p,body,timeoutMs)=>${apiPost})`,{request:(...args)=>{requestCalls.push(args);return 'done'},JSON});
assert.equal(post('/api/sales-orders/42/confirm'),'done');assert.equal(requestCalls.length,1);assert.equal(requestCalls[0][1].method,'POST');assert.equal(requestCalls[0][1].body,undefined);
requestCalls=[];post('/x',{a:1});assert.equal(requestCalls[0][1].body,'{"a":1}');
const requestBody=required(sources.api.match(/async function request<T = any>\([\s\S]*?\n\}/),'request function')[0];
assert.equal((requestBody.match(/fetchWithTimeout\(/g)||[]).length,1);assert.doesNotMatch(requestBody,/\b(for|while)\s*\(/);
const timeoutBody=required(sources.api.match(/async function fetchWithTimeout<T>\([\s\S]*?\n\}/),'fetchWithTimeout function')[0];
assert.equal((timeoutBody.match(/await fetch\(/g)||[]).length,1);assert.doesNotMatch(timeoutBody,/\b(for|while)\s*\(/);

const fallback=required(sources.stage.match(/function fallbackLabel\(v: string\) \{[\s\S]*?\n\}/),'fallback')[0].replace('(v: string)','(v)');
const label=required(sources.stage.match(/export function statusLabel\(status: string, t: CtxT\) \{[\s\S]*?\n\}/),'status label')[0].replace('export function','function').replace('(status: string, t: CtxT)','(status, t)').replace(' as Record<string, string>','');
const statusLabel=vm.runInNewContext(`(()=>{${fallback}\n${label}\nreturn statusLabel})()`);
const t=key=>key==='statusValue.confirmed'?'translated-confirmed':key;
assert.equal(statusLabel('CONFIRMED',t),'translated-confirmed');assert.equal(statusLabel(' confirmed ',t),' confirmed ');assert.equal(statusLabel('odd_status',t),'odd status');assert.equal(statusLabel(null,t),'');

assert.match(sources.output,/class SalesOrderOut\(ORMModel\):[\s\S]*?customer_name:\s*Optional\[str\]/);
assert.match(sources.output,/class SalesOrderDetail\(SalesOrderOut\):\s*\n\s*items:\s*list\[SalesOrderItemOut\]/);
for(const name of ['model_id','color','size','quantity','printing_required']) assert.ok(sources.planning.includes(`i.${name}`),`detail line consumer ${name}`);
assert.ok(sources.planning.includes('row.model_id'));assert.ok(sources.planning.includes('firstItem?.brand_id'));assert.ok(sources.planning.includes('so.deadline'));assert.ok(sources.planning.includes('so.order_no'));
for(const lang of ['en','ru','uz']){
  const locale=read(`frontend/src/lib/i18n/locales/${lang}-base.ts`);
  for(const key of ['btn.confirm','page.planning.confirmedAwaiting','statusValue.confirmed','statusValue.pending_sales_approval','statusValue.planning_approved']) assert.ok(locale.includes(`"${key}"`),`${lang} locale anchor ${key}`);
}
for(const [name,src] of Object.entries(sources)) console.log(`SOURCE ${name} ${sha(src)}`);
console.log('PASS source-extracted filter, row projections, bodyless caller, direct POST/no-retry structure, display normalization, locale anchors; NOT browser/HTTP/PG');
