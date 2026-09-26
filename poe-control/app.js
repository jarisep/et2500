// SPDX-License-Identifier: Apache-2.0
'use strict';
const $ = id => document.getElementById(id);
let state = null, selected = null, busy = false, lastRender = '', timer, looping = false;
const labels = {supplying:'Supplying power',disabled:'PoE disabled',idle:'Not supplying',unknown:'Unknown status'};
const fmt = (n, digits=1) => Number(n).toFixed(digits);
const speed = p => !p.link ? 'Link down' : p.speed_mbps ? (p.speed_mbps >= 1000 ? `${p.speed_mbps / 1000} Gbps` : `${p.speed_mbps} Mbps`) + (p.duplex === 'full' ? ' · full' : '') : 'Link up';
function tag(name, cls, text) { const e = document.createElement(name); if(cls)e.className=cls; if(text!==undefined)e.textContent=text; return e; }
function isSupplying(p) { return p.state === 'supplying' && p.power_w > 0; }
function statusText(p) { return p.state === 'supplying' && !isSupplying(p) ? 'No measured output' : labels[p.state] || 'Unknown status'; }
function svgTag(name,attrs={}) { const node=document.createElementNS('http://www.w3.org/2000/svg',name);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);return node; }
// Coordinates are in the supplied reference image's 1904 x 1312 display space.
const copperPositions=[{x:553,w:68,l:563,r:613},{x:626,w:68,l:636,r:685},{x:699,w:68,l:708,r:756},{x:773,w:68,l:780,r:830},{x:859,w:76,l:870,r:920},{x:940,w:80,l:954,r:1006}];
function panelPort(p,unavailable,sfp=false) {
  const top=p.port%2===1, col=Math.floor((p.port-(sfp?13:1))/2);
  const pos=sfp?{x:1033+col*74,w:68,l:1042+col*74}:copperPositions[col];
  const y=top?548:611, height=sfp?49:52, ledY=top?557:656;
  const active=!unavailable&&isSupplying(p), link=!unavailable&&p.link;
  const description=`Port ${p.port} · ${p.interface} · ${unavailable?'State unavailable':speed(p)}${sfp?' · SFP':` · ${statusText(p)} · ${fmt(p.power_w)} W`}`;
  const g=svgTag('g',{class:'panel-port'+(sfp?' sfp':'')+(unavailable?' unavailable':''),role:sfp?'img':'button','aria-label':description,'data-port':p.port});
  if(!sfp){g.setAttribute('tabindex',unavailable?'-1':'0');g.setAttribute('aria-disabled',String(unavailable));g.onclick=()=>{if(!unavailable)openPort(p.port);};g.onkeydown=e=>{if(!unavailable&&(e.key==='Enter'||e.key===' ')){e.preventDefault();openPort(p.port);}};}
  const title=svgTag('title');title.textContent=description;g.append(title);
  g.append(svgTag('rect',{x:pos.x,y,width:pos.w,height,rx:3,class:'port-hit'}));
  g.append(svgTag('rect',{x:pos.x+pos.w/2-12,y:y+20,width:24,height:17,rx:3,class:'port-number-bg'}));
  const number=svgTag('text',{x:pos.x+pos.w/2,y:y+32,'text-anchor':'middle',class:'port-number'});number.textContent=String(p.port).padStart(2,'0');g.append(number);
  g.append(svgTag('rect',{x:pos.l-5,y:ledY-4,width:10,height:8,rx:1.2,class:'panel-led link-led'+(link?' on':''),'data-active':String(link)}));
  if(!sfp)g.append(svgTag('rect',{x:pos.r-5,y:ledY-4,width:10,height:8,rx:1.2,class:'panel-led poe-led'+(active?' on':''),'data-active':String(active)}));
  return g;
}
function render() {
  const ports = state.ports, unavailable = state.stale || !!state.error;
  $('liveDot').className = 'dot' + (unavailable ? ' amber' : '');
  $('freshness').textContent = unavailable ? 'Waiting for fresh measurements' : 'Live · automatic refresh';
  $('error').hidden = !unavailable;
  $('error').textContent = state.error ? `${state.error}. Showing the last available measurements; controls are paused.` : 'Reading the controller. Controls become available when fresh measurements arrive.';
  $('sampleTime').textContent = state.updated_at ? 'Last sample · ' + new Date(state.updated_at*1000).toLocaleTimeString() : 'Waiting for first sample';
  if (!ports.length) return;
  const total = ports.reduce((a,p)=>a+p.power_w,0), supplying = ports.filter(isSupplying).length;
  $('watts').textContent = fmt(total); $('powered').textContent = supplying; $('links').textContent = ports.filter(p=>p.link).length;
  $('powerBar').style.width = Math.min(100,total/150*100)+'%';
  $('powerNote').textContent = '150 W reference · vendor software rating';
  const signature = JSON.stringify([ports.map(({sampled_at, ...p})=>p),state.uplinks,unavailable]);
  if(signature !== lastRender) {
    lastRender=signature;
    const cards=document.createDocumentFragment(), rack=document.createDocumentFragment();
    for (const p of ports) {
      const active=!unavailable&&isSupplying(p), card=tag('article','card'+(active?' powered':''));
      const head=tag('div','card-head'); head.append(tag('span','port-name',`Port ${String(p.port).padStart(2,'0')}`),tag('span','role '+p.role.toLowerCase(),p.role));
      const status=tag('div','state');status.append(tag('i','dot '+(active?'poe-orange':p.state==='unknown'?'amber':'grey')),tag('span','',statusText(p)));
      const read=tag('div','card-reading'), watts=tag('div','power-value',fmt(p.power_w));watts.append(tag('small','','W'));
      const electrical=tag('div','electrical');electrical.append(tag('div','',fmt(p.voltage_v)+' V'),tag('div','',fmt(p.current_ma,0)+' mA'));read.append(watts,electrical);
      const bottom=tag('div','card-bottom'), button=tag('button','manage','Manage ↗');button.type='button';button.disabled=unavailable;button.setAttribute('aria-label',`Manage port ${p.port}`);button.onclick=()=>openPort(p.port);
      bottom.append(tag('span','link-label'+(p.link?' up':''),speed(p)),button);card.append(head,status,read,bottom);cards.append(card);
      rack.append(panelPort(p,unavailable));
    }
    for(const p of state.uplinks || [])rack.append(panelPort(p,unavailable,true));
    $('ports').replaceChildren(cards);$('rack').replaceChildren(rack);
  }
  const events = state.events.map(e=> {const li=tag('li');li.append(tag('span','',e.text),tag('time','',new Date(e.time*1000).toLocaleTimeString()));return li;});
  if(events.length) $('events').replaceChildren(...events);
  if($('settings').open) updateDialog(false);
}
function openPort(port){selected=port;$('dialogMessage').textContent='';$('confirmOff').hidden=true;updateDialog(true);$('settings').showModal();}
function updateDialog(reset){
  const p=state.ports.find(p=>p.port===selected);if(!p)return;
  $('dialogTitle').textContent=`Port ${String(p.port).padStart(2,'0')}`;$('dialogRole').textContent=p.role+' CONNECTION';
  $('dialogSummary').textContent=`${statusText(p)} · ${fmt(p.power_w)} W · ${speed(p)}`;
  $('rawStatus').textContent='Controller status '+p.status_code;$('interfaceName').textContent=p.interface;
  const unavailable=state.stale||!!state.error;
  for(const id of ['enablePower','disablePower','priority','savePriority','limit','saveLimit','confirmAction']) $(id).disabled=busy||unavailable;
  $('limit').querySelector('[value="60"]').disabled=p.pairs!==4;
  $('limit').disabled=$('saveLimit').disabled=busy||unavailable||!p.pairs;
  $('limitHint').textContent=p.pairs ? `Detected ${p.pairs}-pair device. Existing legacy-detection mode is preserved.` : 'The controller cannot report a reliable power limit until a device is supplying power.';
  if(reset){$('priority').value=p.priority==='Unknown'?'Low':p.priority;$('limit').value=String([15,30,60].includes(p.limit_w)?p.limit_w:30);}
}
async function change(action,value){
  if(busy||!state||state.stale||state.error)return;
  busy=true;updateDialog(false);$('confirmOff').hidden=true;$('dialogMessage').className='dialog-message';$('dialogMessage').textContent='Sending command…';
  try{
    const response=await fetch('/api/port',{method:'POST',headers:{'Content-Type':'application/json','X-PoE-Token':state.csrf},body:JSON.stringify({port:selected,action,value}),signal:AbortSignal.timeout(20000)});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'Change failed');
    $('dialogMessage').textContent=data.message;
    await refresh();
  }catch(e){$('dialogMessage').className='dialog-message bad';$('dialogMessage').textContent=e.name==='TimeoutError'?'Response timed out. Refresh before retrying: the command may have reached the controller.':e.message;}
  finally{busy=false;updateDialog(false);}
}
async function refresh(){
  try{const r=await fetch('/api/state',{cache:'no-store',signal:AbortSignal.timeout(5000)});if(!r.ok)throw new Error('Management service unavailable');state=await r.json();render();}
  catch(e){$('error').hidden=false;$('error').textContent='Connection lost. Displayed measurements may be out of date.';$('freshness').textContent='Disconnected';$('liveDot').className='dot amber';if(state){state.stale=true;render();$('error').textContent='Connection lost. Displayed measurements may be out of date.';}}
}
$('controlForm').onsubmit=e=>e.preventDefault();
$('closeDialog').onclick=()=>{if(!busy)$('settings').close();};
$('settings').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
$('enablePower').onclick=()=>change('power','on');
$('disablePower').onclick=()=>{$('confirmText').textContent=`Turn off PoE on Port ${selected}? Any powered device on this port will shut down.`;$('confirmOff').hidden=false;$('confirmAction').focus();};
$('cancelAction').onclick=()=>{$('confirmOff').hidden=true;};
$('confirmAction').onclick=()=>change('power','off');
$('savePriority').onclick=()=>change('priority',$('priority').value);
$('saveLimit').onclick=()=>change('limit',Number($('limit').value));
async function loop(){if(looping)return;looping=true;try{await refresh();}finally{looping=false;timer=setTimeout(loop,document.hidden?15000:3000);}}
document.addEventListener('visibilitychange',()=>{if(!document.hidden){clearTimeout(timer);loop();}});
loop();
