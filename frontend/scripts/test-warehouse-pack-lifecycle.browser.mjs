import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium } from 'playwright';
const root=process.cwd();
const stubs={
 '@/lib/auth':`export const useMe=()=>({me:{}}); export const can=()=>window.allowed!==false;`,
 '@/lib/i18n':`export const useT=()=>({lang:window.lang||'en',t:key=>key});`,
 '@/components/DialogProvider':`export const useDialogs=()=>({ask:async()=>window.confirmAction!==false});`,
 '@/components/Modal':`export default function Modal({open,children,title}) {return open?<div role="dialog"><h2>{title}</h2>{children}</div>:null;}`,
 '@/lib/api':`export const api={post:async(path,body)=>{window.calls.push({method:'POST',path,body});if(window.fail)throw Error('Package is reserved');return{};},del:async(path)=>{window.calls.push({method:'DELETE',path});if(window.fail)throw Error('Package is reserved');return{};}};export const fetcher=async()=>({rows:[{id:12,production_no:'PO-TEST',package_ids:[41,42],count:2,quantity:120}],has_more:false});`,
};
const entry=`import React from 'react';import {createRoot} from 'react-dom/client';import Review from './src/components/ShipmentReviewPanel';import Receive from './src/components/ReceivePackagesByOrder';import Delete from './src/components/DeleteWarehousePackage';
window.calls=[];const data={shipment:{id:8,status:'created',shipment_type:'manual'},review:{quantity:60,packages_count:1,amount:'120',calculated_amount:'120',basis:'x'.repeat(64)},packages:[{id:41,package_no:'PKG-TEST',quantity:60,scanned:true,quantity_items:[{item_id:1,color:'navy',size:'M',quantity:60,available_quantity:60}]}]};
createRoot(document.getElementById('root')).render(<><Review preparation={data} onChanged={async()=>{}}/><Receive/><Delete id={41} packageNo="PKG-TEST"/></>);`;
const built=await build({stdin:{contents:entry,resolveDir:root,loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',plugins:[{name:'fixtures',setup(b){b.onResolve({filter:/^@\//},args=>args.path in stubs?{path:args.path,namespace:'fixtures'}:undefined);b.onLoad({filter:/.*/,namespace:'fixtures'},args=>({contents:stubs[args.path],loader:'tsx',resolveDir:root}));}}]});
const browser=await chromium.launch({channel:process.platform==='win32'?'chrome':undefined});
try {
 const page=await browser.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
 async function load(options={}){await page.goto('about:blank');await page.setContent('<div id="root"></div>');await page.evaluate(opts=>Object.assign(window,opts),options);await page.addScriptTag({content:built.outputFiles[0].text});}
 await load();await page.locator('summary').click();await page.getByRole('button',{name:'Review quantity',exact:true}).click();
 await page.getByRole('spinbutton').fill('30');await page.getByRole('textbox',{name:'Reason',exact:true}).fill('Ship half');await page.getByRole('button',{name:'Save review',exact:true}).click();
 await page.waitForFunction(()=>window.calls.length===1);const selection=await page.evaluate(()=>window.calls[0]);assert.equal(selection.body.keep_remainder,true);assert.equal(selection.body.items[0].quantity,30);assert.equal(selection.body.expected_quantity,60);
 await page.getByRole('button',{name:'Receive by order',exact:true}).click();await page.getByRole('button',{name:'Mark received',exact:true}).click();await page.waitForFunction(()=>window.calls.length===2);assert.deepEqual((await page.evaluate(()=>window.calls[1])).body.package_ids,[41,42]);
 await page.evaluate(()=>window.confirmAction=false);await page.getByRole('button',{name:'Delete pack',exact:true}).click();assert.equal(await page.evaluate(()=>window.calls.length),2);
 await page.evaluate(()=>{window.confirmAction=true;window.fail=true});await page.getByRole('button',{name:'Delete pack',exact:true}).click();await page.getByRole('alert').waitFor();assert.equal(await page.getByRole('alert').innerText(),'Package is reserved');
 await load({allowed:false});assert.equal(await page.getByRole('button',{name:'Delete pack',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'Receive by order',exact:true}).count(),0);
 for(const [lang,label] of [['ru','Принять по заказу'],['uz','Buyurtma bo‘yicha qabul qilish']]){await load({lang});await page.getByRole('button',{name:label,exact:true}).waitFor();}
 assert.deepEqual(errors,[]);console.log('Warehouse controls: quantity selection, order receipt, deletion cancellation/failure, permissions and RU/UZ passed.');
}finally{await browser.close();}
