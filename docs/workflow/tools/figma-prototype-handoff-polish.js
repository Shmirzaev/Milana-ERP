for(const style of ['Regular','Medium','Semi Bold'])await figma.loadFontAsync({family:'Inter',style});
const p=await figma.getNodeByIdAsync('2:2');let changes=0;
for(const key of ['P094','P095','P096','P097']){
 const f=p.children.find(n=>n.name.startsWith(key+' · '));
 if(key!=='P095')for(const n of f.findAll(n=>n.type==='INSTANCE'&&['Create package','First Grade singles'].includes(n.name))){n.visible=false;changes++;}
 for(const n of f.findAll(n=>n.type==='FRAME'&&n.name.startsWith('Input · '))){
  const t=n.findOne(n=>n.type==='TEXT');if(!t)continue;
  const sample={'Input · Failed':'4','Input · Output':'1,196','Input · Print type':'Screen print','Input · Line name':'Line 01','Input · Order batch':'BATCH-101','Input · Capacity':'24','Input · Default weight (kg)':'5.8 kg'};if(sample[n.name]){t.characters=sample[n.name];changes++;}if(key==='P095'&&n.name==='Input · Material used'){t.characters='Poly bag · care label';changes++;}
  if(/Max pieces per batch/i.test(n.name)){t.characters='200';changes++;}
  if(n.name==='Input · /'){t.characters='Demo Employee A';const label=n.parent.children.find(n=>n.type==='TEXT');if(label)label.characters='OPERATOR';changes++;}
 }
 for(const records of f.findAll(n=>n.type==='FRAME'&&n.name==='Records')){
  const h=records.children.find(n=>n.name==='Table header'),cells=h.children.filter(n=>n.type==='TEXT');const packed=cells.findIndex(n=>n.characters==='PACKED');if(packed<0)continue;
  if(key!=='P095')cells[packed].characters='OUTPUT';
  for(const row of records.children.filter(n=>/^Record \d+$/.test(n.name))){const t=row.children.filter(n=>n.type==='TEXT');t[packed].characters=String(Number(t[1].characters.replace(/,/g,''))-Number(t[3].characters)-Number(t[4].characters.replace(/,/g,'')));changes++;}
 }
}
const ov=p.children.find(n=>n.getPluginData('overlayKey')==='save:P094');
if(!ov.children.some(n=>n.name==='Skip printing · send to sewing')){
 const source=ov.children.find(n=>n.type==='INSTANCE'&&n.name==='Continue');const b=source.clone();ov.insertChild(ov.children.indexOf(source)+1,b);b.name='Skip printing · send to sewing';const t=b.findOne(n=>n.type==='TEXT');t.characters=b.name;b.setPluginData('prototypeTarget','P097');b.setPluginData('prototypeOverlay','false');const dest=p.children.find(n=>n.name.startsWith('P097 · '));await b.setReactionsAsync([{trigger:{type:'ON_CLICK'},actions:[{type:'NODE',destinationId:dest.id,navigation:'NAVIGATE',transition:null}]}]);source.findOne(n=>n.type==='TEXT').characters='Send to printing';changes++;
}
print(JSON.stringify({kind:'handoff-polish',changes,optionalPrinting:true,packageCreationStage:'Packaging'}));
