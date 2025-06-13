<!-- static/settops.html  —  2025-05-30 UX refresh -->
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title id="host-name">STB Manager</title>
<style>
/* ===== layout ======================================================= */
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,sans-serif;margin:0;padding:20px}
h1{margin:0 0 18px 0}
nav{margin-bottom:16px}
nav button{margin-right:6px;padding:4px 10px;font-size:.8rem;border:0;border-radius:3px;cursor:pointer;background:#5cb85c;color:#fff}
nav button:hover{background:#4cae4c}
/* scroll container (table) */
.table-wrap{max-width:100%;overflow:auto;border:1px solid #dcdcdc;border-radius:4px}

/* ===== grid table =================================================== */
table{border-collapse:separate;border-spacing:0;width:100%;min-width:1230px}
thead{position:sticky;top:0;background:#fafafa;z-index:2}
th,td{padding:6px 8px;border-bottom:1px solid #e0e0e0;font-size:.9rem}
thead th{font-weight:600;user-select:none;white-space:nowrap}
tbody tr:nth-child(even){background:#fcfcfc}
tbody tr:hover{background:#f5faff}
td[contenteditable]{cursor:text}
td:focus-visible{outline:2px solid #1a73e8;outline-offset:-2px}

/* freeze first column */
thead th:first-child,tbody td:first-child{position:sticky;left:0;background:inherit;z-index:1}

/* ===== controls ===================================================== */
.switch{position:relative;width:54px;height:24px;display:inline-block}
.switch input{opacity:0;width:0;height:0}
.slider{position:absolute;inset:0;background:#c3c3c3;border-radius:50px;transition:.3s}
.slider:before{content:"";position:absolute;height:20px;width:20px;left:2px;top:2px;border-radius:50%;background:#fff;transition:.3s}
input:checked + .slider{background:#42b72a}
input:checked + .slider:before{transform:translateX(30px)}
.slider-labels{position:absolute;inset:0;display:flex;justify-content:space-between;align-items:center;font-size:9px;color:#fff;padding:0 4px;pointer-events:none}

/* selects */
select{height:24px;font-size:.85rem}
td[data-host-cell]{min-width:140px}

/* buttons */
.btn{padding:3px 8px;border:0;border-radius:3px;font-size:.75rem;color:#fff;cursor:pointer}
.btn-del{background:#d9534f}.btn-del:hover{background:#c9302c}
.btn-pair{background:#5bc0de}.btn-pair:hover{background:#31b0d5}
.save-btn{background:#0275d8;padding:6px 12px}.save-btn:hover{background:#025aa5}

/* responsive hint */
@media(max-width:800px){
  body{padding:12px}
  h1{font-size:1.25rem}
}
</style>
</head>
<body>

<nav>
  <button onclick="location.href='/'">JAMboRemote</button>
  <button onclick="location.href='/apps'">dayJAM</button>
  <button onclick="location.href='http://10.74.139.230:9090/dpweb/'">DPWeb</button>
</nav>

<h1>STB Manager</h1>

<div class="table-wrap">
<table id="stb-table">
  <thead>
    <tr>
      <th onclick="sortTable(0)">Alias ▴▾</th>
      <th onclick="sortTable(1)">STB</th>
      <th onclick="sortTable(2)">IP</th>
      <th>Protocol</th>
      <th onclick="sortTable(4)">Remote</th>
      <th onclick="sortTable(5)">Model</th>
      <th onclick="sortTable(6)">COM</th>
      <th>Type / Host</th>
      <th style="min-width:120px">Actions</th>
    </tr>
  </thead>
  <tbody id="stb-table-body"></tbody>
</table>
</div>

<button onclick="addRow()">Add Row</button>
<button class="save-btn" onclick="saveChanges()">💾 Save</button>

<script>
const API_LIST = '/get-stb-list';
const API_SAVE = '/save-stb-list';
let   stbData     = {};
let   hopperNames = [];
let   sortAsc     = {};

/* ---------- helpers ---------- */
const qs   = s => document.querySelector(s);
const qsa  = s => [...document.querySelectorAll(s)];

/* gather hoppers from current DOM */
function collectHoppers(){
  hopperNames = qsa('#stb-table-body tr')
     .filter(tr=>tr.querySelector('select[data-k="role"]').value==='hopper')
     .map(tr=>tr.querySelector('[data-k="alias"]').innerText.trim());
  hopperNames = [...new Set(hopperNames)];
}
function makeSwitch(proto='RF'){
  return `
    <label class="switch">
      <input type="checkbox" data-k="protocol"${proto==='SGS'?' checked':''}>
      <span class="slider"></span>
      <div class="slider-labels"><span>SGS</span><span>RF</span></div>
    </label>`;
}
function makeRole(role='hopper'){
  return `
    <select data-k="role" onchange="onRoleChange(this)">
      <option value="hopper"${role==='hopper'?' selected':''}>hopper</option>
      <option value="joey"${role==='joey'?' selected':''}>joey</option>
    </select>`;
}
function makeHost(sel=''){
  const opts = hopperNames.map(h=>`<option value="${h}"${h===sel?' selected':''}>${h}</option>`).join('');
  return `<select data-k="host"${hopperNames.length?'':' style="display:none"'}>${opts}</select>`;
}
function buildRow(alias,d={}){
  const proto = d.protocol==='SGS'?'SGS':'RF';
  const tr    = document.createElement('tr');
  tr.innerHTML = `
   <td contenteditable data-k="alias">${alias}</td>
   <td contenteditable data-k="stb">${d.stb||''}</td>
   <td contenteditable data-k="ip">${d.ip||''}</td>
   <td>${makeSwitch(proto)}</td>
   <td contenteditable data-k="remote">${d.remote||''}</td>
   <td contenteditable data-k="model">${d.model||''}</td>
   <td contenteditable data-k="com_port">${d.com_port||''}</td>

   <!-- Combined Type/Host cell -->
   <td data-type-host>
     ${makeRole(d.role)}
     <span style="margin-left:8px;">${makeHost(d.host)}</span>
   </td>

   <td>
     <button class="btn btn-del" onclick="delRow(this)">Del</button>
     <input type="text" placeholder="PIN" size="4"
            onkeydown="if(event.key==='Enter')sendPin(this)">
     <button class="btn btn-pair" onclick="pairStart(this)">Pair</button>
   </td>`;
  return tr;
}

// onRoleChange: now refresh only the <td data-type-host>
function onRoleChange(sel){
  collectHoppers();
  const row = sel.closest('tr');
  const td  = row.querySelector('td[data-type-host]');
  const currentHost = td.querySelector('select[data-k="host"]')?.value || '';
  td.innerHTML = `
    ${makeRole(sel.value)}
    <span style="margin-left:8px;">${makeHost(currentHost)}</span>
  `;
}
/* ---------- table render ---------- */
function populateTable(){
  const tbody = qs('#stb-table-body');
  tbody.innerHTML='';
  hopperNames = Object.entries(stbData)
    .filter(([,d])=>(d.role||'hopper')==='hopper').map(([a])=>a);
  Object.entries(stbData).forEach(([alias,d])=>tbody.appendChild(buildRow(alias,d)));
}

function addRow(){
  collectHoppers();
  qs('#stb-table-body').appendChild(buildRow('',{}));
}
function delRow(btn){ btn.closest('tr').remove(); }

/* ---------- save ---------- */
function rowObj(tr){
  const o={};
  tr.querySelectorAll('[data-k]').forEach(el=>{
    const k=el.dataset.k;
    if(el.matches('input[type=checkbox]')) o[k]=el.checked?'SGS':'RF';
    else if(el.matches('select'))          o[k]=el.value;
    else                                   o[k]=el.innerText.trim();
  });
  return o;
}
function saveChanges(){
  const out={};
  qsa('#stb-table-body tr').forEach(tr=>{
    const d=rowObj(tr);
    if(d.alias) out[d.alias]=d;
  });
  fetch(API_SAVE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stbs:out})})
    .then(r=>r.json())
    .then(j=>alert(j.success?'Saved ✔':'Error ❌'));
}
/* ---------- sorting ---------- */
function sortTable(i){
  const tb=qs('#stb-table-body');
  const rows=[...tb.rows];
  sortAsc[i]=!sortAsc[i];
  rows.sort((a,b)=>a.cells[i].innerText.localeCompare(b.cells[i].innerText)*(sortAsc[i]?1:-1));
  rows.forEach(r=>tb.appendChild(r));
}
/* ---------- pairing helpers (unchanged) ---------- */
function pairStart(btn){
  const d=rowObj(btn.closest('tr'));
  if(!d.ip||!d.stb)return alert('Need IP & STB');
  fetch('/sgs/pair/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({alias : d.alias,stb:d.stb})})
   .then(r=>r.json()).then(j=>{
     if(j.ok){alert('PIN on TV – enter & press Enter');btn.previousElementSibling.focus();}
     else alert('pair-start failed: '+j.msg);
   });
}
function sendPin(inp){
  const pin=inp.value.trim();
  if(pin.length!==6)return alert('6-digit PIN');
  const d=rowObj(inp.closest('tr'));
  fetch('/sgs/pair/complete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip:d.ip,stb:d.stb,pin})})
    .then(r=>r.json()).then(j=>{alert(j.ok?'Paired 🎉':'Pairing failed');if(j.ok)inp.value='';});
}
/* ---------- bootstrap ---------- */
window.addEventListener('DOMContentLoaded',()=>{
  fetch('/hostname').then(r=>r.json()).then(d=>qs('#host-name').textContent=d.hostname);
  fetch(API_LIST).then(r=>r.json()).then(d=>{stbData=d.stbs||{};populateTable();});
});
</script>
</body>
</html>