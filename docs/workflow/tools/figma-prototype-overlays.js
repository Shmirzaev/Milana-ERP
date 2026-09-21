// Append to the prototype runtime; JOB.kind is "overlays".
if(JOB.kind==='overlays'){
 const overlays=[];
 function close(p){button(p,'Close','CLOSE','secondary',120);}
 function nextRoute(s){if(!s)return '/';const r=s.route;if(r.includes('/cutting'))return '/work-orders/[id]/printing';if(r.includes('/printing'))return '/work-orders/[id]/sewing';if(r.includes('/sewing'))return '/packaging/receive';if(r.includes('/packaging'))return '/warehouse-stock';if(r.includes('shipment'))return '/shipments/history';if(s.group===2)return '/sales-orders/[id]';if(s.group===4)return '/production-orders/[id]';if(s.group===6)return '/inventory';return s.route;}
 for(const key of JOB.keys){
  if(page.children.some(n=>n.getPluginData('overlayKey')===key))continue;
  const parts=key.split(':'),kind=parts[0],s=SPEC.screens.find(s=>s.id===parts[1]);
  const wide=kind==='module'||kind==='all-workspaces';
  const p=card(page,'Dialog · '+key,wide?820:560,28);p.setPluginData('overlayKey',key);p.x=9000+(page.children.filter(n=>n.getPluginData('overlayKey')).length%4)*940;p.y=Math.floor(page.children.filter(n=>n.getPluginData('overlayKey')).length/4)*960;p.cornerRadius=12;

  const w=wide?764:504;
  if(kind==='module'){
   txt(p,SPEC.moduleNames[Number(parts[1])-1],24,'Semi Bold');txt(p,'Choose a workspace',13,'Regular','soft');
   for(const screen of SPEC.screens.filter(x=>x.group===Number(parts[1])))button(p,displayTitle(screen),screen.id,'secondary',w);
  }else if(kind==='all-workspaces'){
   txt(p,'Workspaces',24,'Semi Bold');txt(p,'Explore the Milana demo environment',13,'Regular','soft');
   for(let i=0;i<16;i+=2){const r=row(p,'Modules',w,16);button(r,SPEC.moduleNames[i],'module:'+(i+1),'secondary',(w-16)/2,true);button(r,SPEC.moduleNames[i+1],'module:'+(i+2),'secondary',(w-16)/2,true);}
  }else if(kind==='menu'){
   txt(p,displayTitle(s),22,'Semi Bold','ink',w);txt(p,'Actions',12,'Semi Bold','subtle');
   const controls=s.controls.length?s.controls:[{label:'View record',targets:[detailDestination(s)||s.id]}];
   for(const c of controls){const dest=c.targets.find(t=>t!==s.id&&SPEC.screens.some(x=>x.id===t));button(p,c.label,dest||'action:'+s.id+':'+c.label,'secondary',w,!dest);}
  }else if(kind==='save'||kind==='scan'){
   badge(p,kind==='scan'?'QR validated':'Saved successfully');txt(p,kind==='scan'?'Sample item accepted':'Your changes are saved',24,'Semi Bold','ink',w);
   txt(p,kind==='scan'?'PK-DEMO-8401 · MP-2401 · Navy · Size M':'Demo record · '+(s?.group===2?'SO':'PO')+'-DEMO-2401',14,'Regular','soft',w);
   txt(p,kind==='scan'?'24 pieces received. The item is ready for the next department.':'The sample record is ready for the next step.',14,'Regular','ink',w);
   if(s?.route.includes('/cutting'))button(p,'Skip printing · send to sewing',target('/work-orders/[id]/sewing'),'secondary',w);
   button(p,kind==='scan'?'View item':'Continue',target(kind==='scan'?'/packages/[id]':nextRoute(s)),'primary',w);
   if(s?.group===2)button(p,'Send to planning',target('/planning'),'secondary',w);
  }else if(kind==='action'){
   const label=parts.slice(2).join(':');txt(p,label,24,'Semi Bold','ink',w);
   if(/delete|remove|cancel order/i.test(label)){txt(p,'Remove this sample record?',16,'Medium');txt(p,'This action applies only to the fictional prototype record.',13,'Regular','soft',w);}
   else if(/export|print|download/i.test(label)){txt(p,'Document preview',16,'Semi Bold');fields(p,s||{},['Reference','Date','Quantity'],w);txt(p,'PO-DEMO-2401 · Milana · September 2026',13,'Regular','soft',w);}
   else{fields(p,s||{},/package|single/i.test(label)?['Production order','Model','Color','Size','Quantity']:['Name','Quantity','Notes'],w);}
   if(/single/i.test(label)){for(const n of p.findAll(n=>n.type==='FRAME'&&(n.name==='Input · Quantity'||n.name==='Input · Size'))){const t=n.findOne(t=>t.type==='TEXT');if(t)t.characters=n.name.endsWith('Quantity')?'1':'M';}}
   button(p,/export|print|download/i.test(label)?'Done':'Confirm',/export|print|download/i.test(label)?'CLOSE':'save:'+(s?.id||'P055'),'primary',w,!/export|print|download/i.test(label));
  }else if(kind==='filter'){
   txt(p,'Filter records',24,'Semi Bold');for(const status of ['All records','In progress','Ready','Completed'])button(p,status,'CLOSE','secondary',w);
  }else if(kind==='notifications'){
   txt(p,'Notifications',24,'Semi Bold');txt(p,'Today',12,'Semi Bold','subtle');txt(p,'PO-DEMO-2401 is ready for packaging.',15,'Medium','ink',w);button(p,'Open packaging queue',target('/packaging/queue'),'primary',w);txt(p,'New sales order SO-DEMO-2402 needs planning.',15,'Medium','ink',w);button(p,'Open planning',target('/planning'),'secondary',w);
  }else if(kind==='tasks'){
   txt(p,'My tasks',24,'Semi Bold');txt(p,'3 open tasks · Demo Manager',13,'Regular','soft');for(const [label,route] of [['Review new sales order','/sales-orders/[id]'],['Confirm packaging receipt','/packaging/receive'],['Prepare shipment','/shipments']])button(p,label,target(route),'secondary',w);
  }else if(kind==='language'){
   txt(p,'Language',24,'Semi Bold');txt(p,'This review prototype uses English sample screens.',13,'Regular','soft',w);for(const lang of ['English · selected','Русский','O‘zbekcha'])button(p,lang,'CLOSE','secondary',w);
  }else if(kind==='assistant-reply'){
   txt(p,'Production summary',24,'Semi Bold');txt(p,'PO-DEMO-2401: 1,200 planned, 1,180 cut, 800 sewn and 480 packed.',16,'Regular','ink',w);button(p,'View production order',target('/production-orders/[id]'),'primary',w);
  }else if(kind==='reset-confirm'){
   txt(p,'Check your email',24,'Semi Bold');txt(p,'A sample reset confirmation is shown for demo@example.com.',14,'Regular','soft',w);button(p,'Back to sign in',target('/login'),'primary',w);
  }else{
   txt(p,'Sample records · '+(kind==='next'?'Page 2':'Page 1'),24,'Semi Bold');table(p,{group:2},['Order','Quantity','Status'],4,w,target('/sales-orders/[id]'));
  }
  close(p);if(p.height>760){p.primaryAxisSizingMode='FIXED';p.resize(p.width,760);p.clipsContent=true;p.overflowDirection='VERTICAL';}overlays.push({key,id:p.id});
 }
 print(JSON.stringify({kind:'overlays',overlays,links,created:created.length}));
}
