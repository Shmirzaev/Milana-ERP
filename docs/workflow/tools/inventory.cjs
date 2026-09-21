/* Read-only source inventory. Usage: node inventory.cjs <typescript-lib-path> */
const fs = require('fs');
const path = require('path');
const ts = require(process.argv[2] || 'typescript');
const root = path.resolve(__dirname, '../../..');
const out = path.resolve(__dirname, '..');
const files = [];
function walk(dir) { for (const d of fs.readdirSync(dir, {withFileTypes:true})) { const p=path.join(dir,d.name); if(d.isDirectory()) walk(p); else if(/\.tsx?$/.test(p)) files.push(p); } }
walk(path.join(root,'frontend/src'));
const rel=p=>path.relative(root,p).replaceAll('\\','/');
const trees=new Map(files.map(p=>[rel(p),ts.createSourceFile(p,fs.readFileSync(p,'utf8'),ts.ScriptTarget.Latest,true, p.endsWith('tsx')?ts.ScriptKind.TSX:ts.ScriptKind.TS)]));
const dict={};
function visit(n,fn){ fn(n); ts.forEachChild(n,c=>visit(c,fn)); }
for(const [f,tree] of trees) if(/locales\/en-/.test(f)) visit(tree,n=>{if(ts.isPropertyAssignment(n)&&ts.isStringLiteral(n.name)&&ts.isStringLiteral(n.initializer)) dict[n.name.text]=n.initializer.text;});
const text=n=>n?.getText().replace(/\s+/g,' ').trim()||'';
const val=n=>!n?'':ts.isStringLiteral(n)||ts.isNoSubstitutionTemplateLiteral(n)?n.text:ts.isJsxExpression(n)?val(n.expression):text(n);
const resolveLabel=s=>s.replace(/\bt\(["']([^"']+)["']\)/g,(_,k)=>dict[k]||k).replace(/\s+/g,' ').trim();
function jsxLabel(n){
 if(ts.isJsxText(n)) return n.text.trim();
 if(ts.isJsxExpression(n)) {const e=n.expression;if(!e)return ''; if(ts.isConditionalExpression(e))return resolveLabel(text(e.whenTrue))+' / '+resolveLabel(text(e.whenFalse));const s=resolveLabel(text(e));return s.length>180?'[dynamic content]':s;}
 if(ts.isJsxElement(n)) return n.children.map(jsxLabel).filter(Boolean).join(' ');
 return '';
}
const routes=[...trees.keys()].filter(f=>/\/app\/.*page\.tsx$/.test(f)).sort().map((file,i)=>({id:`P${String(i+1).padStart(3,'0')}`,file,route:'/'+file.replace('frontend/src/app/','').replace(/\([^/]+\)\//g,'').replace(/\/?page\.tsx$/,'')}));
const fileToRoute=new Map(routes.map(r=>[r.file,r]));
const imports=new Map();
for(const [file,tree] of trees){ const deps=[];visit(tree,n=>{if((ts.isImportDeclaration(n)||ts.isExportDeclaration(n))&&n.moduleSpecifier&&ts.isStringLiteral(n.moduleSpecifier)){const s=n.moduleSpecifier.text; let base=s.startsWith('@/')?'frontend/src/'+s.slice(2):s.startsWith('.')?path.posix.normalize(path.posix.join(path.posix.dirname(file),s)):'';if(base){ const match=[base,base+'.tsx',base+'.ts',base+'/index.tsx',base+'/index.ts'].find(x=>trees.has(x));if(match)deps.push(match);}}});imports.set(file,deps);}
function depsOf(f,seen=new Set()){if(seen.has(f))return seen;seen.add(f); for(const d of imports.get(f)||[])depsOf(d,seen);return seen;}
const closure=new Map(routes.map(r=>[r.route,depsOf(r.file)]));
const globalFiles=new Set(['frontend/src/components/Sidebar.tsx','frontend/src/components/Topbar.tsx','frontend/src/components/TasksPanel.tsx','frontend/src/components/NotificationsBell.tsx']);
const controls=[],nav=[],api=[],configuredLinks=[];
for(const [file,tree] of trees){
 const funcs=new Map();visit(tree,n=>{if(ts.isFunctionDeclaration(n)&&n.name)funcs.set(n.name.text,n);if(ts.isVariableDeclaration(n)&&ts.isIdentifier(n.name)&&n.initializer&&(ts.isArrowFunction(n.initializer)||ts.isFunctionExpression(n.initializer)))funcs.set(n.name.text,n.initializer);});
 function expand(n,seen=new Set(),depth=0,targets=[]){if(!n||depth>4)return '';let s=text(n);const extra=[]; visit(n,c=>{if(ts.isCallExpression(c)&&/^(router\.(push|replace)|window\.open|window\.location\.(assign|replace))$/.test(text(c.expression)))targets.push(val(c.arguments[0]));if(ts.isBinaryExpression(c)&&c.operatorToken.kind===ts.SyntaxKind.EqualsToken&&text(c.left)==='window.location.href')targets.push(val(c.right));if(ts.isIdentifier(c)&&funcs.has(c.text)&&!seen.has(c.text)){seen.add(c.text);extra.push(expand(funcs.get(c.text),seen,depth+1,targets));}});return s+' '+extra.join(' ');}
 const owners=[...closure].filter(([,set])=>set.has(file)).map(([r])=>r);
 const line=n=>tree.getLineAndCharacterOfPosition(n.getStart()).line+1;
 visit(tree,n=>{
  if(ts.isArrayLiteralExpression(n)&&n.elements.length===2&&n.elements.every(ts.isStringLiteral)&&n.elements[1].text.startsWith('/'))configuredLinks.push({label:n.elements[0].text,destination:n.elements[1].text,file,line:line(n),sourceRoutes:owners});
  if(ts.isBinaryExpression(n)&&n.operatorToken.kind===ts.SyntaxKind.EqualsToken&&text(n.left)==='window.location.href')nav.push({file,line:line(n),sourceRoutes:owners,method:'window.location.href',destination:val(n.right)});
  if(ts.isCallExpression(n)&&/^(router\.(push|replace|back|refresh)|redirect|window\.open|window\.location\.(assign|replace))$/.test(text(n.expression))){nav.push({file,line:line(n),sourceRoutes:owners,method:text(n.expression),destination:val(n.arguments[0])||'(browser history/current route)'});}
  if(ts.isCallExpression(n)&&/^api\.(get|post|put|patch|delete)$/.test(text(n.expression))){api.push({file,line:line(n),sourceRoutes:owners,method:text(n.expression),endpoint:val(n.arguments[0])});}
  const op=ts.isJsxElement(n)?n.openingElement:ts.isJsxSelfClosingElement(n)?n:null;if(!op)return;
  const tag=text(op.tagName); const a={};for(const p of op.attributes.properties)if(ts.isJsxAttribute(p))a[text(p.name)]=p.initializer;
  if(!['button','Button','Link','a','form'].includes(tag)&&!a.onClick)return;
  let label=tag==='form'?'Form submission':resolveLabel(val(a['aria-label'])||val(a.title)||(ts.isJsxElement(n)?jsxLabel(n):''));
  if(label.length>240)label=label.slice(0,220)+' [dynamic label]';
  const handler=a.onClick||a.onSubmit; const dests=[]; const body=expand(handler,new Set(),0,dests);
  let href=val(a.href),kind='local state / inspect handler';
  if(href)kind=val(a.target)==='_blank'?'open new tab':'open page/link';
  else if(dests.length)kind='navigate after action';
  else if(/\.print\(|printHtml|printLabel|printBarcode/i.test(body))kind='print';
  else if(/download|export|saveAs|createObjectURL/.test(body))kind='download/export';
  else if(/api\.(post|put|patch|delete)\(/.test(body))kind='save/change data';
  else if(/set\w*(?:Modal|Dialog|Open)\w*\(/.test(body))kind='open/close dialog';
  else if(/set\w*(?:Tab|Filter|Search|Page|Selected|Expanded)\w*\(/.test(body))kind='filter/select/expand';
  else if(/router\.back\(/.test(body))kind='browser back';
  else if(tag==='form'||val(a.type)==='submit')kind='submit form';
  if(!label)label=tag==='form'?'Form submission':val(a.type)==='submit'?'Submit':text(handler)||`Icon control at line ${line(n)}`;
  controls.push({id:`C${String(controls.length+1).padStart(4,'0')}`,file,line:line(n),sourceRoutes:owners,global:globalFiles.has(file),tag,label,kind,destination:href||dests.join(' | '),handler:text(handler),disabled:val(a.disabled),evidence:'static source; conditional visibility and dynamic data require runtime QA'});
 });
}
const sidebar=[];for(const [file,tree] of trees)if(file.endsWith('/Sidebar.tsx'))visit(tree,n=>{if(ts.isObjectLiteralExpression(n)){const p={};for(const item of n.properties)if(ts.isPropertyAssignment(item))p[text(item.name)]=val(item.initializer);if(p.href&&p.labelKey)sidebar.push({label:dict[p.labelKey]||p.labelKey,destination:p.href,permissions:p.perms||'Additional role/factory rules',audience:p.audience||'',superOnly:p.superOnly||'',file,line:tree.getLineAndCharacterOfPosition(n.getStart()).line+1});}});
const payload={baseline:'fb3c3d582b0bda9c94cd6a951c432a7a4383820f',release:'20260920_030043',generated:'2026-09-21',method:'TypeScript AST inventory, static analysis; no live business actions executed',routes,sidebar,configuredLinks,controls,navigationCalls:nav,apiCalls:api};
fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'source-inventory.json'),JSON.stringify(payload,null,2)+'\n');
const esc=s=>String(s??'').replaceAll('|','\\|').replaceAll('\n',' ');
function csv(name,rows,keys){fs.writeFileSync(path.join(out,name),'\uFEFF'+[keys,...rows.map(r=>keys.map(k=>Array.isArray(r[k])?r[k].join(' | '):r[k]))].map(row=>row.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n'));}
csv('page-register.csv',routes,['id','route','file']);csv('button-register.csv',controls,['id','sourceRoutes','global','label','kind','destination','handler','disabled','file','line','evidence']);csv('sidebar-register.csv',sidebar,['label','destination','permissions','audience','superOnly','file','line']);
let md='# Page and button reference\n\nBaseline `'+payload.baseline+'`; production source release `'+payload.release+'`. This is a static source inventory, not a record of live clicks. Dynamic labels remain expressions when no literal label exists. One control definition may render many rows. Destination queries are significant. Classification is inferred from handlers; see source for conditional behavior.\n\n'+routes.length+' route templates; '+sidebar.length+' configured sidebar entries; '+controls.length+' control definitions; '+nav.length+' navigation calls. Shared controls may appear on several routes.\n\n## Global navigation\n\n| Label | Destination | Permission candidates |\n|---|---|---|\n'+sidebar.map(r=>`| ${esc(r.label)} | ${esc(r.destination)} | ${esc(r.permissions)} |`).join('\n')+'\n';
for(const r of routes){const rows=controls.filter(c=>c.sourceRoutes.includes(r.route));md+=`\n## ${r.id} ${r.route}\n\nSource: [page](${path.posix.relative('docs/workflow',r.file)}).\n\n| Control | Label or data expression | Effect | Destination or local handler | Evidence |\n|---|---|---|---|---|\n`+rows.map(c=>`| ${c.id} | ${esc(c.label)} | ${c.kind} | ${esc(c.destination||c.handler||'Local form behavior')} | ${esc(c.file)}:${c.line} |`).join('\n')+'\n';if(!rows.length)md+='No direct control definitions found; inspect route redirects and imported view composition.\n';}
md+='\n## Shared controls and component boundaries\n\nThe CSV and JSON retain every discovered control, including global shell, dialogs, configurable controls and components with no statically resolved route owner. A blank owner is unresolved attribution, not proof that the control is unused. The main workflow guide describes business effects; this appendix preserves exact source evidence.\n';
fs.writeFileSync(path.join(out,'PAGE_AND_BUTTON_REFERENCE.md'),md);
console.log(JSON.stringify({routes:routes.length,sidebar:sidebar.length,controls:controls.length,navigation:nav.length,apiCalls:api.length,unowned:controls.filter(c=>!c.sourceRoutes.length).length}));
