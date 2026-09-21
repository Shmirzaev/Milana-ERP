// Structural dry run, not a replacement for executing the plugin in Figma.
const fs=require('fs'),path=require('path'),vm=require('vm');
const dir=path.resolve(__dirname,'..');let count=0;const nodes=new Map(),issues=[];
class Node {constructor(type){this.type=type;this.id=String(++count);this.children=[];this.width=100;this.height=100;this.x=0;this.y=0;this.fontSize=16;this._chars='';nodes.set(this.id,this);for(const p of ['overlayPositionType','overlayBackground','overlayBackgroundInteraction'])Object.defineProperty(this,p,{get(){return undefined;},set(){throw Error('Read-only property '+p);}});}
 appendChild(n){if(n.parent){n.parent.children=n.parent.children.filter(c=>c!==n);}n.parent=this;this.children.push(n);}
 resize(w,h){if(!(w>0&&h>0))throw Error('Invalid size');this.width=w;this.height=h;if(this.type==='TEXT'&&this.textAutoResize==='HEIGHT')this.measure();}
 set characters(s){this._chars=s;if(this.textAutoResize==='HEIGHT')this.measure();}get characters(){return this._chars;}
 measure(){const limit=Math.max(1,Math.floor(this.width/(this.fontSize*.55)));this.height=this._chars.split('\n').reduce((n,l)=>n+Math.max(1,Math.ceil(l.length/limit)),0)*this.fontSize*1.25;}
 setPluginData(){}
 async setReactionsAsync(r){for(const reaction of r){if(reaction.trigger.type!=='ON_CLICK'||!reaction.actions.length)throw Error('Invalid reaction');for(const a of reaction.actions){if(a.type==='NODE'&&!nodes.has(a.destinationId))throw Error('Missing destination');if(!['NODE','CLOSE'].includes(a.type))throw Error('Invalid action');}}this.reactions=r;}
}
let done;const finished=new Promise(r=>done=r);let message='';const figma={loadFontAsync:async()=>{},createPage:()=>new Node('PAGE'),setCurrentPageAsync:async p=>{figma.currentPage=p;},createFrame:()=>new Node('FRAME'),createText:()=>new Node('TEXT'),viewport:{scrollAndZoomIntoView(){}},closePlugin:s=>{message=s;done();}};
vm.runInNewContext(fs.readFileSync(path.join(dir,'figma/code.js'),'utf8'),{figma,console});
finished.then(()=>{if(message.startsWith('Import stopped'))issues.push(message);for(const n of nodes.values()){if(n.type==='FRAME')for(const c of n.children)if(c.x<0||c.y<0||c.x+c.width>n.width+1||c.y+c.height>n.height+1)issues.push('Overflow '+n.name+' / '+c.name);}
 const result={nodes:nodes.size,frames:[...nodes.values()].filter(n=>n.type==='FRAME').length,reactions:[...nodes.values()].filter(n=>n.reactions).length,message,issues,limitation:'Mock validates graph, dimensions and selected read-only API properties. It does not validate actual Figma rendering, fonts, import or prototype playback.'};fs.writeFileSync(path.join(dir,'figma/structural-check.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({...result,issues:issues.slice(0,15),issueCount:issues.length}));if(issues.length)process.exitCode=1;});
