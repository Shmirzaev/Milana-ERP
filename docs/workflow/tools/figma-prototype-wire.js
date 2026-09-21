// Runs in Scripter after screens and dialogs exist. LINKS is the saved ledger.
const page=await figma.getNodeByIdAsync('2:2');await figma.setCurrentPageAsync(page);
const screenMap=new Map(page.children.filter(n=>/^[PV]\d{3} · /.test(n.name)).map(n=>[n.name.slice(0,4),n]));
const overlayMap=new Map(page.children.filter(n=>n.getPluginData('overlayKey')).map(n=>[n.getPluginData('overlayKey'),n]));
const intents=new Map(LINKS.map(l=>[l.id,l]));
for(const n of page.findAll(n=>!!n.getPluginData('prototypeTarget')))intents.set(n.id,{id:n.id,target:n.getPluginData('prototypeTarget'),overlay:n.getPluginData('prototypeOverlay')==='true'});
let wired=0,obsolete=0;const issues=[];
for(const l of intents.values()){
 const n=await figma.getNodeByIdAsync(l.id);if(!n||n.removed){obsolete++;continue;}
 const destination=screenMap.get(l.target)||overlayMap.get(l.target);
 if(l.target!=='CLOSE'&&!destination){issues.push({id:l.id,target:l.target,error:'Missing destination'});continue;}
 let root=n;while(root.parent&&root.parent.type!=='PAGE')root=root.parent;
 if(destination?.id===root.id)continue;
 try{await n.setReactionsAsync([{trigger:{type:'ON_CLICK'},actions:l.target==='CLOSE'?[{type:'CLOSE'}]:[{type:'NODE',destinationId:destination.id,navigation:overlayMap.has(l.target)?'OVERLAY':'NAVIGATE',transition:null}]}]);wired++;}catch(e){issues.push({id:l.id,target:l.target,error:String(e)});}
}
page.flowStartingPoints=[{nodeId:screenMap.get('P055').id,name:'Explore Milana ERP'},{nodeId:screenMap.get('P100').id,name:'Sign in to the demo'},{nodeId:screenMap.get('P074').id,name:'Sales order to shipment'}];
const blank=[...screenMap].filter(([k,f])=>!f.children.length).map(([k])=>k);
const broken=[];let reactionNodes=0;
for(const n of page.findAll(n=>'reactions' in n&&n.reactions.length>0)){reactionNodes++;for(const r of n.reactions)for(const a of r.actions||[]){if(a.type==='NODE'&&a.destinationId&&!await figma.getNodeByIdAsync(a.destinationId))broken.push({id:n.id,destination:a.destinationId});}}
figma.currentPage.selection=[screenMap.get('P055')];figma.viewport.scrollAndZoomIntoView(figma.currentPage.selection);
print(JSON.stringify({kind:'verification',pageId:page.id,screens:screenMap.size,dialogs:overlayMap.size,wired,obsolete,issues,blank,broken,reactionNodes,flows:page.flowStartingPoints}));
