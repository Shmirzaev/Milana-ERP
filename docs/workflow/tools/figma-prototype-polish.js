// Final cosmetic pass on the newly created prototype page only.
await figma.loadFontAsync({family:'Inter',style:'Regular'});
await figma.loadFontAsync({family:'Inter',style:'Semi Bold'});
const p=await figma.getNodeByIdAsync('2:2');let titles=0,sizes=0;
for(const f of p.children.filter(n=>/^[PV]\d{3} · /.test(n.name))){
 const key=f.name.slice(0,4);const heading=f.findOne(n=>n.type==='FRAME'&&n.name==='Title');
 if(heading){const t=heading.children.find(n=>n.type==='TEXT'&&n.fontSize===26);if(t){t.characters=key==='P055'?'Good morning, Demo Manager':t.characters.replace(/ — \/[^·]+/,'').replace('DEMO-2401 Inbox','Department inbox');titles++;}}
 if(['P094','P095','P096','P097','P049','P051'].includes(key))for(const input of f.findAll(n=>n.type==='FRAME'&&n.name==='Input · Size')){const text=input.findOne(n=>n.type==='TEXT');if(text){text.characters='M';sizes++;}}
}
const overflow=[];let resizedButtons=0;
for(const n of p.findAll(n=>n.type==='INSTANCE'&&n.name!=='ERP / Sidebar'&&n.name!=='ERP / Topbar')){
 const text=n.findOne(n=>n.type==='TEXT');if(text&&text.width>n.width-24){n.resize(Math.ceil(text.width+24),n.height);resizedButtons++;}if(text&&text.width>n.width-12)overflow.push({id:n.id,label:n.name,width:n.width,textWidth:text.width});
}
print(JSON.stringify({kind:'polish',titles,sizes,resizedButtons,buttonLabelOverflow:overflow}));
