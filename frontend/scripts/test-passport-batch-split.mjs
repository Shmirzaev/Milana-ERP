import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import React from "react";
import * as jsx from "react/jsx-runtime";
import { renderToStaticMarkup } from "react-dom/server";

const read = path => fs.readFileSync(new URL(path, import.meta.url), "utf8");
function compile(source, dependencies = {}) {
  const output = ts.transpileModule(source, {compilerOptions: {module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports = {};
  new Function("exports","require",output)(exports, name => {assert.ok(name in dependencies, name);return dependencies[name];});
  return exports;
}
function walk(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(walk);
  if (typeof node.type === "function") return walk(node.type(node.props));
  return [node,...walk(node.props?.children)];
}
const lib=compile(read("../src/lib/passportBatchSplit.ts"));
const batches={1:{id:1,batch_no:"LOT-A",item_id:5,color:" RED ",unit:"kg",width:180,gsm:180,available_quantity:150},
  2:{id:2,batch_no:"LOT-B",item_id:5,color:"red",unit:"kg",width:180,gsm:180,available_quantity:250}};
const group={stock_batch_id:1,planned_kg:300,layer_weight_kg:6,total_layers:50,pieces:600,
  batch_allocations:[{stock_batch_id:1,quantity:100,batch_no:"LOT-A"},{stock_batch_id:2,quantity:200,batch_no:"LOT-B"}]};
assert.equal(lib.passportSplitProblem(group,batches),null);
assert.equal(lib.passportSplitProblem({...group,meter_mode:true},batches),"incompatible");
assert.equal(lib.passportSplitProblem(group,{1:{...batches[1],unit:"m"},2:{...batches[2],unit:"m"}}),"incompatible");
assert.equal(lib.passportUsageQuantity({...group,beka_per_piece_kg:.01}),300,"kg ledger must not change its inherited binding semantics");
assert.equal(lib.passportUsageQuantity({...group,meter_mode:true,beka_per_piece_kg:.01}),306);
assert.equal(lib.passportUsageQuantity({planned_kg:.3}),.3);
assert.equal(lib.passportUsageQuantity({meter_mode:true,layer_weight_kg:1,total_layers:1,beka_per_piece_kg:.0001,pieces:5}),1);
assert.equal(lib.passportUsageQuantity({meter_mode:true,layer_weight_kg:1,total_layers:1,beka_per_piece_kg:.0003,pieces:5}),1.002);
assert.equal(lib.passportUsageQuantity({layer_weight_kg:"0.3335",total_layers:3}),1);
assert.equal(lib.passportUsageQuantity({planned_kg:1.0005}),1);
assert.equal(lib.passportUsageQuantity({planned_kg:1.0015}),1.002);
assert.ok(Number.isNaN(lib.passportUsageQuantity({planned_kg:-1})));
assert.equal(lib.passportSplitProblem({...group,batch_allocations:[{stock_batch_id:1,quantity:.1},{stock_batch_id:2,quantity:.2}],layer_weight_kg:0,planned_kg:.3},batches),null);
for(const [patch,expected] of [
  [[{stock_batch_id:1,quantity:""},{stock_batch_id:2,quantity:200}],"amount"],
  [[{stock_batch_id:1,quantity:-1},{stock_batch_id:2,quantity:301}],"amount"],
  [[{stock_batch_id:1,quantity:.0001},{stock_batch_id:2,quantity:299.9999}],"amount"],
  [[{stock_batch_id:1,quantity:Infinity},{stock_batch_id:2,quantity:200}],"amount"],
  [[{stock_batch_id:1,quantity:90},{stock_batch_id:2,quantity:200}],"mismatch"],
  [[{stock_batch_id:1,quantity:160},{stock_batch_id:2,quantity:140}],"stock"],
  [[{stock_batch_id:1,quantity:100},{stock_batch_id:1,quantity:200}],"duplicate"],
]) assert.equal(lib.passportSplitProblem({...group,batch_allocations:patch},batches),expected);
for(const patch of [{item_id:6},{color:"blue"},{unit:"m"},{width:175},{gsm:220}]) {
  assert.equal(lib.compatiblePassportBatches(batches[1],{...batches[2],...patch}),false);
  assert.equal(lib.passportSplitProblem(group,{...batches,2:{...batches[2],...patch}}),"incompatible");
}
assert.equal(lib.passportSplitProblem(group,{...batches,1:{...batches[1],available_quantity:0}},false),null,"used passports may reopen after stock was consumed");
for(const dimension of ["width","gsm"]) {
  const three={...batches,1:{...batches[1],[dimension]:null},3:{...batches[2],id:3,[dimension]:175}};
  const split={...group,batch_allocations:[{stock_batch_id:1,quantity:100},{stock_batch_id:2,quantity:100},{stock_batch_id:3,quantity:100}]};
  assert.equal(lib.passportSplitProblem(split,three),"incompatible","unknown anchor must not hide conflicting known dimensions");
  assert.equal(lib.compatiblePassportGroup(Object.values(three)),false);
}

for(const lang of ["en","ru","uz"]) {
  const {default: Split}=compile(read("../src/components/PassportBatchSplit.tsx"),{
    "react/jsx-runtime":jsx,"@/lib/i18n":{useT:()=>({lang})},"@/lib/passportBatchSplit":lib,
    "lucide-react":{Plus:()=>null,Trash2:()=>null},
  });
  const calls=[];
  const props={material:group,batches,disabled:false,locked:false,pendingIds:[2],onChange:(...args)=>calls.push(args),onAdd:()=>calls.push("add"),onRemove:id=>calls.push(id)};
  const tree=Split(props), html=renderToStaticMarkup(tree);
  for(const token of ["LOT-A","LOT-B","100","200","300",lib.passportBatchText(lang).once]) assert.ok(html.includes(token));
  const nodes=walk(tree);
  nodes.find(node=>node.type==="input").props.onChange({target:{value:"95"}});assert.deepEqual(calls.shift(),[1,"95"]);
  assert.equal(nodes.filter(node=>node.type==="button")[0].props.disabled,true,"anchor cannot be removed");
  const locked=walk(Split({...props,locked:true}));
  assert.ok(locked.filter(node=>node.type==="input"||node.type==="button").every(node=>node.props.disabled));
  assert.ok(!renderToStaticMarkup(Split({...props,locked:true})).includes(lib.passportBatchText(lang).add));
  assert.ok(walk(Split({...props,disabled:true})).filter(node=>node.type==="input"||node.type==="button").every(node=>node.props.disabled));
}

// Exercise actual page coordination: merge two assigned batches, save/reopen-safe
// source shape, refused request draft retention and explicit batch separation.
const source=read("../src/app/(app)/cutting-passports/page.tsx");
const ast=ts.createSourceFile("page.tsx",source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const names=new Set(["addMaterial","removeSplitBatch","removePendingMaterial","buildPayload","num","save"]),parts=[];
let empty;
function visit(node){
  if(ts.isFunctionDeclaration(node)&&names.has(node.name?.text))parts.push(node.getText(ast));
  if(ts.isVariableDeclaration(node)&&node.name.getText(ast)==="EMPTY_FORM")empty=node.initializer.getText(ast);
  ts.forEachChild(node,visit);
}
visit(ast);
const fabricSources=compile(read("../src/lib/fabricSource.ts"));
const context=vm.createContext({ ...lib, ...fabricSources, console, Number,Date, Map,Set,lang:"en",splitText:lib.passportBatchText("en"),
  t:key=>key,editing:null,saving:false,splitTarget:1,selectedMaterial:{...batches[2],item_name:"Cotton"},materialAmount:"200",batchInfos:batches,
  mutate:async()=>{},refreshCache:async()=>{},resetMaterialPicker:()=>{},setShowForm:()=>{},setSelectedMaterial:()=>{},setMaterialAmount:()=>{},setMaterialPickerOpen:()=>{},setSplitTarget:()=>{},
});
const run=code=>vm.runInContext(ts.transpileModule(code,{compilerOptions:{target:ts.ScriptTarget.ES2020}}).outputText,context);
run(`const EMPTY_FORM=${empty}; globalThis.empty=EMPTY_FORM; ${parts.join("\n")}`);
context.form={...context.empty,date:"2026-11-05",production_order_id:7,pieces:600};
context.materialForms=[{...context.form,stock_batch_id:1,fabric_type:"Cotton",lot_no:"LOT-A",planned_kg:100},
  {...context.form,stock_batch_id:2,fabric_type:"Cotton",lot_no:"LOT-B",planned_kg:200}];
context.additionalMaterials=[];
const sync=()=>{context.splitProblem=context.materialForms.map(row=>lib.passportSplitProblem(row,context.batchInfos)).find(Boolean);};
for(const [setter,key] of [["setMaterialForms","materialForms"],["setAdditionalMaterials","additionalMaterials"],["setBatchInfos","batchInfos"]]) context[setter]=value=>{context[key]=typeof value==="function"?value(context[key]):value;sync();};
context.setErr=value=>{context.error=value;};context.setSaving=value=>{context.saving=value;};
const requests=[];context.api={post:async(path,payload)=>requests.push({path,payload}),patch:async()=>{throw Error("unexpected patch");}};
context.addMaterial();
assert.equal(context.materialForms.length,1);
assert.equal(context.materialForms[0].planned_kg,300);
assert.equal(context.materialForms[0].pieces,600);
assert.deepEqual(Array.from(context.materialForms[0].batch_allocations,row=>Number(row.quantity)),[100,200]);
context.materialForms[0].layer_weight_kg=6;context.materialForms[0].total_layers=50;sync();
await context.save({preventDefault(){}});
assert.equal(requests.length,1);assert.equal(requests[0].payload.materials.length,1);
assert.deepEqual(Array.from(requests[0].payload.materials[0].batch_allocations,row=>[row.stock_batch_id,row.quantity]),[[1,100],[2,200]]);
assert.equal(requests[0].payload.materials[0].pieces,600);
const draft=JSON.stringify(context.materialForms);
context.api.post=async()=>{throw Error("stock changed");};
await context.save({preventDefault(){}});
assert.equal(context.error,"stock changed");assert.equal(JSON.stringify(context.materialForms),draft);
context.removeSplitBatch(1,2);
assert.equal(context.materialForms.length,2,"an assigned source becomes its own entry; it cannot disappear from the order");
assert.equal(context.materialForms[0].batch_allocations.length,1);
assert.equal(context.splitProblem,"mismatch","removing a source must not silently move its quantity to the remaining batch");
context.materialForms=[{...context.form,stock_batch_id:1,batch_allocations:[{stock_batch_id:1,quantity:100}]}];
context.additionalMaterials=[{stock_batch_id:1,estimated_quantity:100,unit:"kg"}];
context.removePendingMaterial(context.materialForms[0]);
assert.equal(context.materialForms.length,0,"a pending singleton entry remains removable");assert.equal(context.additionalMaterials.length,0);
const cuttingSource=read("../src/app/(app)/work-orders/[id]/cutting/page.tsx");
const cuttingAst=ts.createSourceFile("cutting.tsx",cuttingSource,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let saveDetails;
function findDetails(node){if(ts.isFunctionDeclaration(node)&&node.name?.text==="saveCuttingDetailsEdit")saveDetails=node.getText(cuttingAst);ts.forEachChild(node,findDetails);}
findDetails(cuttingAst);run(saveDetails);
context.numberOrZero=value=>Number(value)||0;
context.editingCuttingDetails={groupedMaterials:true,recordId:5,materialUsagePending:false,materials:[{stock_batch_id:1,details:{cut_pieces:600}}],notes:"  QA note  "};
context.setEditingCuttingDetailsBusy=()=>{};context.setEditingCuttingDetailsErr=()=>{};context.setEditingCuttingDetails=()=>{};context.setDoneMsg=()=>{};
let notePayload;context.api.patch=async(path,payload)=>{notePayload={path,payload};};
await context.saveCuttingDetailsEdit();
assert.equal(notePayload.path,"/api/cutting/records/5");
assert.deepEqual(Object.keys(notePayload.payload),["notes"],"grouped notes editing must never resend locked material calculations");
assert.equal(notePayload.payload.notes,"QA note");
console.log("Passport shared-batch totals, compatibility/stock/precision refusals, readonly controls EN/RU/UZ, actual merge/save/refusal/separate handlers passed.");
