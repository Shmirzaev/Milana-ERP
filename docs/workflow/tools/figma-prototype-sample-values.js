for(const style of ['Regular','Medium','Semi Bold'])await figma.loadFontAsync({family:'Inter',style});
const p=await figma.getNodeByIdAsync('2:2');let changed=0;
for(const f of p.children.filter(n=>/^[PV]\d{3} · /.test(n.name)))for(const r of f.findAll(n=>n.type==='FRAME'&&n.name==='Records')){
 const header=r.children.find(n=>n.name==='Table header');if(!header)continue;const cols=header.children.filter(n=>n.type==='TEXT').map(n=>n.characters.toLowerCase());
 r.children.filter(n=>/^Record \d+$/.test(n.name)).forEach((row,i)=>row.children.filter(n=>n.type==='TEXT').forEach((t,c)=>{
  if(cols[c]==='manager'){t.characters='Demo Manager';changed++;}
  if(cols[c]==='employee id'){t.characters='EMP-DEMO-'+(101+i);changed++;}
  if(cols[c]==='status'&&/^P0(?:07|23|29|30|32|33|34|35|36|37)/.test(f.name)){t.characters=i===4?'On leave':'Active';changed++;}
  if(cols[c]==='operation'){t.characters=['Shoulder seam','Sleeve attachment','Hem stitch','Label attachment','Final check'][i%5];changed++;}
 }));
}
const calendar=p.children.find(n=>n.name.startsWith('P031 · '));for(const day of calendar.findAll(n=>n.type==='FRAME'&&/^Day 3[1-5]$/.test(n.name))){day.visible=false;changed++;}
print(JSON.stringify({kind:'sample-values',changed}));
