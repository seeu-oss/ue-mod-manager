"""单页界面（无框架、无构建步骤）。文案从 i18n.py 注入，切语言不刷新。"""

import json

from . import i18n


def render(lang=None):
    lang = lang if lang in i18n.T else i18n.DEFAULT_LANG
    html = TEMPLATE.replace("__I18N__", json.dumps(i18n.table(), ensure_ascii=False))
    html = html.replace("__LANGS__", json.dumps(
        [{"code": k, "name": v["_name"]} for k, v in i18n.T.items()], ensure_ascii=False))
    html = html.replace("__LANG__", lang)
    return html


TEMPLATE = r"""<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UE Mod Manager</title>
<link rel="icon" href="/favicon.ico">
<style>
:root{
  --bg:#0f1116;--panel:#171a21;--head:#1d212a;--line:#282d38;
  --txt:#e7eaf2;--dim:#8b93a5;--accent:#4c8dff;--ok:#3ecf8e;--warn:#e5b03a;--bad:#e5534b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.6 "Segoe UI","Microsoft YaHei UI",system-ui,sans-serif}
.wrap{max-width:1060px;margin:0 auto;padding:20px 20px 60px}
header{display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.logo{width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,#4c8dff,#2b5fbf);
  display:grid;place-items:center;font-weight:700;color:#0b1220;font-size:14px}
h1{font-size:18px;margin:0;font-weight:600}
.sub{color:var(--dim);font-size:12px}
.spacer{flex:1}
select,input[type=text]{background:#0b0e13;border:1px solid var(--line);color:var(--txt);
  padding:6px 10px;border-radius:8px;font-size:13px;font-family:inherit}
input[type=text]{font-family:Consolas,monospace;font-size:12px;flex:1;min-width:180px}
select:focus,input:focus{outline:none;border-color:var(--accent)}
button{background:var(--head);border:1px solid var(--line);color:var(--txt);padding:7px 14px;
  border-radius:8px;cursor:pointer;font:13px inherit;transition:.15s}
button:hover{border-color:#3a4256;background:#242a36}
button.primary{background:linear-gradient(135deg,#4c8dff,#2b6ad4);border-color:transparent;color:#08101f;font-weight:600}
button.ghost{background:transparent}
button:disabled{opacity:.45;cursor:not-allowed}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-bottom:14px;overflow:hidden}
.panel h2{font-size:12.5px;margin:0;padding:10px 16px;color:var(--dim);font-weight:500;
  border-bottom:1px solid var(--line);background:var(--head);display:flex;align-items:center;gap:8px}
.panel .body{padding:13px 16px}
.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.kv{display:flex;gap:10px;align-items:center;margin-bottom:7px;font-size:12.5px;color:var(--dim)}
.kv>span:first-child{width:60px;flex:none}
.kv b.p{font-family:Consolas,monospace;font-weight:400;font-size:12px;color:var(--dim);word-break:break-all}
table{width:100%;border-collapse:collapse;font-size:13px}
#modsBox{max-height:calc(100vh - 470px);overflow:auto}
th{text-align:left;color:var(--dim);font-weight:500;font-size:11.5px;padding:8px 12px;
  border-bottom:1px solid var(--line);background:var(--head)}
td{padding:9px 12px;border-bottom:1px solid #21252f;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr.off .name{opacity:.45}
.name{font-weight:500;word-break:break-all}
.meta{color:var(--dim);font-size:11.5px;word-break:break-all}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:20px;margin-left:6px}
.tag.dep{background:#12294a;color:#6aa9f5}
.tag.off{background:#242835;color:#7d8496}
.cf{color:#e5b03a;font-size:11.5px;margin-top:2px}
.v{font-size:11px;padding:1px 7px;border-radius:20px;display:inline-block}
.v.ok{background:#12301f;color:#54d29a}
.v.warn{background:#3a2c12;color:#e5b03a}
.v.bad,.v.unsupported{background:#331717;color:#e57373}
#docBox:empty{display:none}
.drow{display:flex;align-items:flex-start;gap:12px;padding:11px 16px;border-top:1px solid #21252f}
.drow .dtext{flex:1;min-width:0}
.dtitle{font-size:13px;font-weight:500;margin-bottom:2px}
.drow.error .dtitle{color:#e57373}
.drow.warn .dtitle{color:var(--warn)}
.drow.info .dtitle{color:var(--dim)}
.drow button{flex:none}
.src{font-size:11px;padding:1px 7px;border-radius:20px;background:#1b202b;border:1px solid var(--line);color:var(--dim);margin-left:6px}
.grow{display:flex;align-items:center;gap:9px;padding:10px 16px;border-bottom:1px solid #21252f;cursor:pointer}
.grow:last-child{border-bottom:none}
.grow:hover{background:#1b202b}
.grow.sel{background:#141a26;box-shadow:inset 3px 0 0 var(--accent)}
.gname{font-weight:500}
.grow .gpath{margin-left:auto;max-width:44%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:var(--dim);font-family:Consolas,monospace;font-size:11.5px}
.grow.dead{opacity:.5}
#unsupBox:empty{display:none}
.unsup{padding:0 16px}
.unsup summary{cursor:pointer;color:var(--dim);font-size:12px;padding:9px 0;list-style:none}
.unsup summary::-webkit-details-marker{display:none}
.unsup summary:hover{color:var(--text)}
.urow{display:flex;align-items:center;gap:9px;padding:6px 0;color:var(--dim);font-size:12.5px}
.urow .gname{font-weight:400;color:var(--dim)}
.urow .eng{font-size:11px;padding:1px 7px;border-radius:20px;background:#1b202b;border:1px solid var(--line)}
.sw{width:40px;height:22px;border-radius:20px;background:#2a2f3d;position:relative;cursor:pointer;transition:.16s}
.sw.on{background:linear-gradient(135deg,#4c8dff,#2b6ad4)}
.sw i{position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;background:#e8ebf2;transition:.16s}
.sw.on i{left:20px;background:#fff}
.empty{padding:30px;text-align:center;color:var(--dim)}
.hint{font-size:12px;color:var(--dim)}
.okmsg{color:var(--ok)}.badmsg{color:var(--bad)}.warnmsg{color:var(--warn)}
ol.order{margin:0;padding-left:22px;font-size:12.5px;font-family:Consolas,monospace;color:#aab3c6}
ol.order li{padding:1px 0}
.badge{font-size:11px;padding:2px 8px;border-radius:20px;background:#1b202b;border:1px solid var(--line);color:var(--dim)}
#dropMask{position:fixed;inset:0;background:rgba(76,141,255,.14);border:2px dashed var(--accent);
  display:none;place-items:center;z-index:99;pointer-events:none}
#dropMask.show{display:grid}
#dropMask div{background:#101622;border:1px solid var(--accent);padding:14px 22px;border-radius:12px;font-weight:600}
</style>
</head>
<body>
<div id="dropMask"><div data-t="hint.dropActive"></div></div>
<div class="wrap">
  <header>
    <div class="logo">UE</div>
    <div>
      <h1>UE Mod Manager</h1>
      <div class="sub" data-t="app.tagline"></div>
    </div>
    <div class="spacer"></div>
    <select id="langSel" onchange="setLang(this.value)"></select>
    <span class="badge" id="status">—</span>
  </header>

  <div class="panel">
    <h2><span data-t="sec.games"></span> <span class="hint" id="gameCount"></span></h2>
    <div id="gameList"><div class="empty">…</div></div>
    <div id="unsupBox"></div>
    <div class="body" style="border-top:1px solid var(--line)">
      <div class="row">
        <button onclick="scan()" data-t="btn.rescan"></button>
        <button class="primary" onclick="pickGame()" data-t="btn.pickGame"></button>
        <button class="ghost" onclick="removeGame()" data-t="btn.remove"></button>
      </div>
      <div id="paths" style="margin-top:12px"></div>
    </div>
  </div>

  <div class="panel" id="modsPanel">
    <h2><span data-t="sec.mods"></span> <span class="hint" id="modCount"></span></h2>
    <div id="modsBox"><div class="empty">…</div></div>
    <div class="body" style="border-top:1px solid var(--line)">
      <div class="row">
        <button class="primary" onclick="picker.click()" data-t="btn.addMod"></button>
        <input type="file" id="picker" accept=".zip,.pak,.utoc,.ucas" multiple hidden onchange="upload(this.files)">
        <button onclick="syncAll()" id="syncBtn" data-t="btn.sync"></button>
        <button onclick="removeAll()" data-t="btn.undoAll"></button>
        <span class="hint" id="msg" data-t="hint.drop"></span>
      </div>
    </div>
    <div class="body" style="border-top:1px solid var(--line);padding-top:9px;padding-bottom:9px">
      <span class="hint"><span data-t="hint.where"></span>
        <a href="https://www.nexusmods.com" target="_blank" rel="noopener" style="color:var(--accent)">Nexus Mods</a>
        ·
        <a href="https://mod.io" target="_blank" rel="noopener" style="color:var(--accent)">mod.io</a></span>
    </div>
  </div>

  <div class="panel" id="docPanel">
    <h2><span data-t="doc.title"></span> <span class="hint" id="docSum"></span></h2>
    <div class="body" style="padding-bottom:8px">
      <div class="row">
        <button class="primary" onclick="runDoctor()" data-t="doc.btn"></button>
        <span class="hint" id="docIdle" data-t="doc.idle"></span>
      </div>
    </div>
    <div id="docBox"></div>
  </div>

  <div class="panel">
    <h2><span data-t="sec.order"></span> <span class="hint" data-t="sec.order.hint"></span></h2>
    <div class="body"><ol class="order" id="order"><li class="hint">—</li></ol></div>
  </div>
</div>

<script>
const I18N = __I18N__;
const LANGS = __LANGS__;
let LANG = localStorage.getItem('uemm.lang') || "__LANG__";
if (!I18N[LANG]) LANG = "en";

let games = [], unsup = [], current = null, data = {};
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function t(key, params){
  const table = I18N[LANG] || I18N.en || {};
  let s = table[key];
  if (s === undefined) s = (I18N.en || {})[key];
  if (s === undefined) return key;
  if (params) for (const k in params) s = s.split('{' + k + '}').join(params[k]);
  return s;
}

function errText(j){
  if (j && j.code){
    const key = 'err.' + j.code;
    const table = I18N[LANG] || {};
    if (table[key]) return table[key];
  }
  return (j && j.error) || t('msg.failed');
}

function applyStatic(){
  document.documentElement.lang = LANG;
  document.querySelectorAll('[data-t]').forEach(el => { el.textContent = t(el.dataset.t); });
  const empty = $('modsBox').querySelector('.empty');
  if (empty) empty.textContent = t('msg.loading');
}

function setLang(lang){
  LANG = I18N[lang] ? lang : 'en';
  localStorage.setItem('uemm.lang', LANG);
  $('langSel').value = LANG;
  applyStatic();
  renderGames();
  loadState();
}

function say(text, kind){
  const m = $('msg');
  m.className = 'hint ' + (kind || '');
  m.textContent = text;
}

async function post(url, body){
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body || {})});
  try { return await r.json(); } catch(e){ return {ok:false, code:'game_not_found'}; }
}

async function loadGames(keep){
  const r = await post('/api/games', {});
  games = r.games || [];
  unsup = r.unsupported || [];
  if (keep && games.some(g => g.key === keep)) current = keep;
  else if (!games.some(g => g.key === current)) current = games.length ? games[0].key : null;

  renderGames();
  renderUnsupported();
  if (current) { await loadState(); await runDoctor(); }
  else {
    $('modsBox').innerHTML = `<div class="empty">${t('hint.noGames')}</div>`;
    $('paths').innerHTML = '';
    $('order').innerHTML = '<li class="hint">—</li>';
  }
}

const SOURCE_LABEL = {steam: 'Steam', epic: 'Epic', manual: 'Manual'};

function renderUnsupported(){
  const list = unsup;
  const box = $('unsupBox');
  if (!list.length){ box.innerHTML = ''; return; }
  box.innerHTML = `<details class="unsup">
    <summary>${esc(t('sec.unsupported', {n: list.length}))}</summary>
    <div style="padding-bottom:10px">
      <div class="hint" style="margin-bottom:6px">${esc(t('hint.unsupported'))}</div>
      ${list.map(u => `<div class="urow">
        <span class="gname">${esc(u.name)}</span>
        <span class="eng">${esc(u.engine_label)}</span>
      </div>`).join('')}
    </div>
  </details>`;
}

function renderGames(){
  $('gameCount').textContent = games.length ? `(${games.length})` : '';
  const box = $('gameList');
  if (!games.length){
    box.innerHTML = `<div class="empty">${t('hint.noGames')}<br><br>
      <button class="primary" onclick="pickGame()">${t('btn.pickGame')}</button></div>`;
    return;
  }
  box.innerHTML = games.map(g => {
    const sup = g.support || {level:'ok'};
    return `<div class="grow ${g.key === current ? 'sel' : ''} ${g.exists ? '' : 'dead'}" data-key="${esc(g.key)}">
      <span class="gname">${esc(g.name)}</span>
      <span class="src">${SOURCE_LABEL[g.source] || 'Manual'}</span>
      <span class="v ${sup.level}">${esc(t('st.' + sup.level))}</span>
      ${g.exists ? '' : `<span class="v unsupported">${t('st.broken')}</span>`}
      <span class="gpath">${esc(g.path)}</span>
    </div>`;
  }).join('');
}

$('gameList').addEventListener('click', async e => {
  const row = e.target.closest('.grow');
  if (!row || !row.dataset.key) return;
  current = row.dataset.key;
  renderGames();
  await loadState();
  await runDoctor();
});

let docIssues = [];

function resetDoctor(){
  docIssues = [];
  if (!$('docBox')) return;
  $('docBox').innerHTML = '';
  $('docSum').textContent = '';
  $('docIdle').textContent = t('doc.idle');
}

async function runDoctor(){
  if (!current) return;
  $('docIdle').textContent = t('msg.processing');
  const r = await post('/api/doctor', {key: current});
  if (r.code || r.error){ say(errText(r), 'badmsg'); resetDoctor(); return; }
  renderDoctor(r);
}

function renderDoctor(rep){
  docIssues = rep.issues || [];
  const box = $('docBox');
  if (rep.running){
    $('docSum').textContent = '';
    box.innerHTML = `<div class="body"><span class="hint" style="color:var(--warn)">${esc(t('doc.running'))}</span></div>`;
    return;
  }
  if (!docIssues.length){
    $('docSum').textContent = '';
    $('docIdle').textContent = '';
    box.innerHTML = `<div class="body"><span class="hint okmsg">${esc(t('doc.clean'))}</span></div>`;
    return;
  }
  const errs = docIssues.filter(i => i.severity === 'error').length;
  $('docSum').textContent = t('doc.summary', {e: errs, w: docIssues.length - errs});
  $('docIdle').textContent = '';
  box.innerHTML = docIssues.map((it, i) => `
    <div class="drow ${it.severity}">
      <div class="dtext">
        <div class="dtitle">${esc(t('doc.k.' + it.kind))}</div>
        <div class="hint">${esc(t('doc.k.' + it.kind + '.d', it.params))}</div>
      </div>
      ${it.fixable ? `<button class="ghost" onclick="fixIssue(${i})">${esc(t('doc.fix'))}</button>` : ''}
    </div>`).join('');
}

async function fixIssue(i){
  const it = docIssues[i];
  if (!it || !it.fix) return;
  say(t('msg.processing'));
  const r = await post('/api/doctor_fix', {key: current, fix: it.fix});
  if (r.ok){
    say(t('doc.fixed', {n: r.changed || 0}), 'okmsg');
    await loadState();
    if (r.report) renderDoctor(r.report);
  } else {
    say(errText(r), 'badmsg');
    if (r.report) renderDoctor(r.report);
  }
}

async function loadState(){
  if (!current) return;
  const r = await post('/api/state', {key: current});
  if (r.code || r.error){ say(errText(r), 'badmsg'); return; }
  data = r;
  const g = r.game;
  $('status').textContent = r.running ? t('msg.running') : t('msg.ready');
  $('status').style.color = r.running ? 'var(--warn)' : 'var(--ok)';

  const compat = data.compat || {level:'ok', notes:[]};
  const srcKey = g.staging_source === 'vortex' ? 'src.vortex'
    : (g.staging_source === 'custom' ? 'src.custom' : 'src.auto');
  $('paths').innerHTML = `
    <div class="kv"><span>${t('path.install')}</span><b class="p">${esc(g.path)}</b></div>
    <div class="kv"><span>${t('path.target')}</span><b class="p">${esc(g.mods)}</b></div>
    <div class="kv"><span>${t('path.staging')}</span><b class="p">${esc(g.staging || '')}</b>
      <span class="src">${t(srcKey)}</span></div>
    <div class="kv" style="margin-top:10px"><span>${t('path.compat')}</span>
      <span class="v ${compat.level}">${t('st.' + compat.level)}</span>
      <span class="hint">${(compat.notes || []).map(n => t('note.' + n)).join(' · ')}</span>
    </div>
    <div class="row" style="margin-top:8px">
      <button class="ghost" onclick="changeStaging()">${t('btn.changeStaging')}</button>
      <button class="ghost" onclick="openDir('staging')">${t('btn.openStaging')}</button>
      <button class="ghost" onclick="openDir('mods')">${t('btn.openMods')}</button>
    </div>` +
    (data.vortex && g.staging_source !== 'vortex' ? `
    <div class="row" style="margin-top:9px;padding-top:9px;border-top:1px solid var(--line)">
      <span class="hint">${t('vortex.found', {n: data.vortex.mods})}</span>
      <button class="primary" onclick="adoptVortex()">${t('btn.adopt')}</button>
    </div>` : '') +
    (data.vortex_archives && data.vortex_archives.length ? `
    <div class="row" style="margin-top:9px;padding-top:9px;border-top:1px solid var(--line)">
      <span class="hint">Vortex downloads: ${data.vortex_archives.length}</span>
      <button class="ghost" onclick="importVortex()">${t('btn.adopt')}</button>
    </div>` : '');

  renderMods(r.mods || []);
  renderOrder(r.order || []);
  resetDoctor();
}

function renderMods(mods){
  $('modCount').textContent = mods.length ? `(${mods.length})` : '';
  const box = $('modsBox');
  if (!mods.length){
    box.innerHTML = `<div class="empty">${t('hint.noMods')}</div>`;
    return;
  }
  box.innerHTML = `<table><thead><tr>
    <th style="width:50px">${t('col.on')}</th><th>${t('col.mod')}</th><th style="width:74px">${t('col.size')}</th>
    <th style="width:54px">${t('col.pak')}</th><th style="width:76px">${t('col.health')}</th><th style="width:86px">${t('col.state')}</th>
  </tr></thead><tbody>` + mods.map(m => `
    <tr class="${m.enabled ? '' : 'off'}">
      <td><div class="sw ${m.enabled ? 'on' : ''}" data-id="${esc(m.id)}" data-on="${m.enabled ? 0 : 1}"><i></i></div></td>
      <td><div class="name">${esc(m.id)}</div>
        ${m.conflicts && m.conflicts.length ? `<div class="cf">${m.conflicts.map(c => esc(t('cf.' + c.kind, c))).join('; ')}</div>` : ''}
      </td>
      <td class="meta">${m.size_h}</td>
      <td class="meta">${m.paks}</td>
      <td><span class="v ${m.verdict}" title="${esc(t('verdict.' + m.note_key, {n: m.valid_paks}))}">${{ok:t('st.usable'),warn:t('st.caution'),bad:t('st.invalid')}[m.verdict] || '—'}</span></td>
      <td>${m.deployed ? `<span class="tag dep">${t('st.deployed')}</span>` : `<span class="tag off">${t('st.notDeployed')}</span>`}</td>
    </tr>`).join('') + '</tbody></table>';
}

function renderOrder(order){
  const box = $('order');
  if (!order.length){ box.innerHTML = '<li class="hint">—</li>'; return; }
  box.innerHTML = order.map(o => `<li>${esc(o.pak)} <span style="color:#5d6577">— ${esc(o.mod)}</span></li>`).join('');
}

$('modsBox').addEventListener('click', async e => {
  const sw = e.target.closest('.sw');
  if (!sw || !current) return;
  const on = sw.dataset.on === '1';
  say(t('msg.processing'));
  const r = await post('/api/toggle', {key: current, id: sw.dataset.id, enabled: on});
  if (r.ok) say(on ? t('msg.toggledOn') : t('msg.toggledOff'), 'okmsg');
  else say(errText(r), 'badmsg');
  loadState();
});

async function scan(){
  say(t('msg.scanning'));
  const r = await post('/api/scan', {});
  say(t('msg.scanned', {found: r.found || 0, added: r.added || 0}), 'okmsg');
  loadGames(current);
}

async function pickGame(){
  say(t('msg.picking'));
  const r = await post('/api/pick_game', {});
  if (r.ok){ say(t('msg.picked', {name: r.name}), 'okmsg'); loadGames(r.key); return; }
  if (r.cancelled){ say(''); return; }
  if (r.code === 'no_dialog'){ addGame(); return; }
  say(errText(r), 'badmsg');
}

async function addGame(){
  const path = prompt(t('prompt.addGame'));
  if (!path) return;
  const r = await post('/api/add_game', {path});
  if (r.ok){ say(r.name, 'okmsg'); loadGames(r.key); }
  else say(errText(r), 'badmsg');
}

async function removeGame(){
  if (!current) return;
  if (!confirm(t('confirm.removeGame'))) return;
  await post('/api/remove_game', {key: current});
  current = null;
  loadGames();
}

async function adoptVortex(){
  const r = await post('/api/adopt_vortex', {key: current});
  if (r.ok) say(t('msg.adopted', {n: r.mods}), 'okmsg');
  else say(errText(r), 'badmsg');
  loadState();
}

async function importVortex(){
  const r = await post('/api/import_vortex', {key: current});
  if (r.ok) say(t('msg.installed', {ok: r.installed || 0}), 'okmsg');
  else if (r.code === 'nothing_new') say(t('msg.nothing_new', {n: r.skipped || 0}), 'okmsg');
  else say(errText(r), 'badmsg');
  loadState();
}

async function changeStaging(){
  const v = prompt(t('prompt.staging'), data.game ? data.game.staging : '');
  if (!v) return;
  const r = await post('/api/save_staging', {key: current, path: v});
  if (r.ok) say(t('msg.changedStaging'), 'okmsg');
  else say(errText(r), 'badmsg');
  loadState();
}

async function syncAll(){
  const btn = $('syncBtn');
  btn.disabled = true;
  say(t('msg.syncing'));
  const r = await post('/api/deploy', {key: current});
  btn.disabled = false;
  if (r.ok){
    const s = r.stats || {};
    say(t('msg.synced', {linked: s.linked || 0, copied: s.copied || 0}), 'okmsg');
  } else say(errText(r), 'badmsg');
  loadState();
}

async function removeAll(){
  if (!confirm(t('confirm.undoAll'))) return;
  say(t('msg.undoing'));
  const r = await post('/api/undeploy', {key: current});
  if (r.ok) say(t('msg.undone', {n: r.removed || 0}), 'okmsg');
  else say(errText(r), 'badmsg');
  loadState();
}

async function openDir(which){
  await post('/api/open', {key: current, which});
}

async function upload(files){
  if (!files || !files.length) return;
  if (!current && games.length){ current = games[0].key; renderGames(); }
  if (!current){ say(t('hint.noGames'), 'badmsg'); return; }
  let ok = 0, fail = 0, last = '';
  for (let i = 0; i < files.length; i++){
    say(t('msg.installing', {i: i + 1, n: files.length, name: files[i].name}));
    try {
      const r = await fetch('/api/install', {method:'POST',
        headers:{'X-Filename': encodeURIComponent(files[i].name), 'X-Game': current},
        body: files[i]});
      const j = await r.json();
      if (j.ok) ok++; else { fail++; last = errText(j); }
    } catch(e){ fail++; last = String(e); }
  }
  if (fail) say(t('msg.installPartial', {ok: ok, fail: fail, err: last}), 'warnmsg');
  else say(t('msg.installed', {ok: ok}), 'okmsg');
  $('picker').value = '';
  loadState();
}

let dragDepth = 0;
window.addEventListener('dragenter', e => {
  if (!e.dataTransfer || !Array.from(e.dataTransfer.types).includes('Files')) return;
  dragDepth++;
  $('dropMask').classList.add('show');
});
window.addEventListener('dragover', e => { e.preventDefault(); });
window.addEventListener('dragleave', () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $('dropMask').classList.remove('show');
});
window.addEventListener('drop', e => {
  e.preventDefault();
  dragDepth = 0;
  $('dropMask').classList.remove('show');
  if (e.dataTransfer && e.dataTransfer.files.length) upload(e.dataTransfer.files);
});

(function init(){
  $('langSel').innerHTML = LANGS.map(l =>
    `<option value="${l.code}" ${l.code === LANG ? 'selected' : ''}>${l.name}</option>`).join('');
  applyStatic();
  loadGames();
  setInterval(() => { if (!document.hidden && current) loadState(); }, 10000);
})();
</script>
</body>
</html>
"""
