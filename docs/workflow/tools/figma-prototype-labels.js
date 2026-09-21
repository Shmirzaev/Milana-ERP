// Replace source-expression remnants with business-facing labels.
for(const style of ['Regular','Medium','Semi Bold'])await figma.loadFontAsync({family:'Inter',style});
const page=await figma.getNodeByIdAsync('2:2');
function human(s){
 s=s.replace(/\.replace\([\s\S]*$/,'').replace(/\.toLowerCase\(\)/g,'');
 if(/^<Loader|^<Refresh/.test(s))return 'Refresh';if(/^<ChevronDown/.test(s))return 'More options';if(/^<ChevronUp/.test(s))return 'Collapse';
 if(/^hrT\(/.test(s))return s.replace(/^hrT\(["']?/,'').replace(/["')]+$/,'');
 if(/stocktakeText/.test(s))return 'Stock count';if(/firstGradeText/.test(s))return 'First Grade singles';
 if(/shipmentReviewText|reviewText\.reference/.test(s))return 'Shipment reference';
 if(/lastDispatch/.test(s))return 'Dispatch PDF';if(/\.bundle_no/.test(s))return 'BD-DEMO-1201';if(/\.shipment_no/.test(s))return 'SH-DEMO-3401';
 if(/orderReference|formatOrderReference|r\.production_no/.test(s))return 'PO-DEMO-2401';
 if(/model_code|v\.variant_no/.test(s))return 'MP-2401';if(/row\.packages/.test(s))return 'PK-DEMO-8401';
 if(/file\.file_name|attachmentName/.test(s))return 'Sample document.pdf';
 if(/^Show more \(/.test(s))return 'Show more';if(/^Active Orders \(/.test(s))return 'Active orders';
 const mapped={'c.manual':'Manual entry','c.reprint':'Reprint label','c.loading':'Loading','c.cancel':'Cancel','factoriesCopy.all':'All factories','activityCopy.exportReports':'Export reports','activityCopy.reports':'Reports','deleteText.deleteShipment':'Delete shipment','manualShipmentText[lang].ship':'Create shipment','content.hero.primaryAction':'Open dashboard','content.hero.secondaryAction':'Explore workspaces','content.finalCta.primaryAction':'Open dashboard','content.finalCta.secondaryAction':'Sign in'};
 if(mapped[s])return mapped[s];
 if(/^(text\.|content\.controls\.)/.test(s)){const last=s.split('.').pop();return last.charAt(0).toUpperCase()+last.slice(1).replace(/([A-Z])/g,' $1').toLowerCase();}
 return s;
}
let changed=0;const leftovers=[];
for(const n of page.findAll(n=>n.type==='TEXT')){const next=human(n.characters);if(next!==n.characters){n.characters=next;changed++;}if(/\.replace\(|\.toLowerCase|className=|hrT\(|\b(?:row|text|content|c)\./.test(n.characters))leftovers.push({id:n.id,text:n.characters});}
print(JSON.stringify({kind:'labels',changed,leftovers}));
