// Append to the runtime with JOB.kind="data-polish".
if(JOB.kind==='data-polish'){
 let numericCells=0,formValues=0;
 for(const s of SPEC.screens){const f=page.children.find(n=>n.name.startsWith(s.id+' · '));
  for(const records of f.findAll(n=>n.type==='FRAME'&&n.name==='Records')){
   const header=records.children.find(n=>n.name==='Table header');if(!header)continue;
   const columns=header.children.filter(n=>n.type==='TEXT').map(n=>n.characters.toLowerCase());
   const rows=records.children.filter(n=>/^Record \d+$/.test(n.name));
   rows.forEach((r,i)=>r.children.filter(n=>n.type==='TEXT').forEach((t,c)=>{
    const label=columns[c]||'';
    if(/shortage/.test(label)){t.characters='0';numericCells++;}
    else if(/required|balance|actual|rolls|^count$|^total$|days|hours/.test(label)){t.characters=String(/rolls/.test(label)?12+i:/days/.test(label)?22:/hours/.test(label)?8:[120,72,180,48,96][i%5]);numericCells++;}
    else if(/^item$/.test(label)){t.characters=['Cotton jersey 180 GSM','Rib knit 240 GSM','Sewing thread · Navy','Care label','Brand label'][i%5];numericCells++;}
   }));
  }
  for(const input of f.findAll(n=>n.type==='FRAME'&&n.name.startsWith('Input · '))){const t=input.findOne(n=>n.type==='TEXT');if(!t)continue;
   if(input.name==='Input · Order type'){t.characters='Client order';formValues++;}
   if(/Printing instructions/.test(input.name)){t.characters='Front logo · 2 colors';formValues++;}
   if(/Attach picture or file/.test(input.name)){t.characters='MP-2401-specification.pdf';formValues++;}
  }
 }
 const order=page.children.find(n=>n.name.startsWith('P073 · '));
 for(const [old,label,val]of [['Name','Customer','Atlas Retail (Demo)'],['Phone','Order quantity','1,200']]){
  const field=order.findOne(n=>n.type==='FRAME'&&n.name===old);if(field){const title=field.children.find(n=>n.type==='TEXT');title.characters=label.toUpperCase();const input=field.children.find(n=>n.type==='FRAME');input.children.find(n=>n.type==='TEXT').characters=val;}
 }
 const records=order.findOne(n=>n.type==='FRAME'&&n.name==='Records');records.children.filter(n=>/^Record \d+$/.test(n.name)).forEach((r,i)=>r.children.filter(n=>n.type==='TEXT').forEach((t,c)=>t.characters=['MP-2401 · Everyday tee','Navy',['S','M','L'][i],'400','$4.80'][c]));
 print(JSON.stringify({kind:'data-polish',numericCells,formValues,salesOrderPieces:1200,salesOrderValue:5760}));
}
