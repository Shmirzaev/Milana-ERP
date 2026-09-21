for(const style of ['Regular','Medium','Semi Bold'])await figma.loadFontAsync({family:'Inter',style});
const p=await figma.getNodeByIdAsync('2:2');let fixed=0;
const shipment=p.children.find(n=>n.name.startsWith('P082 · '));
const create=shipment.findOne(n=>n.type==='INSTANCE'&&n.name==='Create shipment');
create.setPluginData('prototypeTarget','action:P082:Create shipment');create.setPluginData('prototypeOverlay','true');
for(const key of ['P027','P092']){const f=p.children.find(n=>n.name.startsWith(key+' · '));const action=f.findOne(n=>n.type==='INSTANCE'&&n.name==='Add record');if(action){action.name='Scan package';action.findOne(n=>n.type==='TEXT').characters='Scan package';action.setPluginData('prototypeTarget','P051');action.setPluginData('prototypeOverlay','false');fixed++;}}
for(const ov of p.children.filter(n=>/Create package$/i.test(n.getPluginData('overlayKey'))))for(const n of ov.findAll(n=>n.type==='FRAME'&&(n.name==='Input · Quantity'||n.name==='Input · Size'))){n.findOne(t=>t.type==='TEXT').characters=n.name.endsWith('Quantity')?'24':'M';fixed++;}
for(const t of p.findAll(n=>n.type==='TEXT')){const labels={title:'Preview image',placeholder:'Search',loadMoreText:'Load more',children:'Open',label:'Select'};if(labels[t.characters]){t.characters=labels[t.characters];fixed++;}}
print(JSON.stringify({kind:'finalize',fixed,shipmentCreationDialog:true,warehouseEntry:'Scan package'}));
