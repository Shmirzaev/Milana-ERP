for(const style of ['Regular','Medium','Semi Bold'])await figma.loadFontAsync({family:'Inter',style});
const p=await figma.getNodeByIdAsync('2:2');let fixed=0,totals=0;
for(const n of p.findAll(n=>n.type==='FRAME'&&n.layoutMode==='HORIZONTAL')){
 if(n.counterAxisSizingMode==='FIXED'&&n.primaryAxisSizingMode==='AUTO'){n.primaryAxisSizingMode='FIXED';n.counterAxisSizingMode='AUTO';fixed++;}
}
for(const records of p.findAll(n=>n.type==='FRAME'&&n.name==='Records')){
 const header=records.children.find(n=>n.name==='Table header');if(!header)continue;
 const cols=header.children.filter(n=>n.type==='TEXT').map(n=>n.characters.toLowerCase());
 const a=cols.indexOf('planned'),b=cols.indexOf('completed'),c=cols.indexOf('remaining');
 if(a>=0&&b>=0&&c>=0)for(const row of records.children.filter(n=>/^Record \d+$/.test(n.name))){const cells=row.children.filter(n=>n.type==='TEXT');const planned=Number(cells[a].characters.replace(/,/g,'')),remaining=Number(cells[c].characters.replace(/,/g,''));if(Number.isFinite(planned)&&Number.isFinite(remaining)){cells[b].characters=(planned-remaining).toLocaleString('en-US');totals++;}}
}
const overlaps=[];
for(const f of p.children.filter(n=>/^[PV]\d{3} · /.test(n.name))){
 const body=f.findOne(n=>n.type==='FRAME'&&n.name==='Page content');if(!body)continue;
 for(let i=1;i<body.children.length;i++){const a=body.children[i-1],b=body.children[i];if(a.y+a.height>b.y+1)overlaps.push({screen:f.name,first:a.name,second:b.name});}
}
print(JSON.stringify({kind:'layout-fix',fixed,totals,overlaps}));
