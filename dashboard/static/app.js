const $ = (s) => document.querySelector(s);
let cases = [], selectedCase = null, selectedNode = null, view = 'graph';
const svgNS = 'http://www.w3.org/2000/svg';

function label(item, kind) {
  if (kind === 'identifier') return item.value;
  if (kind === 'scan') return `${item.tool} · ${item.scope === 'recursive' ? 'recursive' : item.status}`;
  return item.site || item.url;
}
function items(c) {
  return [
    ...c.identifiers.map(item => ({...item, kind:'identifier'})),
    ...c.scans.map(item => ({...item, kind:'scan'})),
    ...c.accounts.map(item => ({...item, kind:'account'})),
  ];
}
function caseName(c) { return c.identifiers[0]?.value || c.id; }
function visibleCase(c) {
  if ($('#recursive').checked) return c;
  const scans=c.scans.filter(s=>s.scope!=='recursive'), visible=new Set(scans.map(s=>s.id));
  const relationships=c.relationships.filter(r=>visible.has(r.source));
  const allReferenced=new Set([...c.scans.map(s=>s.target),...c.relationships.map(r=>r.target)]);
  const shown=new Set([...scans.map(s=>s.target),...relationships.map(r=>r.target)]);
  return {...c,scans,relationships,
    identifiers:c.identifiers.filter(i=>shown.has(i.id)||!allReferenced.has(i.id)),
    accounts:c.accounts.filter(a=>shown.has(a.id)).map(a=>({...a,observations:(a.observations || []).filter(o=>visible.has(o.scan_id))}))};
}
function button(text, callback, className = '') {
  const b = document.createElement('button'); b.textContent = text; b.className = className; b.addEventListener('click', callback); return b;
}
function text(tag, value, className = '') {
  const e = document.createElement(tag); e.textContent = value; e.className = className; return e;
}
function renderCases() {
  $('#case-count').textContent = cases.length;
  const nav = $('#cases'); nav.replaceChildren();
  for (const c of cases) {
    const b = button('', () => { selectedCase = c.id; selectedNode = null; render(); }, `case-button${selectedCase === c.id ? ' active' : ''}`);
    b.append(text('strong', caseName(c)), text('small', new Date(c.created_at).toLocaleString())); nav.append(b);
  }
}
function render() {
  renderCases();
  const selected = cases.find(item => item.id === selectedCase);
  const c = selected && visibleCase(selected);
  $('#empty').hidden = !!c; $('#content').hidden = !c;
  if (!c) { $('#title').textContent = 'Your cases'; return; }
  $('#title').textContent = caseName(c); $('#subtitle').textContent = `Case ${c.id} · ${new Date(c.created_at).toLocaleString()}`;
  const stats = $('#stats'); stats.replaceChildren();
  for (const [name, count] of [['Identifiers',c.identifiers.length],['Searches',c.scans.length],['Accounts',c.accounts.length],['Reported links',c.relationships.length]]) {
    const box = document.createElement('div'); box.className = 'stat'; box.append(text('small',name),text('strong',String(count))); stats.append(box);
  }
  renderIntake(c);
  const direct = c.scans.filter(s => !s.parent_scan);
  const counts = new Map();
  for (const scan of direct) counts.set(scan.status, (counts.get(scan.status) || 0) + 1);
  const parseFailures = direct.filter(s => s.parse_status === 'failed').length;
  $('#scan-progress').textContent = [...counts].map(([state, count]) => `${count} ${state.replaceAll('_', ' ')}`).join(' · ')
    + (parseFailures ? ` · ${parseFailures} output(s) need parsing; original evidence is saved` : '');
  $('#graph-view').hidden = view !== 'graph'; $('#list-view').hidden = view !== 'list';
  document.querySelectorAll('.tab').forEach(b => { b.classList.toggle('active', b.dataset.view === view); b.setAttribute('aria-selected', String(b.dataset.view === view)); });
  renderGraph(c); renderList(c); renderDetail(c);
}
function renderIntake(c) {
  const panel = $('#case-intake'); panel.replaceChildren(); panel.hidden = !c.people?.length;
  if (panel.hidden) return;
  panel.append(text('h2', 'People and supplied information'));
  for (const person of c.people) {
    const group = document.createElement('div'); group.className = 'observation';
    group.append(text('h3', person.name));
    for (const input of person.inputs) {
      const description = `${input.type}: ${input.value}${input.source ? ` · Source: ${input.source}` : ''}${input.notes ? ` · ${input.notes}` : ''}`;
      group.append(button(description, () => { selectedNode = input.identifier_id; renderGraph(c); renderDetail(c); }));
    }
    panel.append(group);
  }
  for (const relation of c.person_relationships || []) {
    const from = c.people.find(p => p.id === relation.from), to = c.people.find(p => p.id === relation.to);
    if (from && to) panel.append(text('p', `${from.name} · ${relation.label} · ${to.name} (user supplied)`));
  }
  const supplied = new Map();
  for (const person of c.people) for (const input of person.inputs) {
    const owners = supplied.get(input.identifier_id) || []; owners.push(person.name); supplied.set(input.identifier_id, owners);
  }
  const matches = c.relationships.filter(r => r.label === 'mentioned in output' && supplied.has(r.target));
  if (matches.length) {
    panel.append(text('h3', 'Supplied identifiers mentioned in search output'));
    panel.append(text('p', 'Possible connections only; review the original evidence.'));
    for (const match of matches) {
      const scan = c.scans.find(s => s.id === match.source), identifier = c.identifiers.find(i => i.id === match.target);
      if (!scan || !identifier || scan.target === identifier.id) continue;
      const searched = c.identifiers.find(i => i.id === scan.target);
      panel.append(button(`${identifier.value} (${supplied.get(match.target).join(', ')}) mentioned in ${scan.tool} search for ${searched?.value || 'unknown'} · view evidence`, () => { selectedNode = scan.id; renderGraph(c); renderDetail(c); }));
    }
  }
  for (const person of c.people) for (const input of person.inputs.filter(i => i.type === 'profile')) {
    for (const account of c.accounts.filter(a => a.url === input.value)) {
      panel.append(button(`Supplied profile for ${person.name} matches a reported account · ${account.url} · view sources`, () => { selectedNode = account.id; renderGraph(c); renderDetail(c); }));
    }
  }
}
function edges(c) {
  return [...c.scans.map(s => ({source:s.target,target:s.id,label:'searched with',scan:s.id})),
    ...c.scans.filter(s => s.parent_scan).map(s => ({source:s.parent_scan,target:s.id,label:'recursive search',scan:s.id})),
    ...c.relationships.map(r => ({...r,scan:r.source}))];
}
function renderGraph(c) {
  const graph = $('#graph'); graph.replaceChildren();
  const all = items(c), groups = ['identifier','scan','account'].map(kind => all.filter(i => i.kind === kind));
  const height = Math.max(280, ...groups.map(group => group.length * 72 + 55));
  const svg = document.createElementNS(svgNS,'svg'); svg.setAttribute('viewBox',`0 0 900 ${height}`); svg.setAttribute('role','img'); svg.setAttribute('aria-label','Relationship map: select a node to inspect evidence');
  const positions = new Map();
  groups.forEach((group, column) => group.forEach((item, index) => positions.set(item.id, {x:30+column*300,y:32+index*72})));
  for (const edge of edges(c)) {
    const a=positions.get(edge.source), b=positions.get(edge.target); if (!a || !b) continue;
    if (a.x === b.x) {
      const path=document.createElementNS(svgNS,'path');path.setAttribute('d',`M ${a.x+240} ${a.y+24} C ${a.x+275} ${a.y+24}, ${b.x+275} ${b.y+24}, ${b.x+240} ${b.y+24}`);path.setAttribute('fill','none');path.setAttribute('stroke','#c7d3e2');path.setAttribute('stroke-width','1.5');svg.append(path);
    } else {
      const line=document.createElementNS(svgNS,'line'); line.setAttribute('x1',a.x+(a.x<b.x?240:0));line.setAttribute('y1',a.y+24);line.setAttribute('x2',b.x+(a.x<b.x?0:240));line.setAttribute('y2',b.y+24); svg.append(line);
    }
  }
  for (const item of all) {
    const p=positions.get(item.id), g=document.createElementNS(svgNS,'g'); g.classList.add('node'); if (selectedNode===item.id) g.classList.add('selected');
    g.setAttribute('transform',`translate(${p.x},${p.y})`); g.setAttribute('tabindex','0'); g.setAttribute('role','button'); g.setAttribute('aria-label',`${item.kind}: ${label(item,item.kind)}`);
    const rect=document.createElementNS(svgNS,'rect'); rect.setAttribute('width','240');rect.setAttribute('height','48');rect.setAttribute('rx','9');
    const circle=document.createElementNS(svgNS,'circle');circle.setAttribute('cx','16');circle.setAttribute('cy','24');circle.setAttribute('r','5');circle.setAttribute('fill',({identifier:'#397df0',scan:'#8f68d8',account:'#32ad8a'})[item.kind]);
    const name=document.createElementNS(svgNS,'text');name.setAttribute('x','29');name.setAttribute('y','21');const l=label(item,item.kind);name.textContent=l.length>28?l.slice(0,27)+'…':l;
    const type=document.createElementNS(svgNS,'text');type.setAttribute('x','29');type.setAttribute('y','37');type.setAttribute('class','node-type');type.textContent=item.kind === 'identifier' ? item.type : item.kind;
    const select=()=>{selectedNode=item.id;renderGraph(c);renderDetail(c);};g.addEventListener('click',select);g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}});g.append(rect,circle,name,type);svg.append(g);
  }
  graph.append(svg);
}
function renderList(c) {
  const target=$('#findings'); target.replaceChildren(); const query=$('#search').value.toLowerCase();
  for(const item of items(c).filter(i=>`${label(i,i.kind)} ${i.kind} ${i.type||''}`.toLowerCase().includes(query))) {
    const b=button('',()=>{selectedNode=item.id;renderDetail(c);},'finding');
    if(item.kind==='account'){const image=profileImage(item);if(image){image.classList.add('finding-image');b.append(image);}}
    b.append(text('strong',label(item,item.kind)),text('small',item.type||item.kind));target.append(b);
  }
  if(!target.childNodes.length) target.append(text('p','No matching findings.','footnote'));
}
function profileImage(account) {
  for (const observation of account.observations || []) {
    try {
      const url = new URL(observation.fields.image);
      const host = url.hostname.toLowerCase();
      if (url.protocol !== 'https:' || url.username || url.password || host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || host.includes(':') || /^(127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2[0-9]|3[01])\.|0\.)/.test(host)) continue;
      const img = document.createElement('img'); img.src = url.href; img.alt = `Profile image reported for ${account.site}`; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer'; img.addEventListener('error', () => img.remove()); return img;
    } catch {}
  }
  return null;
}
function renderDetail(c) {
  const detail=$('#detail'), all=items(c), item=all.find(i=>i.id===selectedNode); if(!item) { detail.replaceChildren(text('h2','Explore a finding'),text('p','Select an item in the map or list to see its connections and evidence.')); return; }
  detail.replaceChildren(text('div',item.kind==='identifier'?item.type:item.kind,'meta'),text('h2',label(item,item.kind)));
  if(item.kind==='scan') {
    const target=all.find(i=>i.id===item.target);
    detail.append(text('p',`${item.scope === 'recursive' ? 'Recursive search' : 'Direct search'} for ${target?.value || 'unknown identifier'} · ${item.status}. Evidence is the original tool output.`));
    if(item.error) detail.append(text('p',item.error));
    if(item.parse_status === 'failed') detail.append(text('p',`Output saved; parsing failed: ${item.parse_error || 'Unknown format'}`));
    if(['failed','timed_out','interrupted'].includes(item.status)) detail.append(text('p','Findings from this attempt may be incomplete.'));
    if(item.started_at) detail.append(text('p',`Started: ${new Date(item.started_at).toLocaleString()}${item.finished_at ? ` · Finished: ${new Date(item.finished_at).toLocaleString()}` : ''}`));
    if(item.tool_version) detail.append(text('p',`Tool revision: ${item.tool_version} · Parser: ${item.parser_version || 'not run'}`,'meta'));
    for(const [filename, title] of [[item.output,'Show original output'],[item.structured_output,'Show structured report']]) {
      if(!filename || item.status === 'pending') continue;
      const b=button(title,async()=>{b.disabled=true;try{const response=await fetch(`/api/cases/${encodeURIComponent(c.id)}/evidence/${encodeURIComponent(filename)}`);if(!response.ok)throw new Error();const pre=document.createElement('pre');pre.textContent=await response.text();detail.append(pre);b.remove();}catch{b.disabled=false;detail.append(text('p','Output is not available yet. Try again after the scan starts.'));}});detail.append(b);
    }
    if(item.previous_attempt) detail.append(button('View previous attempt',()=>{selectedNode=item.previous_attempt;renderGraph(c);renderDetail(c);}));
    if(item.checks?.length){const group=document.createElement('div');group.className='observation';group.append(text('h3','Site checks'));const list=document.createElement('dl');list.className='profile-fields';for(const check of item.checks){list.append(text('dt',check.site),text('dd',check.status));}group.append(list);detail.append(group);}
  }
  if(item.kind==='account') {
    detail.append(text('p','Reported account · Treat as a lead until verified.'));
    const image=profileImage(item);if(image){image.classList.add('profile-image');detail.append(image);}
    try { const u=new URL(item.url); if(['http:','https:'].includes(u.protocol)){const a=text('a',item.url);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';detail.append(a);} } catch {}
    for(const observation of (item.observations || []).filter(o=>all.some(s=>s.id===o.scan_id))) {
      const source=all.find(i=>i.id===observation.scan_id); const group=document.createElement('div');group.className='observation';
      const searched=source && all.find(i=>i.id===source.target);
      group.append(text('h3',`Reported by ${source?.tool || 'scan'}${searched ? ` · ${searched.value}` : ''}${source?.scope === 'recursive' ? ' (recursive search)' : ''}`));
      const list=document.createElement('dl');list.className='profile-fields';
      for(const [key,value] of Object.entries(observation.fields || {})){if(key==='image'||key==='image_bg'||key==='snapcode_image')continue;list.append(text('dt',key.replaceAll('_',' ')),text('dd',String(value)));}
      if(list.childNodes.length)group.append(list);
      if(source)group.append(button('View source scan',()=>{selectedNode=source.id;renderGraph(c);renderDetail(c);}));detail.append(group);
    }
  }
  const related=edges(c).filter(e=>e.source===item.id||e.target===item.id);
  if(related.length){detail.append(text('p','Connected findings'));for(const edge of related){const other=all.find(i=>i.id===(edge.source===item.id?edge.target:edge.source));if(other) detail.append(button(`${edge.label} · ${label(other,other.kind)}`,()=>{selectedNode=other.id;renderGraph(c);renderDetail(c);}));}}
}
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{view=b.dataset.view;render();}));
$('#search').addEventListener('input',()=>{const c=cases.find(item=>item.id===selectedCase);if(c)renderList(visibleCase(c));});
$('#recursive').addEventListener('change',()=>render());
async function refresh(){try{const response=await fetch('/api/cases');if(!response.ok)throw new Error();const next=await response.json();if(JSON.stringify(next)===JSON.stringify(cases))return;cases=next;if(selectedCase&&!cases.some(c=>c.id===selectedCase))selectedCase=null;render();}catch{$('#subtitle').textContent='Unable to read the workspace. Retrying…';}}
refresh();setInterval(refresh,10000);
