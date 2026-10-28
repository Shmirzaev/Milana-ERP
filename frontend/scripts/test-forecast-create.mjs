import assert from 'node:assert/strict';
import fs from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

const read = path => fs.readFileSync(new URL(path, import.meta.url), 'utf8');
function compile(source, deps={}) {
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports={};
  new Function('exports','require',code)(exports,name=>{assert.ok(name in deps,`Unexpected dependency ${name}`);return deps[name];});
  return exports;
}
const contracts=compile(read('../src/lib/forecastRecommendationContracts.ts'));
const source=read('../src/app/(app)/forecasting/page.tsx');
const suggestion={recommendation_type:contracts.ForecastRecommendationType.BRANDED_STOCK_PRODUCTION,model_id:8,model_code:'FC-8',model_name:'Forecast garment',color:'white',size:'M',suggested_quantity:12.34567,unit:'kg',confidence:'manual-other',source_extra:{nested:[1,true]}};
const element=(type,props)=>({type,props:props??{}});
function walk(node,out=[]) {
  if(Array.isArray(node)){for(const child of node)walk(child,out);return out;}
  if(node && typeof node==='object'){out.push(node);walk(node.props?.children,out);}
  return out;
}
function render({manage=true,post=async()=>({}),rows=[suggestion]}={}) {
  const calls=[],messages=[];let mutations=0;
  const page=compile(source,{
    react:{useState:value=>[value,next=>{if(typeof next==='string')messages.push(next);}],useRef:()=>({current:false})},
    'react/jsx-runtime':{jsx:element,jsxs:element,Fragment:'fragment'},
    'next/link':{default:'a'},
    swr:{default:path=>path.endsWith('/dashboard')?{data:{branded_stock_suggestions:rows,item_reorder_suggestions:[{recommendation_type:'item_reorder',item_id:1,suggested_quantity:4}],demand_trend:[],cards:{},unlinked_bom_count:0},mutate:async()=>{}}:{data:[],mutate:async()=>{mutations++;}}},
    '@/lib/forecastRecommendationContracts':contracts,
    '@/lib/variantDisplay':{formatModelVariantCode:x=>x},
    '@/lib/api':{api:{post:async(path,body)=>{calls.push({path,body});return post(path,body);}},fetcher(){}},
    '@/lib/auth':{useMe:()=>({me:{}}),can:(_me,permission)=>permission==='forecasting.manage'&&manage},
    '@/lib/i18n':{useT:()=>({lang:'en',t:key=>key})},
    '@/components/StagePipeline':{statusLabel:x=>x},
    '@/components/PageHeader':{default:'header'},
    '@/components/ForecastLineChart':{default:'chart'},
    'lucide-react':Object.fromEntries(['Check','ClipboardList','PackagePlus','RotateCcw','ShoppingBag','X'].map(k=>[k,'icon'])),
  }).default;
  const nodes=walk(page());
  const saves=nodes.filter(n=>n.type==='button'&&n.props.children==='page.forecasting.saveRecommendation');
  return {calls,messages,saves,get mutations(){return mutations;}};
}

test('actual save handler preserves fractional quantity and complete metadata then reloads list',async()=>{
  const ui=render();assert.equal(ui.saves.length,1);await ui.saves[0].props.onClick();
  assert.equal(ui.calls.length,1);assert.equal(ui.calls[0].path,'/api/forecasting/recommendations');
  assert.deepEqual(ui.calls[0].body,{recommendation_type:'branded_stock_production',model_id:8,item_id:null,brand_id:null,collection_id:null,color:'white',size:'M',suggested_quantity:12.34567,unit:'kg',confidence:'manual-other',reason:null,source_json:suggestion});
  assert.equal(ui.mutations,1);assert.ok(ui.messages.includes('page.forecasting.saved'));
});
test('permission hides save and model-less reorders remain excluded',()=>{
  assert.equal(render({manage:false}).saves.length,0);
  assert.equal(render({rows:[]}).saves.length,0);
});
test('in-flight double click sends once and subsequent explicit save remains allowed',async()=>{
  let finish;const pending=new Promise(resolve=>{finish=resolve;});
  const ui=render({post:()=>pending});
  const first=ui.saves[0].props.onClick();await ui.saves[0].props.onClick();assert.equal(ui.calls.length,1);
  finish({});await first;await ui.saves[0].props.onClick();assert.equal(ui.calls.length,2);
});
test('failed save reports error, does not reload, and releases action lock for retry',async()=>{
  let failing=true;const ui=render({post:async()=>{if(failing)throw new Error('Factory refused');return {};}});
  await ui.saves[0].props.onClick();assert.equal(ui.mutations,0);assert.ok(ui.messages.includes('Factory refused'));
  failing=false;await ui.saves[0].props.onClick();assert.equal(ui.calls.length,2);assert.equal(ui.mutations,1);
});
test('legacy empty-field normalization remains unchanged without discarding source object',()=>{
  const row={recommendation_type:contracts.ForecastRecommendationType.ITEM_REORDER,suggested_quantity:0,model_id:0,color:'',size:'',unit:'',confidence:'',reason:'',custom:['keep']};
  const input=contracts.forecastRecommendationInput(row);
  assert.equal(input.model_id,null);assert.equal(input.suggested_quantity,0);assert.equal(input.unit,'pcs');
  assert.equal(input.confidence,null);assert.equal(input.source_json,row);assert.deepEqual(input.source_json.custom,['keep']);
});
