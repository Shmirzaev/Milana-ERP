// Isolated real React/SWR pagination, plus actual issued-label layout. No ERP connection.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import QRCode from "qrcode";

const root = process.cwd();
const output = path.resolve(root, "../outputs/ui-qa");
fs.mkdirSync(output, { recursive: true });
const processPage = fs.readFileSync("src/app/(app)/process-qr/page.tsx", "utf8");
const labelStart = processPage.indexOf("function IssuedProcessLabel(");
const labelEnd = processPage.indexOf("function ProcessQrImage(", labelStart);
const labelSource = processPage.slice(labelStart, labelEnd > 0 ? labelEnd : undefined);
const printHelper = processPage.slice(processPage.indexOf("function sewingLinePrintText("), processPage.indexOf("function qrDataUrl("));
const css = processPage.split('<style jsx global>{`')[1].split('`}</style>')[0];
const qrImage = await QRCode.toDataURL("200028408", { width: 220, margin: 1 });
const entry = `
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import useLoadMore from "./src/lib/useLoadMore";
import PaginationControls from "./src/components/PaginationControls";
import { useT } from "@/lib/i18n";
const VALID_SECTIONS=["sewing"], SECTION_BADGES={sewing:""};
const paidSectionLabel=()=>"Sewing", formatModelVariantCode=(x)=>x, orderReference=x=>x.sales_order_no;
const Pencil=()=>null, ProcessQrImage=()=>null;
${printHelper}
${labelSource}
const label={id:1,factory_code:"BST",operation_name:"bort overlo",operation_section:"sewing",model_code:"PB10012-V-6311",sales_order_no:"MAN-8288-9327-1ULI",batch_no:"0420-01",sewing_line_code:"BST-BAND-06",sewing_line_name:"Muqadamxon",size:"122",quantity:67,rate_per_piece:150,currency:"UZS",cutting_passport_no:"9327",qr_token:"200028408"};
function App(){
 const [page,setPage]=useState(1),[q,setQ]=useState(""),[scope,setScope]=useState("MIL");
 const pager=useLoadMore(["/rows?q="+q+"&page="+page+"&page_size=50",scope],async([url,factory])=>{const response=await fetch(url+"&factory="+factory);if(!response.ok)throw Error("fixture failure");return response.json();},{shouldRetryOnError:false,revalidateOnFocus:false,dedupingInterval:0});
 return <><input aria-label="Search" value={q} onChange={e=>{setQ(e.target.value);setPage(1)}}/><button onClick={()=>{setScope(scope==="MIL"?"BST":"MIL");setPage(1)}}>Switch factory</button><button onClick={()=>pager.mutate()}>Refresh</button>
 <div id="rows">{pager.data?.rows.map(row=><div key={row.id} data-row>{row.name}</div>)}</div>
 <PaginationControls page={page} pageSize={50} total={pager.data?.total||0} count={pager.data?.rows.length||0} onPageChange={setPage} onPageSizeChange={()=>{}} loading={pager.isValidating} error={pager.error} onRetry={()=>pager.mutate()}/></>;
}
const isLabels=location.pathname==="/labels";
createRoot(document.getElementById("root")).render(isLabels ? <section className="print-sheet work-print-section"><div className="label-grid">{["BST","MIL","ECO"].map(factory=><IssuedProcessLabel key={factory} label={{...label,factory_code:factory,sewing_line_code:factory==="BST"?"BST-BAND-06":"SEW-01",model_code:"BJ5030-V-5796",sales_order_no:"MAN-7345-9415-1ULI",sewing_line_name:"Bozorova Nargiza"}} qrImage=${JSON.stringify(qrImage)} operationNumber={8}/>)}</div></section> : <App/>);
`;
// Strip types through esbuild, preserving the real component implementation.
const built=await build({stdin:{contents:entry,resolveDir:root,loader:"tsx"},bundle:true,write:false,format:"iife",plugins:[{name:"fixture-i18n",setup(b){b.onResolve({filter:/^@\/lib\/i18n$/},()=>({path:"i18n",namespace:"fixture"}));b.onLoad({filter:/.*/,namespace:"fixture"},()=>({contents:`const lang=new URLSearchParams(location.search).get('lang')||'uz';const keys=['common.model','field.orderNo','field.batch','page.processQr.line','field.size','field.qty','page.processQr.rate','page.processQr.kroyNo'];const values={en:['Model','Order','Batch','Line','Size','Quantity','Rate','Cut no'],ru:['Модель','Заказ','Партия','Линия','Размер','Количество','Цена','Крой №'],uz:['Model','Buyurtma','Partiya','Liniya',"O‘lcham",'Miqdor','Narx','Kroy no']};const captions=Object.fromEntries(keys.map((key,i)=>[key,values[lang][i]]));export const useT=()=>({lang,t:(key)=>({...captions,'common.loadMore':'Load more','common.retry':'Retry','common.loading':'Loading','field.unitPcs':'dona'}[key]||key)});`,loader:"js"}));}}]});
let failNext=false;const calls=[];
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,"http://local");
 if(url.pathname==="/rows"){
  calls.push(Object.fromEntries(url.searchParams));
  if(failNext){failNext=false;res.statusCode=500;res.end("failure");return;}
  const q=url.searchParams.get("q"), factory=url.searchParams.get("factory"),page=Number(url.searchParams.get("page"));
  const total=q==="needle"?3:123;
  if(q==="slow")await new Promise(r=>setTimeout(r,250));
  const rows=Array.from({length:total},(_,id)=>({id:id+1,name:factory+" "+(q||"row")+" "+(id+1)})).slice((page-1)*50,page*50);
  res.setHeader("Content-Type","application/json");res.end(JSON.stringify({rows,total,has_more:page*50<total}));return;
 }
 res.setHeader("Content-Type","text/html;charset=utf-8");
 res.end(`<html><head><style>${css} .flex{display:flex}.flex-col{flex-direction:column}.flex-1{flex:1}.min-w-0{min-width:0}.justify-between{justify-content:space-between}.grid{display:grid}.process-label__body{gap:8px}.process-label__details{font-family:Arial}.process-label__header{display:flex} .process-label__line{display:grid;grid-template-columns:33px minmax(0,1fr)} .process-label__title{font-weight:700}</style></head><body><div id="root"></div><script>${built.outputFiles[0].text.replaceAll("</script>","<\\/script>")}</script></body></html>`);
});
await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
const browser=await chromium.launch({channel:process.platform === "win32" ? "chrome" : undefined,headless:true});
const page=await browser.newPage();const errors=[];page.on("pageerror",error=>errors.push(error.message));
const url=`http://127.0.0.1:${server.address().port}`;
try{
 await page.goto(url);await page.locator("[data-row]").nth(49).waitFor();
 assert.equal(await page.locator("[data-row]").count(),50);
 await page.getByRole("button",{name:"Load more",exact:true}).click();
 await page.locator("[data-row]").nth(99).waitFor();assert.equal(await page.locator("[data-row]").count(),100);
 failNext=true;await page.getByRole("button",{name:"Load more",exact:true}).click();await page.getByRole("button",{name:"Retry",exact:true}).waitFor();
 assert.equal(await page.locator("[data-row]").count(),100);
 await page.getByRole("button",{name:"Retry",exact:true}).click();await page.locator("[data-row]").nth(122).waitFor();
 assert.equal(await page.locator("[data-row]").count(),123);assert.equal(await page.getByRole("button",{name:"Load more",exact:true}).count(),0);
 await page.getByLabel("Search").fill("needle");await page.waitForFunction(()=>document.querySelectorAll("[data-row]").length===3);
 assert.equal(await page.locator("[data-row]").first().textContent(),"MIL needle 1");
 await page.getByRole("button",{name:"Switch factory"}).click();await page.waitForFunction(()=>document.querySelector("[data-row]")?.textContent==="BST needle 1");
 await page.getByLabel("Search").fill("slow");await page.getByLabel("Search").fill("needle");await page.waitForTimeout(350);
 assert.equal(await page.locator("[data-row]").count(),3);assert.equal(await page.locator("[data-row]").first().textContent(),"BST needle 1");
 assert(calls.every(call=>call.page_size==="50"));assert(calls.some(call=>call.page==="3"));
 await page.goto(url+"/labels");await page.emulateMedia({media:"print"});await page.locator(".process-label--besttex").waitFor({state:"attached"});
 assert(!(await page.locator(".process-label--besttex").innerText()).includes("BST-BAND-06"));
 assert((await page.locator(".process-label--besttex").innerText()).includes("Bozorova Nargiza"));
 assert((await page.locator(".process-label:not(.process-label--besttex)").first().innerText()).includes("SEW-01"));
 await page.emulateMedia({media:"print"});
 const sizes=await page.locator(".process-label__qr").evaluateAll(nodes=>nodes.map(node=>parseFloat(getComputedStyle(node).width)));
 assert(Math.abs(sizes[0]-18*96/25.4)<1);assert(Math.abs(sizes[1]-21*96/25.4)<1);
 for(const lang of ["uz","ru","en"]){
  await page.goto(url+"/labels?lang="+lang);
  await page.locator(".process-label").nth(2).waitFor({state:"attached"});
  const labels=await page.locator(".process-label").evaluateAll(nodes=>nodes.map(node=>({
   headings:[...node.querySelectorAll(".process-label__line > span:first-child")].map(el=>({text:el.textContent,title:el.title})),
   values:[...node.querySelectorAll(".process-label__value")].map(el=>({text:el.textContent,width:el.clientWidth,scroll:el.scrollWidth,height:el.clientHeight,scrollHeight:el.scrollHeight})),
   footer:node.querySelector(".process-label__footer").textContent,
   width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height,
  })));
  for(const label of labels){
   assert(label.headings.every(h=>h.text===Array.from(h.title)[0]),lang+": initial-only captions");
   assert.equal(label.values[0].text,"BJ5030-V-5796");
   assert.equal(label.values[1].text,"MAN-7345-9415-1ULI");
   for(const value of label.values){assert(value.scroll<=value.width+1,lang+": clipped "+value.text);assert(value.scrollHeight<=value.height+1,lang+": vertically clipped "+value.text);}
   assert(label.footer.includes("QR 200028408"));
   assert(Math.abs(label.width-60*96/25.4)<1);assert(Math.abs(label.height-40*96/25.4)<1);
  }
  await page.screenshot({path:path.join(output,"process-qr-initials-"+lang+".png"),fullPage:true});
 }
 await page.locator(".process-label--besttex").screenshot({path:path.join(output,"besttex-process-qr.png")});
 assert.deepEqual(errors,[]);console.log("PASS: real SWR pagination; Besttex-only QR/name rules; all three factories and EN/RU/UZ use initials and show full model/order/values on 60x40mm labels without clipping.");
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
