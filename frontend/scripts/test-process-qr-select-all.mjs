import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const source=fs.readFileSync('src/app/(app)/process-qr/page.tsx','utf8');
const ast=ts.createSourceFile('page.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let handler;
function visit(node){if(ts.isFunctionDeclaration(node)&&node.name?.text==='selectFactoryOperations')handler=node.getText(ast);ts.forEachChild(node,visit);}
visit(ast);assert.ok(handler);
for(const factory of ['milana','besttex','eco_cotton']){
  let dirty=0;
  let operations=['milana','besttex','eco_cotton'].flatMap(sewingFactory=>[false,true].map((selected,i)=>({id:sewingFactory+i,sewingFactory,selected,rate:'130',copies:2})));
  const before=structuredClone(operations);
  const select=new Function('markOperationsDirty','setOperations','paidOperationMatchesFactory','printPaidOperationFactory',ts.transpile(handler)+';return selectFactoryOperations;')(
    ()=>dirty++, fn=>{operations=fn(operations)},(op,value)=>op.sewingFactory===value,factory);
  for(const selected of [true,false,true]){
    select(selected);
    assert.ok(operations.filter(op=>op.sewingFactory===factory).every(op=>op.selected===selected));
    assert.deepEqual(operations.filter(op=>op.sewingFactory!==factory),before.filter(op=>op.sewingFactory!==factory));
    assert.ok(operations.every(op=>op.rate==='130'&&op.copies===2));
  }
  assert.equal(dirty,3);
}
console.log('Select all toggles only the selected factory, preserves operations and marks unsaved changes.');
