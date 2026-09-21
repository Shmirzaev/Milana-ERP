const fs=require('fs'), path=require('path');
const dir=path.resolve(__dirname,'..');
const inv=JSON.parse(fs.readFileSync(path.join(dir,'source-inventory.json'),'utf8'));
const ts=require(process.argv[2]||'typescript');
const title=s=>s==='/'?'Dashboard':s.replace(/\?.*/,'').split('/').filter(Boolean).map(x=>x==='[id]'?'Detail':x==='[code]'?'Department':x.split('-').map(w=>w[0].toUpperCase()+w.slice(1)).join(' ')).join(' / ');
function group(r){if(/^\/(login|reset-password|presentation|image-preview|profile|settings|search)$/.test(r)||r==='/')return '01 Access and overview';if(/^\/(sales|customers|order-history)/.test(r))return '02 Sales and customers';if(/^\/(models|brands|collections)/.test(r))return '03 Models and catalog';if(/^\/(planning|production-orders|forecasting|processes|traceability)/.test(r))return '04 Planning and traceability';if(/^\/purchasing/.test(r))return '05 Purchasing';if(/^\/(inventory|fabric-scans|eco-fabric-transfers)/.test(r))return '06 Materials and inventory';if(/^\/(cutting|bundles)/.test(r))return '07 Cutting and bundles';if(/^\/(departments|work-orders)/.test(r))return '08 Department work';if(/^\/sewing/.test(r))return '09 Sewing';if(/^\/(packages|packaging)/.test(r))return '10 Packaging';if(/^\/(warehouse|finished-goods|shipments)/.test(r))return '11 Warehouse and shipment';if(/^\/(payroll|process-qr)/.test(r))return '12 Payroll';if(/^\/(hr|attendance|employees)/.test(r))return '13 HR and attendance';if(/^\/usluga/.test(r))return '14 Usluga';if(/^\/(finance|waste)/.test(r))return '15 Finance and waste';return '16 Administration';}
const routeRx=r=>new RegExp('^'+r.split('/').map(p=>/^\[/.test(p)?'[^/]+':p.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('/')+'$');
function matchRoute(p){return inv.routes.find(r=>r.route===p)||inv.routes.find(r=>routeRx(r.route).test(p));}
// Parse destination expressions; preserve template spans without regex truncation.
function candidates(raw,source){
 if(!raw)return [];
 if(raw.startsWith('/'))return [raw];
 if(raw.startsWith('imagePreviewHref('))return ['/image-preview'];
 const tree=ts.createSourceFile('destination.ts','const d = '+raw+';',ts.ScriptTarget.Latest,true);const found=[];
 function emit(n){if(ts.isStringLiteral(n)||ts.isNoSubstitutionTemplateLiteral(n)){if(n.text.startsWith('/'))found.push(n.text);}else if(ts.isTemplateExpression(n)){let s=n.head.text;for(const span of n.templateSpans){const e=span.expression.getText(tree);s+=(e==='modelPageBase'?(source.startsWith('/usluga')?'/usluga/models':'/models'):'{value}')+span.literal.text;}if(s.startsWith('/'))found.push(s);}else ts.forEachChild(n,emit);}
 emit(tree);return [...new Set(found)];
}
const screens=inv.routes.map(r=>({...r,title:title(r.route),group:group(r.route),template:r.route,variant:false}));
for(const s of inv.sidebar){if(screens.some(p=>p.route===s.destination))continue;const r=matchRoute(s.destination.split('?')[0]);if(r)screens.push({id:'V'+String(screens.filter(x=>x.variant).length+1).padStart(3,'0'),file:r.file,route:s.destination,template:r.route,title:s.label+' — '+s.destination,group:group(s.destination.split('?')[0]),variant:true});}
for(const q of ['/warehouse-stock?stock_kind=first_grade','/inventory?group=materials','/inventory?group=accessories'])if(!screens.some(p=>p.route===q)){const r=matchRoute(q.split('?')[0]);screens.push({id:'V'+String(screens.filter(x=>x.variant).length+1).padStart(3,'0'),file:r.file,route:q,template:r.route,title:title(q)+' — '+q.split('?')[1],group:group(q.split('?')[0]),variant:true});}
function target(raw,source){const values=candidates(raw,source);const result=[];for(const value of values){const exact=screens.find(s=>s.route===value);if(exact){result.push(exact.id);continue;}let p=value.split('?')[0].replace(/\{value\}$/,'{value}');let r=matchRoute(p);if(!r&&/\{value\}$/.test(p)&&!p.endsWith('/{value}'))r=matchRoute(p.replace(/\{value\}$/,''));if(r)result.push(r.id);}return [...new Set(result)];}
for(const s of screens){s.controls=inv.controls.filter(c=>c.sourceRoutes.includes(s.template)).flatMap(c=>{const cfg=c.destination==='href'?inv.configuredLinks.filter(x=>x.file===c.file):[];return cfg.length?cfg.map((x,i)=>({...c,...x,id:c.id+'-'+(i+1),targets:target(x.destination,s.template)})):[{...c,targets:target(c.destination,s.template)}];});s.permissions=inv.sidebar.filter(x=>x.destination===s.route).map(x=>x.permissions).join(' | ')||'Route and backend guards apply; see business requirements';}
const globals=inv.controls.filter(c=>!c.sourceRoutes.length).map(c=>({...c,targets:target(c.destination,'/')}));
const data={...inv,screens,globals,sidebar:inv.sidebar.map(s=>({...s,targets:target(s.destination,'/')}))};
delete data.apiCalls;
fs.mkdirSync(path.join(dir,'figma'),{recursive:true});
fs.writeFileSync(path.join(dir,'figma','map-data.json'),JSON.stringify(data,null,2)+'\n');
const runtime=fs.readFileSync(path.join(__dirname,'figma-runtime.js'),'utf8');
fs.writeFileSync(path.join(dir,'figma','code.js'),'const ERP_MAP = '+JSON.stringify(data)+';\n'+runtime);
fs.writeFileSync(path.join(dir,'figma','manifest.json'),JSON.stringify({name:'Milana ERP workflow and navigation',api:'1.0.0',main:'code.js',editorType:['figma'],documentAccess:'dynamic-page',networkAccess:{allowedDomains:['none']}},null,2)+'\n');
const xml=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function wrap(s,n=78){const words=String(s).split(/\s+/),lines=[];let l='';for(const w of words){if((l+' '+w).length>n&&l){lines.push(l);l=w;}else l+=(l?' ':'')+w;}if(l)lines.push(l);return lines;}
const groups=[...new Set(screens.map(s=>s.group))].sort();
fs.mkdirSync(path.join(dir,'figma','svg'),{recursive:true});
for(const g of groups){const pages=screens.filter(s=>s.group===g);let y=122;const shapes=[];for(const s of pages){const links=s.controls.filter(c=>c.destination);const rows=links.length?links.map(c=>`${c.id}  ${c.label}  →  ${c.targets.length?c.targets.map(id=>screens.find(p=>p.id===id).route).join(' OR '):c.destination}`):['No resolved page-opening control in this route. Local actions are in the control register.'];const lines=rows.flatMap(r=>wrap(r,100));const h=100+lines.length*24;shapes.push(`<g><rect x="32" y="${y}" width="1136" height="${h}" fill="white" stroke="#ded9ca"/><text x="54" y="${y+30}" font-size="20" font-weight="600">${xml(s.id+'  '+s.title)}</text><text x="54" y="${y+57}" font-size="16" fill="#56503f">${xml(s.route)}</text>${lines.map((l,i)=>`<text x="54" y="${y+88+i*24}" font-size="15">${xml(l)}</text>`).join('')}</g>`);y+=h+24;}
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="${y+30}" viewBox="0 0 1200 ${y+30}"><rect width="1200" height="${y+30}" fill="#f8f7f3"/><g font-family="Arial, sans-serif" fill="#14110b"><text x="32" y="48" font-size="28" font-weight="600">Milana ERP — ${xml(g)}</text><text x="32" y="82" font-size="16">Source-based navigation • Release 20260920_030043 • Dynamic destinations retain conditions</text>${shapes.join('')}</g></svg>`;
 fs.writeFileSync(path.join(dir,'figma','svg',g.replaceAll(' ','-')+'.svg'),svg);
}
const known=new Set(screens.map(s=>s.id));const errors=[];for(const s of screens)for(const c of s.controls)for(const t of c.targets)if(!known.has(t))errors.push('Missing target '+t);
for(const s of data.sidebar)if(!s.targets.length)errors.push('Unresolved sidebar '+s.destination);
const report={routeTemplates:inv.routes.length,routeFrames:screens.filter(s=>!s.variant).length,variantFrames:screens.filter(s=>s.variant).length,totalFrames:screens.length,sourceControls:inv.controls.length,controlsWithRouteOwners:inv.controls.filter(c=>c.sourceRoutes.length).length,unownedControls:globals.length,sidebarEntries:inv.sidebar.length,resolvedSidebarEntries:data.sidebar.filter(s=>s.targets.length).length,screenControlInstances:screens.reduce((n,s)=>n+s.controls.length,0),resolvedNavigationControls:screens.reduce((n,s)=>n+s.controls.filter(c=>c.targets.length).length,0),unresolvedDestinationControls:screens.flatMap(s=>s.controls.filter(c=>c.destination&&!c.targets.length).map(c=>({screen:s.id,control:c.id,destination:c.destination}))),errors,limitation:'Static AST and generated graph checks only; Figma runtime and live role coverage require actual execution.'};
fs.writeFileSync(path.join(dir,'coverage.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({...report,unresolvedDestinationControls:report.unresolvedDestinationControls.length}));
if(errors.length)process.exitCode=1;
