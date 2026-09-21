/* Runs inside the Figma Plugin API. No network access or ERP writes. */
(async function () {
  await figma.loadFontAsync({family:'Inter',style:'Regular'});
  await figma.loadFontAsync({family:'Inter',style:'Semi Bold'});
  const page=figma.createPage();
  page.name='Milana ERP workflow 2026-09-21';
  await figma.setCurrentPageAsync(page);
  const color=hex=>({r:parseInt(hex.slice(0,2),16)/255,g:parseInt(hex.slice(2,4),16)/255,b:parseInt(hex.slice(4,6),16)/255});
  const paint=hex=>[{type:'SOLID',color:color(hex)}];
  function box(parent,name,x,y,w,h,fill='ffffff') {const n=figma.createFrame();n.name=name;n.resize(w,h);n.x=x;n.y=y;n.fills=paint(fill);n.strokes=paint('ded9ca');n.strokeWeight=1;n.clipsContent=false;parent.appendChild(n);return n;}
  function label(parent,str,x,y,width=800,size=16,bold=false,ink='14110b'){const n=figma.createText();n.name=String(str).slice(0,100);n.fontName={family:'Inter',style:bold?'Semi Bold':'Regular'};n.fontSize=size;n.fills=paint(ink);n.characters=String(str);n.textAutoResize='HEIGHT';n.resize(width,Math.max(size*1.5,20));n.x=x;n.y=y;parent.appendChild(n);return n;}
  async function link(node,dest,overlay=false){await node.setReactionsAsync([{trigger:{type:'ON_CLICK'},actions:[{type:'NODE',destinationId:dest.id,navigation:overlay?'OVERLAY':'NAVIGATE',transition:null}]}]);}
  const intro=box(page,'Read me',0,0,1060,490,'f8f7f3');
  label(intro,'Milana ERP workflow and navigation',32,30,980,30,true);
  label(intro,'Release '+ERP_MAP.release+' | Source '+ERP_MAP.baseline.slice(0,12),32,82,980,16);
  label(intro,'Functional map of '+ERP_MAP.routes.length+' route templates and '+ERP_MAP.controls.length+' control definitions. Screens use editable native layers. They are source-based wireframes, not production screenshots.',32,126,980,20);
  label(intro,'Click an index row to open a screen. Known page destinations navigate. Local saves, scans, print/downloads and unresolved dynamic links open clearly marked explanatory overlays; they never change ERP data. Factory/query variants retain their route text. A new-tab destination is described but uses a prototype transition.',32,218,980,18);
  label(intro,'Permissions and runtime state control actual visibility. Dynamic labels are retained as expressions where needed. Business arrows describe department handoffs and are separate from UI navigation. No real business records or secrets are included.',32,342,980,18);
  const handoff=box(page,'Business workflow',1160,0,1900,650,'f8f7f3');
  label(handoff,'Business handoffs',28,24,1800,28,true);
  label(handoff,'Arrows show business sequence. They are not page-opening controls.',28,68,1800,17);
  const stages=['Sales / branded / Usluga demand','Planning and materials','Cutting and bundles','Optional Printing','Sewing acceptance','Packaging / First Grade','Warehouse receipt','Reserve / scan / ship'];
  stages.forEach((s,i)=>{const column=i<4?i:7-i;const x=28+column*470,y=125+Math.floor(i/4)*205;box(handoff,s,x,y,420,125);label(handoff,s,x+18,y+18,385,22,true);if(i<3)label(handoff,'→',x+433,y+40,35,26);if(i>4)label(handoff,'←',x+433,y+40,35,26);});
  label(handoff,'↓',1640,265,50,26);
  label(handoff,'Printing can be skipped. Defects remain loss; no automatic failed-piece replacement. Singles require exact-size evidence and receipt. Customer ownership is preserved.',28,560,1800,18);
  const frames=new Map();const buttons=[];
  const groups=Array.from(new Set(ERP_MAP.screens.map(s=>s.group))).sort();
  let groupY=950;
  for(const group of groups){label(page,group,0,groupY,4000,30,true);groupY+=80;const screens=ERP_MAP.screens.filter(s=>s.group===group);let rowY=groupY,rowH=0;
    for(let i=0;i<screens.length;i++){const screen=screens[i];if(i>0&&i%3===0){rowY+=rowH+100;rowH=0;}const f=box(page,screen.id+' '+screen.route,(i%3)*1180,rowY,1080,600);frames.set(screen.id,f);f.setPluginData('route',screen.route);f.setPluginData('source',screen.file);
      const heading=label(f,screen.id+'  '+screen.title,28,24,1024,25,true);const route=label(f,screen.route,28,heading.y+heading.height+16,1024,17);const permission=label(f,'Functional control map · '+screen.permissions,28,route.y+route.height+16,1024,14,false,'56503f');
      const indexButton=box(f,'Back to screen index',28,permission.y+permission.height+20,1024,44,'f8f7f3');label(indexButton,'Screen index',12,10,990,16,true);buttons.push({node:indexButton,index:true});
      let cy=indexButton.y+64;
      for(const c of screen.controls){const b=box(f,c.id+' '+c.label,28,cy,1024,100,'ffffff');const tx=label(b,c.label,16,12,990,17,true);const details=(c.targets.length?'Opens '+c.targets.join(' or '):c.kind)+' | '+c.id+(c.kind==='open new tab'?' | opens a browser tab':'');const sub=label(b,details,16,tx.y+tx.height+8,990,14,false,'56503f');const h=Math.max(96,sub.y+sub.height+14);b.resize(1024,h);cy+=h+10;buttons.push({node:b,control:c,screen});}
      if(!screen.controls.length){const empty=label(f,'No direct control found. This route may redirect or delegate its view. Inspect the source reference before treating it as an empty production screen.',28,cy,1024,18);cy=empty.y+empty.height+24;}
      label(f,'Source: '+screen.file,28,cy+12,1024,13,false,'56503f');f.resize(1080,cy+80);rowH=Math.max(rowH,f.height);
    }groupY=rowY+rowH+180;
  }
  const idx=box(page,'All screens and sidebar navigation',-1260,0,1120,600,'ffffff');label(idx,'Screen index',28,26,1050,30,true);label(idx,'All route templates plus concrete sidebar scope variants. This index is a documentation control, not an added ERP menu.',28,78,1050,17);let iy=150;
  for(const s of ERP_MAP.screens){const b=box(idx,s.id+' '+s.route,28,iy,1064,58,'f8f7f3');label(b,s.id+'  '+s.route,14,15,1030,16,true);await link(b,frames.get(s.id));iy+=68;}idx.resize(1120,iy+30);
  const shared=box(page,'Shared controls',-2500,0,1120,600);label(shared,'Shared and unresolved component controls',28,28,1050,28,true);label(shared,'These controls have no statically resolved route owner. Shared navigation may be available across many pages, subject to permission.',28,90,1050,17);let sy=170;
  for(const c of ERP_MAP.globals){const b=box(shared,c.id+' '+c.label,28,sy,1064,100);const t=label(b,c.label,14,12,1030,17,true);const d=label(b,c.kind+' | '+c.id,14,t.y+t.height+8,1030,14);b.resize(1064,Math.max(96,d.y+d.height+14));sy+=b.height+10;buttons.push({node:b,control:c});}shared.resize(1120,sy+30);
  const sidebar=box(page,'Actual sidebar destinations',-3740,0,1120,600);label(sidebar,'Configured ERP sidebar',28,28,1050,28,true);label(sidebar,'Visibility is permission and factory dependent. Every configured sidebar destination is represented.',28,88,1050,17);let ny=160;
  for(const s of ERP_MAP.sidebar){const b=box(sidebar,s.label,28,ny,1064,100,'f8f7f3');const t=label(b,s.label,14,12,1030,18,true);const sub=label(b,s.destination+'\n'+s.permissions,14,t.y+t.height+8,1030,14);b.resize(1064,sub.y+sub.height+14);ny+=b.height+10;if(s.targets.length)await link(b,frames.get(s.targets[0]));}sidebar.resize(1120,ny+30);
  let oy=0,overlayRowHeight=0,overlayCount=0,wired=0;
  for(const b of buttons){if(b.index){await link(b.node,idx);continue;}const c=b.control;if(c.targets.length===1){await link(b.node,frames.get(c.targets[0]));wired++;continue;}
    const ov=box(page,'Action annotation '+c.id,3680+(overlayCount%3)*940,oy,880,420,'f8f7f3');
    const heading=label(ov,'Action annotation · '+c.id,24,22,832,23,true);let yy=heading.y+heading.height+18;
    const action=label(ov,c.label,24,yy,832,20,true);yy=action.y+action.height+20;
    const description=label(ov,c.targets.length>1?'Conditional destination. Choose a documented branch below.':'Effect: '+c.kind+'. This prototype does not perform the business action.',24,yy,832,18);yy=description.y+description.height+18;
    const detail=label(ov,(c.destination?'Destination expression: '+c.destination+'\n':'')+'Source: '+c.file+':'+c.line+'\n'+(c.disabled?'Disabled condition: '+c.disabled+'\n':'')+'Source inspection only; actual visibility and result depend on permissions, record state and server validation.',24,yy,832,15);yy=detail.y+detail.height+20;
    for(const target of c.targets){const dest=frames.get(target);const branch=box(ov,'Open '+target,24,yy,832,48);label(branch,'Open '+ERP_MAP.screens.find(s=>s.id===target).route,12,12,806,16,true);await link(branch,dest);yy+=60;}
    const close=box(ov,'Close annotation',24,yy,832,48);label(close,'Close annotation',12,12,806,16,true);await close.setReactionsAsync([{trigger:{type:'ON_CLICK'},actions:[{type:'CLOSE'}]}]);ov.resize(880,yy+72);await link(b.node,ov,true);overlayCount++;overlayRowHeight=Math.max(overlayRowHeight,ov.height);if(overlayCount%3===0){oy+=overlayRowHeight+100;overlayRowHeight=0;}
  }
  const openIndex=box(intro,'Open index',32,430,996,42,'ffffff');label(openIndex,'Open screen index',12,9,970,16,true);await link(openIndex,idx);
  page.flowStartingPoints=[{nodeId:intro.id,name:'Milana ERP navigation guide'}];
  page.selection=[intro];figma.viewport.scrollAndZoomIntoView([intro]);
  figma.closePlugin('Created '+ERP_MAP.screens.length+' editable screen frames, '+wired+' direct control links and '+overlayCount+' explanatory overlays. Review source conditions before using as a runtime specification.');
})().catch(error=>figma.closePlugin('Import stopped: '+String(error)));
