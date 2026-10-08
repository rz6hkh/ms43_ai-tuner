// ms43diff web interface. Plain JS, no libraries, works offline.
// Every user-visible string goes through the T function (English text plus
// optional {params}); the
// server sends the translations for the current language (see server.py).
"use strict";

const BOOT = window.BOOT || {token: "", lang: "en", strings: {}};

function T(key, params) {
  let s = BOOT.strings[key] || key;
  if (params) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m));
  return s;
}
function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}
const $ = id => document.getElementById(id);

// ---------------------------------------------------------------- server calls
let busyCount = 0;
function busy(on, text) {
  busyCount += on ? 1 : -1;
  $("busy").hidden = busyCount <= 0;
  if (on && text) $("busyText").textContent = text;
}
async function api(name, body, busyText) {
  if (busyText) busy(true, busyText);
  try {
    const res = await fetch("/api/" + name, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Token": BOOT.token},
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({error: res.statusText}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  } finally {
    if (busyText) busy(false);
  }
}
let toastTimer = null;
function toast(html, isError) {
  const el = $("toast");
  el.innerHTML = html;
  el.className = "toast" + (isError ? " error" : "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), isError ? 12000 : 7000);
}
function fail(err) { toast(esc(err.message || err), true); }

// keep the server informed that the window is open / closed
// (a reload — e.g. after switching the language — is not a close)
let reloading = false;
// The ping also brings news from the AI (MCP): the draft changed, or it asked
// to open a screen. Localhost only, so a short interval costs nothing.
let lastEvents = null;
async function ping() {
  try {
    const r = await api("ping");
    if (r.show && r.show !== S.view) { S.view = r.show; S.maps = {}; closeDrawer(); renderSide(); renderView(); }
    else if (r.show === "logs") loadLogs();
    else if (lastEvents !== null && r.events !== lastEvents && S.view === "edits") loadEdits();
    lastEvents = r.events;
  } catch (err) { /* the window is closing */ }
}
ping();
setInterval(ping, 2000);
addEventListener("pagehide", () => {
  if (reloading) return;
  fetch("/api/bye", {method: "POST", keepalive: true,
    headers: {"Content-Type": "application/json", "X-Token": BOOT.token}, body: "{}"});
});

// ---------------------------------------------------------------- state
const S = {state: null, view: "ai", cmp: null, filter: "", chip: "all", selected: null,
           maps: {}, fw: {browse: "bin_b", cross: "bin_b", patch: "bin_b", edits: "bin_b"},
           ed: null, edConfirm: "", edLast: null,
           br: null, brq: "", brcat: "", crossTab: "cmp", cr: null, pp: null, pt: null,
           ptFilter: "all",
           wk: null, wq: "", wsel: null, wtext: null};

const NAV = [
  // the AI workflow first: connect Claude, then review what it proposes
  ["ai", "✦", T("AI assistant"), T("connect to Claude")],
  ["edits", "✎", T("Edits"), T("AI proposals → a new .bin")],
  ["logs", "∿", T("Logs"), T("TunerPro logs over the maps")],
  ["cmp", "⇄", T("Compare A and B"), T("what was changed in the tune")],
  ["browse", "⌕", T("Browse firmware"), T("search, all maps and values")],
  ["cross", "⇆", T("Different software versions"), T("compare and port edits")],
  ["patch", "✓", T("Patches"), T("which are applied")],
  ["wiki", "❡", T("Reference"), T("MS4X Wiki offline")],
];

// ---------------------------------------------------------------- sidebar
// "A · 430069_stage1": the letter plus the file name without extension
function fwName(role) {
  const f = S.state.files[role] || {};
  return (f.name || "").replace(/\.[^.]+$/, "");
}
function fwLabel(role, letter) {
  const name = fwName(role);
  return name ? `${letter} · ${name}` : letter;
}
function fileCard(role, label, emptyHint) {
  const f = S.state.files[role] || {};
  if (!f.path) {
    return `<div class="file empty" data-pick="${role}"><div class="role">${esc(label)}</div>
      <div class="name">+ ${esc(emptyHint)}</div></div>`;
  }
  let tag = "";
  if (f.tag) tag = `<span class="tag${f.ok ? " ok" : f.warning ? " bad" : ""}">${esc(f.tag)}${f.ok ? " ✓" : f.warning ? " !" : ""}</span>`;
  return `<div class="file" data-pick="${role}" title="${esc(f.path)}">
    <button class="clear" data-clear="${role}" title="${esc(T("Remove"))}">×</button>
    <div class="role">${esc(label)} ${tag}</div>
    <div class="name">${esc(f.name)}</div>
    ${f.meta ? `<div class="meta">${esc(f.meta)}</div>` : ""}
    ${f.warning ? `<div class="warn">${esc(f.warning)}</div>` : ""}
    ${f.error ? `<div class="err">${esc(f.error)}</div>` : ""}</div>`;
}
function renderSide() {
  const st = S.state;
  $("ver").textContent = "BMW MS43 · " + st.version;
  $("lblProject").textContent = T("Project");
  $("lblTodo").textContent = T("What to do");
  const other = st.files.xdf2.path || st.files.bin2.path;
  $("files").innerHTML =
    fileCard("xdf", T("XDF definition"), T("choose the .xdf file")) +
    fileCard("bin_a", T("Firmware A"), T("choose the first .bin (e.g. stock)")) +
    fileCard("bin_b", T("Firmware B"), T("choose the second .bin (e.g. tune)")) +
    `<details class="other"${other ? " open" : ""}><summary>${esc(T("Other software version (for comparing versions and porting)"))}</summary>` +
    fileCard("xdf2", T("XDF of the other version"), T("choose the .xdf file")) +
    fileCard("bin2", T("Firmware of the other version"), T("choose the .bin")) + `</details>`;
  $("nav").innerHTML = NAV.map(([v, ico, title, sub]) =>
    `<button data-v="${v}" class="${S.view === v ? "on" : ""}"><span class="ico">${ico}</span>
      <span>${esc(title)}<small>${esc(sub)}</small></span></button>`).join("");
  $("lang").innerHTML = st.langs.map(l =>
    `<option value="${l.code}"${l.code === st.lang ? " selected" : ""}>${esc(l.name)}</option>`).join("");
  $("btnLog").textContent = T("Log");
}
// results that depend on a project file are dropped when that file changes
function resetFor(role) {
  if (["xdf", "bin_a", "bin_b"].includes(role)) S.cmp = null;
  if (["xdf", "xdf2", "bin_a", "bin_b", "bin2"].includes(role)) { S.cr = null; S.pp = null; S.br = null; }
  if (role === "patchlist" || role.startsWith("bin")) S.pt = null;
  if (role === "patchlist" || role.startsWith("bin") || role.startsWith("xdf")) S.ed = null;
  S.maps = {};
}
$("files").addEventListener("click", async e => {
  const clear = e.target.closest("[data-clear]");
  try {
    if (clear) {
      e.stopPropagation();
      S.state = await api("clear", {role: clear.dataset.clear});
    } else {
      const card = e.target.closest("[data-pick]");
      if (!card) return;
      const st = await pickFile(card.dataset.pick);
      if (!st) return;
      S.state = st;
    }
    resetFor((clear || e.target.closest("[data-pick]")).dataset[clear ? "clear" : "pick"]);
    S.cmp = S.state.has_compare ? S.cmp : null;
    renderSide();
    renderView();
  } catch (err) { fail(err); }
});
// one Open dialog at a time: a double click must not queue a second, hidden one
let picking = false;
async function pickFile(role) {
  if (picking) return null;
  picking = true;
  try { return await api("pick", {role}, T("Waiting for the file…")); }
  finally { picking = false; }
}
$("nav").addEventListener("click", e => {
  const b = e.target.closest("button[data-v]");
  if (!b) return;
  S.view = b.dataset.v;
  S.maps = {};
  closeDrawer();
  renderSide();
  renderView();
});
document.addEventListener("click", e => {
  const lg = e.target.closest("[data-golog]");
  if (lg) {
    e.preventDefault();
    S.lgSel = lg.dataset.golog; S.lgV = null; S.lgRange = null; S.lgCell = null;
    if (lg.dataset.golmap) S.lgMap = {map: lg.dataset.golmap, y_channel: "", x_channel: "", filters: null, value_channel: "", compare: ""};
    S.view = "logs"; S.maps = {}; closeDrawer(); renderSide(); renderView();
    return;
  }
  const g = e.target.closest("[data-goto]");
  if (!g) return;
  e.preventDefault();
  S.view = g.dataset.goto; S.maps = {}; closeDrawer(); renderSide(); renderView();
});
$("lang").addEventListener("change", async e => {
  try {
    await api("lang", {lang: e.target.value});
    sessionStorage.setItem("ms43view", S.view);
    reloading = true;
    location.reload();
  } catch (err) { fail(err); }
});
$("btnLog").addEventListener("click", () => api("log").catch(fail));

// ---------------------------------------------------------------- views
function renderView() {
  const views = {cmp: renderCompare, ai: loadAI, browse: loadBrowse, cross: renderCross,
                 patch: renderPatches, edits: loadEdits, logs: loadLogs, wiki: loadWiki};
  return (views[S.view] || renderCompare)();
}

// ---- compare
function startScreen() {
  const f = S.state.files;
  const step = (role, text) =>
    `<div class="step${f[role].path ? " done" : ""}" data-pick="${role}">${f[role].path ? "✓" : "○"} ${esc(text)}</div>`;
  const ready = f.xdf.path && f.bin_a.path && f.bin_b.path;
  return `<h1>${esc(T("Compare A and B"))}</h1>
    <div class="sub">${esc(T("Two firmware files of the same software version, one XDF."))}</div>
    <div class="start"><h2>${esc(ready ? T("Everything is ready") : T("Choose the files"))}</h2>
      <p>${esc(ready ? T("Press the button — the comparison takes a few seconds.")
                     : T("Click a step or a card on the left to choose a file."))}</p>
      <div class="steps">${step("xdf", T("XDF definition"))}${step("bin_a", T("Firmware A"))}${step("bin_b", T("Firmware B"))}</div>
      <button class="btn primary big" id="btnRun"${ready ? "" : " disabled"}>${esc(T("Compare"))}</button></div>`;
}
function renderCompare() {
  const v = $("view");
  if (!S.cmp) {
    v.innerHTML = startScreen();
    return;
  }
  const c = S.cmp, q = S.filter.toLowerCase();
  let shown = 0, sections = "";
  for (const cat of c.categories) {
    const items = cat.items.filter(it =>
      (!q || (it.title + " " + it.name + " " + it.desc + " " + it.address + " " + cat.name).toLowerCase().includes(q)) &&
      (S.chip === "all" || (S.chip === "maps" && it.has_map) || (S.chip === "up" && it.dir === "up") ||
       (S.chip === "down" && it.dir === "down")));
    if (!items.length) continue;
    shown += items.length;
    sections += `<section class="cat"><header>${esc(cat.name)}<span>${items.length}</span></header>` +
      items.map(rowHtml).join("") + `</section>`;
  }
  if (!shown) sections = `<div class="empty-state"><b>${esc(T("Nothing found"))}</b>${esc(T("Try another word — English or Russian, a name or an address."))}</div>`;
  if (c.code_blocks.length && !q && S.chip === "all") {
    sections += `<section class="cat"><header>${esc(T("Edits outside the described parameters (code / patches)"))}<span>${c.code_blocks.length}</span></header>
      <table class="plain mono">${c.code_blocks.map(b => `<tr><td>${esc(b.range)}</td><td>${esc(T("{n} bytes", {n: b.length}))}</td>
      <td style="color:var(--muted)">${esc(T("not described in the XDF — probably a machine code edit"))}</td></tr>`).join("")}</table></section>`;
  }
  const chip = (k, label) => `<button class="chip${S.chip === k ? " on" : ""}" data-chip="${k}">${esc(label)}</button>`;
  v.innerHTML = `
    <div class="top"><div><h1>${esc(T("Compare A and B"))}</h1>
      <div class="sub">${esc(c.a)} → ${esc(c.b)} · XDF ${esc(c.xdf)}</div></div>
      <div class="actions"><button class="btn" data-export="pdf">${esc(T("Save PDF"))}</button>
        <button class="btn" data-export="csv">CSV</button>
        <button class="btn primary" data-export="html">${esc(T("Save HTML report"))}</button>
        <button class="btn" id="btnRerun" title="${esc(T("Compare again"))}">↻</button></div></div>
    ${c.warnings.map(w => `<div class="alert">${esc(w)}</div>`).join("")}
    <div class="stats">
      <div class="stat"><b>${c.stats.changed}</b><span>${esc(T("parameters changed"))}</span></div>
      <div class="stat"><b>${c.stats.identical}</b><span>${esc(T("parameters same"))}</span></div>
      <div class="stat"><b>${c.stats.bytes}</b><span>${esc(T("bytes changed"))}</span></div>
      <div class="stat"><b>${c.stats.code}</b><span>${esc(T("edits outside the XDF (code)"))}</span></div></div>
    <div class="toolbar"><div class="search"><input id="q" placeholder="${esc(T("Search: rev limit, VANOS, c_conf_cat, 0x61A8…"))}" value="${esc(S.filter)}"></div>
      ${chip("all", T("All"))}${chip("maps", T("Maps only"))}${chip("up", T("Raised"))}${chip("down", T("Lowered"))}</div>
    <div id="list">${sections}</div>`;
  for (const title of Object.keys(S.maps)) loadMap(title, S.maps[title], false);
  markSelected();
}
function rowHtml(it) {
  const open = it.title in S.maps;
  return `<div class="row" data-title="${esc(it.title)}">
    <div class="t"><code>${esc(it.title)}</code><div>${esc(it.name)}</div></div>
    <div class="val">${esc(it.a)}<span class="arrow">→</span><b>${esc(it.b)}</b>
      <small>${esc(it.kind)}${it.cells ? " · " + esc(it.cells) : ""}${it.units && !it.has_map ? " · " + esc(it.units) : ""}</small></div>
    <div class="delta ${it.dir}">${esc(it.delta)}</div>
    ${it.has_map ? `<div class="mapline"><button class="mapbtn" data-map="${esc(it.title)}">${open ? "▾ " + esc(T("hide the map")) : "▸ " + esc(T("show the map"))}</button>
      <span class="modes"${open ? "" : " hidden"}>${["delta", "a", "b"].map(m =>
        `<button data-mode="${m}" class="${(S.maps[it.title] || "delta") === m ? "on" : ""}"${m === "delta" ? "" : ` title="${esc(S.state.files[m === "a" ? "bin_a" : "bin_b"].path || "")}"`}>${esc({delta: T("difference"), a: fwLabel("bin_a", "A"), b: fwLabel("bin_b", "B")}[m])}</button>`).join("")}</span>
      <div class="mapbox"></div></div>` : ""}</div>`;
}
function markSelected() {
  document.querySelectorAll(".row").forEach(r => r.classList.toggle("sel", r.dataset.title === S.selected));
}
async function runCompare(cached) {
  try {
    S.cmp = await api("compare", {cached: !!cached}, T("Comparing…"));
    S.maps = {};
    S.state.has_compare = true;
    renderView();
  } catch (err) { fail(err); }
}
async function loadMap(title, mode, rerender = true) {
  S.maps[title] = mode;
  const row = document.querySelector(`.row[data-title="${CSS.escape(title)}"]`);
  if (!row) return;
  const box = row.querySelector(".mapbox");
  try {
    const m = await api("map", {title, mode, source: row.dataset.src || "cmp", role: row.dataset.role});
    box.innerHTML = mapHtml(m);
  } catch (err) { fail(err); }
  if (rerender) {
    row.querySelector(".mapbtn").textContent = "▾ " + T("hide the map");
    if (row.querySelector(".modes")) row.querySelector(".modes").hidden = false;
    row.querySelectorAll(".modes button").forEach(b => b.classList.toggle("on", b.dataset.mode === mode));
  }
}
function mapHtml(m) {
  const head = `<tr><th></th>${m.x.map(x => `<th>${esc(x)}</th>`).join("")}</tr>`;
  const body = m.rows.map((row, r) => `<tr><th>${esc(m.y[r])}</th>${row.map(c =>
    `<td${c.bg ? ` style="background:${c.bg};color:${c.fg}"` : ""}${c.tip ? ` title="${esc(c.tip)}"` : ""}>${esc(c.v)}${c.d ? `<i>${esc(c.d)}</i>` : ""}</td>`).join("")}</tr>`).join("");
  return `${m.caption ? `<div class="axis">${esc(m.caption)}</div>` : ""}
    <div class="mapwrap"><table class="map">${head}${body}</table></div>
    <div class="legend">${esc(m.legend_title)}: ${m.legend.map(l =>
      `<span class="c" style="background:${l.bg};color:${l.fg}">${esc(l.v)}</span>`).join("")}</div>`;
}

$("view").addEventListener("click", async e => {
  const t = e.target;
  if (t.id === "btnRun" || t.id === "btnRerun") return runCompare(false);
  const clear = t.closest("[data-clear]");
  const pick = t.closest("[data-pick]");
  if (clear || pick) {
    const role = (clear || pick).dataset[clear ? "clear" : "pick"];
    try {
      const st = clear ? await api("clear", {role}) : await pickFile(role);
      if (!st) return;
      S.state = st;
      resetFor(role);
      renderSide(); renderView();
    } catch (err) { fail(err); }
    return;
  }
  const exp = t.closest("[data-export]");
  if (exp) return exportReport(exp.dataset.export);
  const chip = t.closest("[data-chip]");
  if (chip) { S.chip = chip.dataset.chip; return renderCompare(); }
  const fw = t.closest("[data-fw]");
  if (fw) {
    S.fw[fw.dataset.fwkey] = fw.dataset.fw;
    if (fw.dataset.fwkey === "cross") S.cr = null;
    if (fw.dataset.fwkey === "patch") S.pt = null;
    if (fw.dataset.fwkey === "edits") S.ed = null;
    S.maps = {};
    closeDrawer();
    return renderView();
  }
  const mapBtn = t.closest("[data-map]");
  if (mapBtn) {
    const title = mapBtn.dataset.map;
    if (title in S.maps) {
      delete S.maps[title];
      const row = mapBtn.closest(".row");
      row.querySelector(".mapbox").innerHTML = "";
      if (row.querySelector(".modes")) row.querySelector(".modes").hidden = true;
      mapBtn.textContent = "▸ " + T("show the map");
    } else {
      loadMap(title, mapBtn.closest(".row").dataset.src === "read" ? "a" : "delta");
    }
    return;
  }
  const mode = t.closest("[data-mode]");
  if (mode) return loadMap(mode.closest(".row").dataset.title, mode.dataset.mode);
  if (t.closest(".mapline") || t.closest("[data-noopen]")) return;
  const row = t.closest(".row[data-title]");
  if (row) openParam(row.dataset.title, {source: row.dataset.src === "edit" ? "read" : (row.dataset.src || "cmp"),
                                         role: row.dataset.role});
});
$("view").addEventListener("input", e => {
  if (e.target.id !== "q") return;
  S.filter = e.target.value;
  const pos = e.target.selectionStart;
  renderCompare();
  const q = $("q");
  q.focus();
  q.setSelectionRange(pos, pos);
});

async function exportReport(kind) {
  try {
    const r = await api("export", {kind}, T("Saving…"));
    if (!r.path) return;
    toast(`${esc(T("Saved: {path}", {path: r.path}))} <button id="btnOpen">${esc(T("Open"))}</button>`);
    $("btnOpen").onclick = () => api("open", {path: r.path}).catch(fail);
  } catch (err) { fail(err); }
}

// ---------------------------------------------------------------- AI assistant
async function loadAI() {
  if (!S.ai) $("view").innerHTML = `<h1>${esc(T("AI assistant"))}</h1>`;
  try { S.ai = await api("ai_state"); renderAI(); } catch (err) { fail(err); }
}
function roleOptions(selected) {
  const f = S.state.files;
  const opt = (role, label) => {
    const file = f[role] && f[role].name ? f[role].name : T("not chosen");
    return `<option value="${role}"${role === selected ? " selected" : ""}>${esc(label)} — ${esc(file)}</option>`;
  };
  return opt("bin_a", T("Firmware A")) + opt("bin_b", T("Firmware B")) +
         opt("bin2", T("Firmware of the other version"));
}
function langOptions(selected) {
  return S.state.langs.map(l => `<option value="${l.code}"${l.code === selected ? " selected" : ""}>${esc(l.name)}</option>`).join("");
}
function checkHtml(c) {
  if (!c) return "";
  return c.ok
    ? `<div class="check ok">✓ ${esc(T("The server answers: {n} tools.", {n: c.tools}))}<pre>${esc(c.info)}</pre></div>`
    : `<div class="check bad">✗ ${esc(T("The server does not answer properly."))}<pre>${esc(c.error)}</pre></div>`;
}
function serverCard(sv) {
  const state = sv.running
    ? `<span class="pill on">● ${esc(T("running"))}</span><span class="muted">${esc(T("{n} requests", {n: sv.requests}))}</span>`
    : `<span class="pill">○ ${esc(T("stopped"))}</span>`;
  const code = sv.registered
    ? `<span class="pill ok">✓ ${esc(T("connected to Claude Code"))}</span>` +
      (sv.registered_other ? `<span class="warn">${esc(T("Claude Code has another address for this name — connect again."))}</span>` : "")
    : `<span class="pill">${esc(T("not connected to Claude Code"))}</span>`;
  return `<div class="srv" data-srv="${esc(sv.name)}">
    <div class="srv-top"><input class="srv-name mono" data-field="name" value="${esc(sv.name)}" aria-label="${esc(T("Server name"))}"${sv.running ? " disabled" : ""}>
      ${state}<span class="grow"></span>
      <button class="btn${sv.running ? "" : " primary"}" data-ai="${sv.running ? "ai_stop" : "ai_start"}"${sv.ready || sv.running ? "" : " disabled"}>${esc(sv.running ? T("Stop") : T("Start"))}</button>
      <button class="btn" data-ai="ai_check"${sv.running ? "" : " disabled"}>${esc(T("Check"))}</button>
      <button class="btn icon" data-ai="ai_remove" title="${esc(T("Remove the server"))}">×</button></div>
    <div class="srv-grid">
      <label>${esc(T("Firmware the AI sees"))}<select data-field="role">${roleOptions(sv.role)}</select></label>
      <label>${esc(T("Answer language"))}<select data-field="lang">${langOptions(sv.lang)}</select></label>
      <label>${esc(T("Port"))}<input data-field="port" type="number" min="1024" max="65535" value="${sv.port}"${sv.running ? " disabled" : ""}></label>
    </div>
    ${sv.ready ? "" : `<div class="warn">${esc(T("Choose the XDF and this firmware in the project on the left."))}</div>`}
    <div class="srv-code">${code}<span class="grow"></span>
      ${S.ai.claude_cli ? `<button class="btn" data-ai="ai_code" data-register="${sv.registered ? "" : "1"}">${esc(sv.registered ? T("Disconnect from Claude Code") : T("Connect to Claude Code"))}</button>` : ""}</div>
    <div class="cmd"><code>${esc(sv.command)}</code><button class="btn" data-copy="${esc(sv.command)}">${esc(T("Copy"))}</button></div>
    ${S.ai.claude_cli ? "" : `<div class="muted small">${esc(T("Run this command once in the Claude Code terminal. Keep the token private."))}</div>`}
    ${checkHtml((S.aiChecks || {})["code:" + sv.name])}
  </div>`;
}
function renderAI() {
  const a = S.ai;
  const questions = [T("What is my rev limit, and is it higher than stock?"),
    T("Show the ignition map ip_iga_ron98_pl__n__maf."),
    T("What does c_conf_cat = 4 mean, and what breaks if I change it?"),
    T("I am removing the catalysts — what do I change and what matters?")];
  $("view").innerHTML = `<h1>${esc(T("AI assistant"))}</h1>
    <div class="sub">${esc(T("Let Claude read your firmware and the MS4X Wiki, answer questions and propose changes. Proposals go to the Edits screen; only you create the new .bin there."))}</div>
    ${a.wiki && a.wiki_missing ? `<div class="alert">${esc(T("The MS4X Wiki reference is incomplete: {n} page(s) missing.", {n: a.wiki_missing}))} <a href="#" data-goto="wiki">${esc(T("Load it on the Reference screen"))}</a></div>` : ""}
    ${a.wiki ? "" : `<div class="alert">${esc(T("The MS4X Wiki reference is not loaded: the AI assistant cannot check what parameters do and has to mark such statements as unverified."))} <a href="#" data-goto="wiki">${esc(T("Load it on the Reference screen"))}</a></div>`}
    <section class="panel"><header><b>${esc(T("Claude Code — live server"))}</b>
      <span class="muted">${esc(T("Runs while this window is open. Choosing another file in the project takes effect at once, no restart of Claude Code needed."))}</span></header>
      ${a.servers.map(serverCard).join("")}
      <button class="btn" data-ai-add="1">+ ${esc(T("Add a server"))}</button>
      <span class="muted small">${esc(T("Several servers can run at once, e.g. one for the stock and one for the tune."))}</span>
    </section>
    ${projectPanel(a)}
    ${carPanel(a)}
    <section class="panel"><header><b>${esc(T("What to ask"))}</b></header>
      ${questions.map(q => `<div class="note">${esc(q)}</div>`).join("")}</section>`;
}
function projectPanel(a) {
  const p = a.project, folder = S.projFolder !== undefined ? S.projFolder : p.folder;
  const res = S.projResult;
  return `<section class="panel"><header><b>${esc(T("Project for Claude Code"))}</b>
      <span class="muted">${esc(T("A folder Claude Code works in: rules (CLAUDE.md), tuning skills, the connection to this window, logs/ and analysis/. Python with pandas and charts comes with the program."))}</span></header>
    <div class="srv"><div class="srv-grid">
      <label>${esc(T("Folder"))}<input id="projFolder" class="mono" value="${esc(folder)}" placeholder="C:\\Tuning\\M54"></label>
      <label>${esc(T("Name"))}<input id="projName" value="${esc(S.projName !== undefined ? S.projName : p.name)}" placeholder="M54B30 X001"></label>
      <label>${esc(T("Server"))}<select id="projServer">${a.servers.map(s => `<option${s.name === p.server ? " selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
    </div>
    <div class="srv-code"><button class="btn" id="btnProjPick">${esc(T("Choose a folder…"))}</button><span class="grow"></span>
      <button class="btn primary" id="btnProjMake">${esc(p.exists ? T("Update the project") : T("Create the project"))}</button>
      ${a.claude_cli ? `<button class="btn" id="btnProjOpen"${p.exists ? "" : " disabled"}>${esc(T("Open in Claude Code"))}</button>
        <button class="btn" id="btnProjOpenTerm"${p.exists ? "" : " disabled"} title="${esc(T("Open in a terminal"))}">&gt;_</button>` : ""}</div>
    ${!a.claude_cli && p.exists ? `<div class="muted small">${esc(T("Open the folder in Claude Code: cd into it and run claude."))}</div>` : ""}
    ${res ? `<div class="note">${esc(T("Written: {n} file(s).", {n: res.written.length}))}${res.kept.length ? " " + esc(T("Kept your changed files: {list}", {list: res.kept.join(", ")})) : ""}</div>` : ""}
    </div></section>`;
}
const CAR_FIELDS = ["model", "gearbox", "ratios", "final_drive", "tire", "circumference", "speed_sensor", "mods_other", "fuel", "notes"];
const CAR_LABEL = () => ({model: T("Car and engine"), gearbox: T("Gearbox"), ratios: T("Gear ratios"), final_drive: T("Final drive"),
  tire: T("Tyres"), circumference: T("Rolling circumference, m"), speed_sensor: T("Vehicle speed comes from"),
  modifications: T("Removed or changed"), mods_other: T("Other changes"), fuel: T("Fuel"), notes: T("Other notes"),
  per_1000: T("Speed per 1000 rpm")});
function carPanel(a) {
  if (!a.project.exists || !a.car || !a.car.catalogue) return "";
  const c = Object.assign({}, a.car, S.carDraft || {}), cat = a.car.catalogue, st = a.car.state || {};
  const val = k => Array.isArray(c[k]) ? c[k].join(" ") : (c[k] === null || c[k] === undefined ? "" : String(c[k]));
  const badge = k => st[k] === "proposed" ? ` <span class="tag warn">${esc(T("proposed"))}</span>` : st[k] === "unknown" ? ` <span class="tag">${esc(T("not confirmed"))}</span>` : "";
  const f = (k, ph, list) => `<label>${esc(CAR_LABEL()[k])}${badge(k)}<input id="car_${k}" value="${esc(val(k))}" placeholder="${esc(ph)}"${list ? ` list="dl_${k}"` : ""}></label>`;
  const known = cat.gearboxes.some(g => g.key === c.gearbox);
  const boxSel = `<label>${esc(T("Gearbox"))}${badge("gearbox")}<select id="car_gearbox_sel">
      <option value=""${!c.gearbox ? " selected" : ""}>${esc(T("— don't know —"))}</option>
      ${cat.gearboxes.map(g => `<option value="${g.key}"${c.gearbox === g.key ? " selected" : ""}>${esc(g.name + " — " + g.use)}</option>`).join("")}
      <option value="__other"${c.gearbox && !known ? " selected" : ""}>${esc(T("other (type it)"))}</option></select></label>`;
  const other = (c.gearbox && !known) || S.carOtherBox;
  const sensors = {unknown: T("not confirmed"), abs_front: T("ABS ring, front (not driven) wheels"),
    abs_rear: T("ABS ring, rear (driven) wheels"), differential: T("rear differential (driven wheels)"), gearbox: T("gearbox output")};
  const mods = new Set(c.modifications || []);
  const props = a.car.proposals || [];
  const speeds = a.car.speeds || [];
  return `<section class="panel"><header><b>${esc(T("Car"))}</b>
      <span class="muted">${esc(T("Facts a log cannot tell. Pick what you know; the speed in each gear is measured from your logs. Claude can propose values from your chat — you accept them here."))}</span></header>
    ${props.length ? `<div class="note warn"><b>${esc(T("Proposed, waiting for you:"))}</b>${props.map(p => `<div class="carprop">
        <span><b>${esc(CAR_LABEL()[p.field] || p.field)}</b>: ${esc(p.shown)} <span class="muted small">— ${esc(p.source)}${p.reason ? ": " + esc(p.reason) : ""}</span></span>
        <span><button class="btn primary" data-carok="${esc(p.field)}">${esc(T("Accept"))}</button>
        <button class="btn" data-carno="${esc(p.field)}">${esc(T("Reject"))}</button></span></div>`).join("")}</div>` : ""}
    <div class="srv"><div class="srv-grid">
      ${f("model", T("E30, M54B30 swap"), true)}
      ${boxSel}
      ${other ? f("gearbox", T("gearbox name")) + f("ratios", "4.21 2.49 1.66 1.24 1.00") : ""}
      ${f("final_drive", T("2.93, or leave empty"), true)}
      ${f("tire", "205/55 R16")}
      <label>${esc(T("Vehicle speed comes from"))}${badge("speed_sensor")}<select id="car_speed_sensor">${Object.entries(sensors).map(([k, n]) => `<option value="${k}"${c.speed_sensor === k ? " selected" : ""}>${esc(n)}</option>`).join("")}</select></label>
      ${f("fuel", T("98 RON"), true)}
    </div>
    <datalist id="dl_model">${cat.models.map(m => `<option value="${esc(m)}">`).join("")}</datalist>
    <datalist id="dl_final_drive">${cat.final_drives.map(m => `<option value="${m}">`).join("")}</datalist>
    <datalist id="dl_fuel">${["95 RON", "98 RON", "100 RON", "E85"].map(m => `<option value="${esc(m)}">`).join("")}</datalist>
    <div class="small"><b>${esc(T("Removed or changed"))}</b>${badge("modifications")}</div>
    <div class="toolbar">${cat.mods.map(m => `<label class="chk"><input type="checkbox" data-carmod="${m.key}"${mods.has(m.key) ? " checked" : ""}> ${esc(m.label)}</label>`).join("")}</div>
    <div class="srv-grid">${f("mods_other", T("other changes"))}${f("notes", "")}</div>
    <div class="small"><b>${esc(T("Speed per 1000 rpm"))}</b>${badge("per_1000")}:
      ${speeds.length ? esc(speeds.map(([g, v]) => T("gear {g}: {v} km/h", {g, v})).join(", ")) : `<span class="muted">${esc(T("not measured yet"))}</span>`}</div>
    ${S.carCal ? `<div class="note">${S.carCal.map(l => esc(l)).join("<br>")}</div>` : ""}
    <div class="srv-code"><button class="btn" id="btnCarCal">${esc(T("Measure from the logs"))}</button>
      <span class="muted small">${esc(T("Needs 5–10 s of steady driving in each gear."))}</span><span class="grow"></span>
      <button class="btn primary" id="btnCarSave">${esc(T("Save"))}</button></div>
    </div></section>`;
}
function carForm() {
  const car = {};
  const g = $("car_gearbox_sel").value;
  car.gearbox = g === "__other" ? ($("car_gearbox") ? $("car_gearbox").value : "") : g;
  if (g === "__other" && $("car_ratios")) car.ratios = $("car_ratios").value;
  ["model", "final_drive", "tire", "speed_sensor", "mods_other", "fuel", "notes"].forEach(k => { car[k] = $("car_" + k).value; });
  car.modifications = [...document.querySelectorAll("[data-carmod]")].filter(x => x.checked).map(x => x.dataset.carmod);
  return car;
}
async function aiAction(name, body, busyText) {
  try {
    const r = await api(name, body, busyText);
    if (r.check) (S.aiChecks = S.aiChecks || {})["code:" + body.name] = r.check;
    S.ai = r;
    renderAI();
    if (r.message) toast(esc(r.message).replace(/\n/g, "<br>"));
  } catch (err) { fail(err); }
}
$("view").addEventListener("input", e => {
  if (S.view !== "ai") return;
  if (e.target.id === "projFolder") S.projFolder = e.target.value;
  if (e.target.id === "projName") S.projName = e.target.value;
  if (e.target.id && e.target.id.startsWith("car_") && e.target.id !== "car_gearbox_sel") (S.carDraft = S.carDraft || {})[e.target.id.slice(4)] = e.target.value;
  if (e.target.dataset && e.target.dataset.carmod) {
    S.carDraft = S.carDraft || {};
    S.carDraft.modifications = [...document.querySelectorAll("[data-carmod]")].filter(x => x.checked).map(x => x.dataset.carmod);
  }
  if (e.target.id === "car_gearbox_sel") {
    S.carDraft = S.carDraft || {};
    S.carOtherBox = e.target.value === "__other";
    S.carDraft.gearbox = S.carOtherBox ? "" : e.target.value;
    renderAI();
  }
});
$("view").addEventListener("click", async e => {
  if (S.view !== "ai") return;
  const t = e.target;
  const copy = t.closest("[data-copy]");
  if (copy) {
    const text = copy.dataset.copy;
    const done = () => toast(esc(T("Copied.")));
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => toast(esc(text)));
    else toast(esc(text));
    return;
  }
  if (t.closest("[data-ai-add]")) return aiAction("ai_add", {});
  if (t.id === "btnProjPick") {
    try { const r = await api("ai_project_pick", {}); if (r.picked) { S.projFolder = r.picked; renderAI(); } } catch (err) { fail(err); }
    return;
  }
  if (t.id === "btnProjMake") {
    try {
      const r = await api("ai_project", {folder: $("projFolder").value, name: $("projName").value,
                                         server: $("projServer").value}, T("Writing…"));
      S.ai = r; S.projResult = r.project_result; S.projFolder = undefined; S.projName = undefined; renderAI();
    } catch (err) { fail(err); }
    return;
  }
  if (t.id === "btnProjOpen" || t.id === "btnProjOpenTerm")
    return aiAction("ai_project_open", {where: t.id === "btnProjOpen" ? "desktop" : "terminal"}, T("Opening…"));
  if (t.id === "btnCarSave") {
    try { S.ai = await api("ai_car", {car: carForm()}, T("Writing…")); S.carDraft = null; S.carOtherBox = false; renderAI(); toast(esc(T("Saved."))); } catch (err) { fail(err); }
    return;
  }
  if (t.id === "btnCarCal") {
    try { const r = await api("ai_car_calibrate", {}, T("Measuring…")); S.ai = r; S.carCal = r.calibration; renderAI(); } catch (err) { fail(err); }
    return;
  }
  const ok = t.closest("[data-carok]"), no = t.closest("[data-carno]");
  if (ok || no) {
    try { S.ai = await api("ai_car_settle", {field: (ok || no).dataset[ok ? "carok" : "carno"], accept: !!ok}); renderAI(); } catch (err) { fail(err); }
    return;
  }
  const act = t.closest("[data-ai]");
  if (act) {
    const name = act.closest("[data-srv]").dataset.srv;
    const body = {name};
    if (act.dataset.ai === "ai_code") body.register = !!act.dataset.register;
    const busyText = {ai_check: T("Checking the server…"), ai_code: T("Talking to Claude Code…")}[act.dataset.ai];
    return aiAction(act.dataset.ai, body, busyText);
  }

});
$("view").addEventListener("change", e => {
  if (S.view !== "ai") return;
  const field = e.target.dataset.field;
  const card = e.target.closest("[data-srv]");
  if (!field || !card) return;
  const value = field === "port" ? Number(e.target.value) : e.target.value;
  aiAction("ai_update", {name: card.dataset.srv, changes: {[field]: value}});
});

// ---------------------------------------------------------------- shared bits for the modes
const FW_LABEL = () => ({bin_a: "A", bin_b: "B", bin2: T("other version")});
function fwSwitch(key, roles) {
  const f = S.state.files, labels = FW_LABEL();
  return `<div class="fw"><span class="muted small">${esc(T("Firmware"))}:</span>${roles.map(r =>
    `<button class="chip${S.fw[key] === r ? " on" : ""}" data-fw="${r}" data-fwkey="${key}"
      title="${esc(f[r].path || "")}">${esc(labels[r])}${f[r].name ? " · " + esc(fwName(r)) : ""}</button>`).join("")}</div>`;
}
function missing(roles) { return roles.filter(r => !S.state.files[r].path); }
const ROLE_LABEL = () => ({xdf: T("XDF definition"), bin_a: T("Firmware A"),
  bin_b: T("Firmware B"), xdf2: T("XDF of the other version"),
  bin2: T("Firmware of the other version"), patchlist: T("Patchlist XDF")});
function needBox(roles, title, sub, button, buttonId) {
  const f = S.state.files, labels = ROLE_LABEL();
  const ready = !missing(roles).length;
  return `<div class="start"><h2>${esc(ready ? T("Everything is ready") : T("Choose the files"))}</h2>
    <p>${esc(ready ? sub : T("Click a step or a card on the left to choose a file."))}</p>
    <div class="steps">${roles.map(r => `<div class="step${f[r].path ? " done" : ""}" data-pick="${r}">${f[r].path ? "✓" : "○"} ${esc(labels[r])}</div>`).join("")}</div>
    ${button ? `<button class="btn primary big" id="${buttonId}"${ready ? "" : " disabled"}>${esc(button)}</button>` : ""}</div>`;
}
function savedToast(path) {
  if (!path) return;
  toast(`${esc(T("Saved: {path}", {path}))} <button id="btnOpen">${esc(T("Open"))}</button>`);
  $("btnOpen").onclick = () => api("open", {path}).catch(fail);
}
function statsHtml(pairs) {
  return `<div class="stats">${pairs.map(([n, label]) => `<div class="stat"><b>${esc(n)}</b><span>${esc(label)}</span></div>`).join("")}</div>`;
}
let debounceTimer = null;
function debounce(fn) { clearTimeout(debounceTimer); debounceTimer = setTimeout(fn, 250); }

// ---------------------------------------------------------------- Browse firmware
async function loadBrowse() {
  const role = S.fw.browse, need = [role === "bin2" ? "xdf2" : "xdf", role];
  if (missing(need).length) {
    $("view").innerHTML = `<h1>${esc(T("Browse firmware"))}</h1>
      <div class="sub">${esc(T("One firmware in full: every map and value, with the reference next to it."))}</div>
      ${fwSwitch("browse", ["bin_a", "bin_b", "bin2"])}${needBox(need, "", "", "", "")}`;
    return;
  }
  try {
    S.br = await api("browse", {role, query: S.brq, category: S.brcat});
    renderBrowse();
  } catch (err) { fail(err); }
}
function renderBrowse() {
  const b = S.br, role = S.fw.browse;
  const cats = [`<button class="cat-btn${S.brcat ? "" : " on"}" data-cat="">${esc(T("All"))}</button>`]
    .concat(b.categories.map(c => `<button class="cat-btn${S.brcat === c.key ? " on" : ""}" data-cat="${esc(c.key)}">
      <span>${esc(c.name)}</span><small>${c.count}</small></button>`)).join("");
  const rows = b.items.map(it => `<div class="row" data-title="${esc(it.title)}" data-src="read" data-role="${role}">
      <div class="t"><code>${esc(it.title)}</code><div>${esc(it.name)}</div></div>
      <div class="val"><b>${esc(it.value)}</b>${it.units ? " " + esc(it.units) : ""}<small>${esc(it.kind)}</small></div>
      <div class="addr mono">${esc(it.address)}</div>
      ${it.has_map ? `<div class="mapline"><button class="mapbtn" data-map="${esc(it.title)}">▸ ${esc(T("show the map"))}</button><div class="mapbox"></div></div>` : ""}
    </div>`).join("");
  const keepFocus = document.activeElement && document.activeElement.id === "brq";
  $("view").innerHTML = `<div class="top"><div><h1>${esc(T("Browse firmware"))}</h1>
      <div class="sub">${esc(b.file)} · XDF ${esc(b.xdf)}</div></div></div>
    ${fwSwitch("browse", ["bin_a", "bin_b", "bin2"])}
    ${b.warning ? `<div class="alert">${esc(b.warning)}</div>` : ""}
    <div class="browse"><nav class="cats">${cats}</nav><div class="browse-main">
      <div class="toolbar"><div class="search"><input id="brq" placeholder="${esc(T("Search: rev limit, VANOS, c_conf_cat, 0x61A8…"))}" value="${esc(S.brq)}"></div></div>
      <div class="muted small">${esc(b.total > b.items.length ? T("Showing the first {n} of {total}. Refine the search.", {n: b.items.length, total: b.total}) : T("Found: {n}", {n: b.total}))}</div>
      <section class="cat">${rows || `<div class="empty-state"><b>${esc(T("Nothing found"))}</b>${esc(T("Try another word — English or Russian, a name or an address."))}</div>`}</section>
    </div></div>`;
  if (keepFocus) { const q = $("brq"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  markSelected();
}
$("view").addEventListener("click", e => {
  if (S.view !== "browse") return;
  const c = e.target.closest("[data-cat]");
  if (c) { S.brcat = c.dataset.cat; S.maps = {}; loadBrowse(); }
});
$("view").addEventListener("input", e => {
  if (e.target.id === "brq") { S.brq = e.target.value; debounce(() => { S.maps = {}; loadBrowse(); }); }
});

// ---------------------------------------------------------------- Different versions + port plan
function renderCross() {
  const tab = S.crossTab;
  const tabs = `<div class="tabs"><button class="${tab === "cmp" ? "on" : ""}" data-ctab="cmp">1. ${esc(T("Compare the versions"))}</button>
    <button class="${tab === "port" ? "on" : ""}" data-ctab="port">2. ${esc(T("Plan for porting your edits"))}</button></div>`;
  const head = `<h1>${esc(T("Different software versions"))}</h1>
    <div class="sub">${esc(T("Each firmware has its own XDF. Parameters are matched by name, physical values are compared, not bytes."))}</div>${tabs}`;
  if (tab === "cmp") {
    const role = S.fw.cross === "bin_a" ? "bin_a" : "bin_b";
    const need = ["xdf", role, "xdf2", "bin2"];
    if (!S.cr) {
      $("view").innerHTML = head + fwSwitch("cross", ["bin_a", "bin_b"]) +
        needBox(need, "", T("Your firmware is compared with the firmware of the other version."), T("Compare the versions"), "btnCross");
      return;
    }
    const c = S.cr;
    $("view").innerHTML = head + fwSwitch("cross", ["bin_a", "bin_b"]) + `
      <div class="top"><div class="sub">A: ${esc(c.a)} · ${esc(c.xdf_a)} (${esc(c.fw_a)}) &nbsp;↔&nbsp; B: ${esc(c.b)} · ${esc(c.xdf_b)} (${esc(c.fw_b)})</div>
        <div class="actions"><button class="btn primary" data-rep="cross:html">${esc(T("Save HTML report"))}</button>
        <button class="btn" id="btnCross" title="${esc(T("Compare again"))}">↻</button></div></div>
      ${statsHtml([[c.stats.different, T("different")], [c.stats.same, T("same")], [c.stats.only_a, T("only in A")], [c.stats.only_b, T("only in B")]])}
      ${c.groups.map(g => `<section class="cat"><header>${esc(g.name)}<span>${g.items.length}</span></header>${g.items.map(it =>
        `<div class="row" data-title="${esc(it.title)}" data-src="xdf" data-role="${it.side === "a" ? role : "bin2"}">
          <div class="t"><code>${esc(it.title)}</code><div>${esc(it.name)}</div></div>
          <div class="val">${esc(it.summary)}${it.units ? " " + esc(it.units) : ""}${it.notes.map(n => `<small class="warn">${esc(n)}</small>`).join("")}</div>
          <div><span class="pill">${esc(it.status)}</span></div></div>`).join("")}</section>`).join("")}`;
    markSelected();
    return;
  }
  const need = ["xdf", "bin_a", "bin_b", "xdf2", "bin2"];
  if (!S.pp) {
    $("view").innerHTML = head + `<div class="alert">${esc(T("The program only builds a plan and writes nothing to the firmware. Make all edits by hand in TunerPro and recalculate the checksums there."))}</div>` +
      needBox(need, "", T("Your edits are the difference between A (stock) and B (tune); they are matched against the other version."), T("Build the plan"), "btnPort");
    return;
  }
  const p = S.pp;
  const pill = key => key === "warned" ? "bad" : "ok";
  $("view").innerHTML = head + `
    <div class="top"><div class="sub">${esc(p.stock)} → ${esc(p.tuned)} (${esc(p.xdf_src)}) ⇒ ${esc(p.target)} (${esc(p.xdf_dst)})</div>
      <div class="actions"><button class="btn" data-rep="port:pdf">${esc(T("Save PDF"))}</button><button class="btn" data-rep="port:csv">CSV</button>
      <button class="btn primary" data-rep="port:html">${esc(T("Save HTML report"))}</button>
      <button class="btn" id="btnPort" title="${esc(T("Compare again"))}">↻</button></div></div>
    <div class="alert">${esc(T("The program only builds a plan and writes nothing to the firmware. Make all edits by hand in TunerPro and recalculate the checksums there."))}</div>
    ${statsHtml([[p.stats.changed, T("parameters you changed")], [p.stats.safe_bytes, T("safe by bytes")], [p.stats.safe_name, T("safe by name")], [p.stats.warned, T("with a warning")]])}
    ${p.groups.map(g => `<section class="cat"><header>${esc(g.name)}<span>${g.items.length}</span></header>${g.items.map(it =>
      `<div class="row" data-title="${esc(it.title)}" data-src="xdf" data-role="bin_a">
        <div class="t"><code>${esc(it.title)}</code><div>${esc(it.name)}</div>${it.dst ? `<div class="muted small">→ <code>${esc(it.dst)}</code></div>` : ""}</div>
        <div class="val">${esc(it.summary)}${it.units ? " " + esc(it.units) : ""}${it.bits.map(b => `<small>• ${esc(b)}</small>`).join("")}
          ${it.candidates.length ? `<small>${esc(T("Similar in the target:"))} ${it.candidates.map(c => `<code>${esc(c)}</code>`).join(", ")}</small>` : ""}</div>
        <div><span class="pill ${pill(g.key)}">${esc(it.status)}</span></div></div>`).join("")}</section>`).join("")}`;
  markSelected();
}
$("view").addEventListener("click", async e => {
  if (S.view !== "cross") return;
  const t = e.target, tab = t.closest("[data-ctab]");
  if (tab) { S.crossTab = tab.dataset.ctab; closeDrawer(); return renderCross(); }
  if (t.id === "btnCross") {
    try { S.cr = await api("cross", {role: S.fw.cross}, T("Comparing different versions…")); renderCross(); } catch (err) { fail(err); }
  }
  if (t.id === "btnPort") {
    try { S.pp = await api("port", {}, T("Building the port plan…")); renderCross(); } catch (err) { fail(err); }
  }
  const rep = t.closest("[data-rep]");
  if (rep) {
    const [what, kind] = rep.dataset.rep.split(":");
    try { savedToast((await api("save_report", {what, kind}, T("Saving…"))).path); } catch (err) { fail(err); }
  }
});

// ---------------------------------------------------------------- Patches
function renderPatches() {
  const role = S.fw.patch, need = ["patchlist", role];
  const head = `<h1>${esc(T("Patches"))}</h1>
    <div class="sub">${esc(T("Which patches from the community patchlist are applied to the firmware."))}</div>
    ${fileCard("patchlist", T("Patchlist XDF"), T("choose the patchlist .xdf"))}${fwSwitch("patch", ["bin_a", "bin_b", "bin2"])}`;
  if (!S.pt) {
    $("view").innerHTML = head + needBox(need, "", T("Press the button to check the patches."), T("Check"), "btnPatch");
    return;
  }
  const p = S.pt, filt = S.ptFilter;
  const chip = (k, label) => `<button class="chip${filt === k ? " on" : ""}" data-ptf="${k}">${esc(label)}</button>`;
  const cls = st => ({"applied": "ok", "not applied": "", "partial": "bad", "modified": "bad", "out of file": "bad"}[st] || "");
  $("view").innerHTML = head + `
    <div class="top"><div class="sub">${esc(p.file)} · ${esc(p.patchlist)}</div>
      <div class="actions"><button class="btn" id="btnPatch" title="${esc(T("Check"))}">↻</button></div></div>
    ${statsHtml([[p.stats.applied, T("applied")], [p.stats.total - p.stats.applied, T("not applied or partly")], [p.stats.total, T("patches in the list")]])}
    <div class="toolbar">${chip("all", T("All"))}${chip("applied", T("applied"))}${chip("not applied", T("not applied"))}${chip("other", T("partly / modified"))}</div>
    ${p.groups.map(g => {
      const items = g.items.filter(it => filt === "all" || it.state === filt ||
        (filt === "other" && !["applied", "not applied"].includes(it.state)));
      return items.length ? `<section class="cat"><header>${esc(g.name)}<span>${items.length}</span></header>${items.map(it =>
        `<div class="row prow"><div class="t"><b>${esc(it.title)}</b><div>${esc(it.desc)}</div>
          ${it.desc_orig ? `<details class="orig" data-noopen="1"><summary>${esc(T("original description (English)"))}</summary><p>${esc(it.desc_orig)}</p></details>` : ""}
          ${it.details.map(d => `<small class="warn mono">${esc(d)}</small>`).join("")}</div>
          <div></div><div><span class="pill ${cls(it.state)}">${esc(it.label)}</span></div></div>`).join("")}</section>` : "";
    }).join("")}`;
}
$("view").addEventListener("click", async e => {
  if (S.view !== "patch") return;
  const f = e.target.closest("[data-ptf]");
  if (f) { S.ptFilter = f.dataset.ptf; return renderPatches(); }
  if (e.target.id === "btnPatch") {
    try { S.pt = await api("patches", {role: S.fw.patch}, T("Checking patches…")); renderPatches(); } catch (err) { fail(err); }
  }
});

// ---------------------------------------------------------------- Edits
async function loadEdits() {
  const role = S.fw.edits, need = [role === "bin2" ? "xdf2" : "xdf", role];
  if (missing(need).length) { S.ed = null; return renderEdits(); }
  try { S.ed = await api("edits_state", {role}); } catch (err) { S.ed = null; fail(err); }
  renderEdits();
}
function editCard(c) {
  const kind = {value: T("value"), cells: T("cells"), region: T("region"), patch: T("patch")}[c.kind] || c.kind;
  const open = c.target in S.maps;
  const cells = (c.cells || []).map(x => `<span class="mono small">${esc(x.at)}: ${esc(x.old)} → <b>${esc(x.new)}</b>${x.asked !== x.new ? ` <span class="muted">(${esc(T("asked {value}", {value: x.asked}))})</span>` : ""}</span>`).join(" · ");
  return `<div class="row edit${c.ok ? "" : " bad"}" data-title="${esc(c.target)}" data-src="edit" data-role="${esc(S.fw.edits)}">
    <div class="t"><code>#${c.id} ${esc(c.target)}</code><div>${esc(c.name || "")}</div>
      <small class="muted">${esc(kind)}${c.shape ? " · " + esc(c.shape) : ""}${c.total ? " · " + esc(T("{changed} of {total} cells changed", {changed: c.changed, total: c.total})) : ""} · ${esc(c.source === "ai" ? "AI" : T("you"))} · ${esc(c.created)}</small></div>
    <div class="val" data-noopen="1"><div class="why">${esc(T("Why"))}: ${esc(c.reason)}</div>
      ${c.evidence ? `<div class="small">∿ ${esc(T("Evidence log"))}: <a href="#" data-golog="${esc(c.evidence)}" data-golmap="${c.has_map ? esc(c.target) : ""}">${esc(c.evidence)}</a></div>` : ""}
      ${cells ? `<div>${cells}${c.changed > (c.cells || []).length ? " …" : ""}</div>` : ""}
      ${c.kind === "patch" ? c.writes.map(w => `<div class="mono small">${esc(w.off)}: ${esc(w.old)} → <b>${esc(w.new)}</b></div>`).join("") : ""}
      ${c.error ? `<div class="err">${esc(T("Refused"))}: ${esc(c.error)}</div>` : ""}
      ${c.red.map(r => `<div class="pill bad">⚠ ${esc(r)}</div>`).join(" ")}
      ${c.notes.map(n => `<div class="muted small">• ${esc(n)}</div>`).join("")}</div>
    <div class="delta" data-noopen="1"><button class="btn icon" data-edrm="${c.id}" title="${esc(T("Remove from the draft"))}">×</button></div>
    ${c.has_map ? `<div class="mapline"><button class="mapbtn" data-map="${esc(c.target)}">${open ? "▾ " + esc(T("hide the map")) : "▸ " + esc(T("show the map"))}</button>
      <span class="modes"${open ? "" : " hidden"}>${[["delta", T("difference")], ["a", T("before")], ["b", T("after")]].map(([m, l]) =>
        `<button data-mode="${m}" class="${(S.maps[c.target] || "delta") === m ? "on" : ""}">${esc(l)}</button>`).join("")}</span>
      <div class="mapbox"></div></div>` : ""}</div>`;
}
function renderEdits() {
  const role = S.fw.edits, need = [role === "bin2" ? "xdf2" : "xdf", role];
  const head = `<div class="top"><div><h1>${esc(T("Edits"))}</h1>
    <div class="sub">${esc(T("Claude proposes changes through MCP; they collect here. Nothing is written until you create the new .bin. Checksums are fixed by MS4X Flasher."))}</div></div></div>
    ${fwSwitch("edits", ["bin_a", "bin_b", "bin2"])}`;
  if (missing(need).length || !S.ed) {
    $("view").innerHTML = head + needBox(need, "", T("Choose the XDF and the firmware the AI works on."), "", "");
    return;
  }
  const e = S.ed;
  const last = S.edLast && S.edLast.role === role ? `<section class="panel done"><header><b>✓ ${esc(T("Created: {name}", {name: S.edLast.name}))}</b>
      <span class="muted">${esc(T("Bytes changed: {n}", {n: S.edLast.bytes}))} · ${esc(S.edLast.path)}</span></header>
      <div class="actions"><button class="btn" id="btnEdOpen">${esc(T("Open the change log"))}</button>
        <button class="btn primary" id="btnEdUse">${esc(T("Use as firmware {role}", {role: role === "bin_a" ? "A" : role === "bin_b" ? "B" : T("of the other version")}))}</button></div></section>` : "";
  if (!e.changes.length) {
    $("view").innerHTML = head + last + `<div class="empty-state"><b>${esc(T("No changes yet"))}</b>${esc(T("Ask Claude in Claude Code to propose changes for {file} — they appear here at once.", {file: e.file}))}</div>`;
    return;
  }
  const canWrite = e.ok && (!e.red || S.edConfirm.trim().toUpperCase() === e.confirm_word.toUpperCase());
  $("view").innerHTML = head + last + `
    <div class="stats">
      <div class="stat"><b>${e.changes.length}</b><span>${esc(T("changes in the draft"))}</span></div>
      <div class="stat"><b>${e.bytes}</b><span>${esc(T("bytes will change"))}</span></div>
      <div class="stat"><b>${esc(e.fw)}</b><span>${esc(e.file)} · ${e.size_kb} ${esc(T("KB"))}</span></div>
      <div class="stat"><b>${e.full_image ? "512" : "64"}</b><span>${esc(e.full_image ? T("KB — flash the full image (patches change code)") : T("KB — calibration flash is enough"))}</span></div></div>
    ${e.blockers.map(b => `<div class="alert">${esc(b)}</div>`).join("")}
    <section class="cat"><header>${esc(T("Changes"))}<span>${e.changes.length}</span></header>${e.changes.map(editCard).join("")}</section>
    <details class="panel"><summary><b>${esc(T("Byte diff"))}</b> <span class="muted">${esc(T("{n} runs", {n: e.runs.length + e.more_runs}))}</span></summary>
      <table class="plain mono"><tr><th>${esc(T("Offset"))}</th><th>${esc(T("Length"))}</th><th>${esc(T("Was"))}</th><th>${esc(T("Will be"))}</th></tr>
      ${e.runs.map(r => `<tr><td>${esc(r.off)}</td><td>${r.len}</td><td>${esc(r.old)}</td><td><b>${esc(r.new)}</b></td></tr>`).join("")}</table>
      ${e.more_runs ? `<div class="muted small">${esc(T("… and {n} more", {n: e.more_runs}))}</div>` : ""}</details>
    <section class="panel"><header><b>${esc(T("Create the new firmware"))}</b>
      <span class="muted">${esc(T("New file: {name} (+ a .changes.txt log next to it). The source file is not changed.", {name: e.next_file}))}</span></header>
      ${e.red ? `<div class="alert">${esc(T("The draft has risky changes (marked ⚠). Read them, then type {word} to confirm.", {word: e.confirm_word}))}
        <input id="edConfirm" class="mono" value="${esc(S.edConfirm)}" placeholder="${esc(e.confirm_word)}"></div>` : ""}
      <div class="actions"><button class="btn primary big" id="btnEdCreate"${canWrite ? "" : " disabled"}>${esc(T("Create .bin"))}</button>
        <button class="btn" id="btnEdClear">${esc(T("Clear the draft"))}</button></div></section>`;
  for (const title of Object.keys(S.maps)) loadMap(title, S.maps[title], false);
}
$("view").addEventListener("click", async e => {
  if (S.view !== "edits") return;
  const t = e.target, rm = t.closest("[data-edrm]");
  try {
    if (rm) { S.ed = await api("edits_remove", {role: S.fw.edits, id: Number(rm.dataset.edrm)}); return renderEdits(); }
    if (t.id === "btnEdClear") { S.ed = await api("edits_remove", {role: S.fw.edits, all: true}); S.maps = {}; return renderEdits(); }
    if (t.id === "btnEdCreate") {
      const r = await api("edits_create", {role: S.fw.edits, confirm: S.edConfirm}, T("Writing…"));
      S.edConfirm = ""; S.maps = {};
      S.edLast = Object.assign({role: S.fw.edits}, r);
      return loadEdits();
    }
    if (t.id === "btnEdOpen" && S.edLast) return api("open", {path: S.edLast.notes});
    if (t.id === "btnEdUse" && S.edLast) {
      await api("edits_use", {role: S.edLast.role, path: S.edLast.path});
      S.state = await api("state"); S.edLast = null; resetFor(S.fw.edits); renderSide(); return loadEdits();
    }
  } catch (err) { fail(err); }
});
$("view").addEventListener("input", e => {
  if (S.view !== "edits" || e.target.id !== "edConfirm") return;
  S.edConfirm = e.target.value;
  const btn = $("btnEdCreate"), ed = S.ed;
  if (btn && ed) btn.disabled = !(ed.ok && S.edConfirm.trim().toUpperCase() === ed.confirm_word.toUpperCase());
});

// ---------------------------------------------------------------- Logs
// TunerPro logs in the project, each bound to the firmware that was in the car.
async function loadLogs() {
  try {
    S.lg = await api("logs_state", {});
    if (S.lg.project) S.lr = await api("logger_state", {}).catch(() => null);
    const v = S.lg.view || {};
    if (v.log) {
      S.lgSel = v.log; S.lgV = null; S.lgRange = (v.from !== undefined && v.to !== undefined) ? [Number(v.from), Number(v.to)] : null;
      S.lgMap = v.map ? {map: v.map, y_channel: v.y_channel || "", x_channel: v.x_channel || "", filters: v.filters || null,
                         value_channel: v.value_channel || "", compare: v.compare || ""} : null;
      S.lgMapData = null; S.lgCell = null;
    }
    if (!S.lgSel && S.lg.logs.length) S.lgSel = S.lg.logs[S.lg.logs.length - 1].name;
    if (S.lgSel && !S.lg.logs.some(l => l.name === S.lgSel)) S.lgSel = null;
    if (!S.lgRole && S.lg.firmwares.length) S.lgRole = S.lg.firmwares[S.lg.firmwares.length > 1 ? 1 : 0].role;
    if (S.lgSel && (!S.lgV || S.lgV.name !== S.lgSel)) await openLog(S.lgSel, false);
  } catch (err) { fail(err); }
  renderLogs();
}
async function openLog(name, render = true) {
  S.lgSel = name;
  S.lgV = await api("logs_view", {log: name}); S.lgCondEdit = false;
  if (!S.lgChart || !S.lgChart.every(c => S.lgV.channels.includes(c))) S.lgChart = S.lgV.chart.slice();
  const fresh = () => ({map: S.lgV.maps[0].title, y_channel: "", x_channel: "", filters: null, value_channel: "", compare: ""});
  if (!S.lgMap && S.lgV.maps.length) S.lgMap = fresh();
  if (S.lgMap && !S.lgV.maps.some(m => m.title === S.lgMap.map)) S.lgMap = S.lgV.maps.length ? fresh() : null;
  if (S.lgMap && S.lgMap.compare && !S.lgV.others.includes(S.lgMap.compare)) S.lgMap.compare = "";
  if (S.lgMap && S.lgMap.value_channel && !S.lgV.channels.includes(S.lgMap.value_channel)) S.lgMap.value_channel = "";
  S.lgFile = null;
  await Promise.all([loadSeries(), loadLogMap()]);
  if (render) renderLogs();
}
async function loadSeries() {
  const v = S.lgV;
  if (!v) return;
  const range = S.lgRange || [v.t0, v.t1];
  S.lgSeries = await api("logs_series", {log: v.name, channels: S.lgChart, from: range[0], to: range[1], points: 1400});
}
async function loadLogMap() {
  S.lgMapData = null; S.lgMapErr = "";
  if (!S.lgV || !S.lgMap || S.lgV.problem) return;
  try {
    const m = S.lgMap;
    S.lgMapData = await api("logs_map", {log: S.lgV.name, map: m.map, y_channel: m.y_channel, x_channel: m.x_channel,
                                         filters: m.filters === null ? undefined : m.filters,
                                         value_channel: m.value_channel || "", compare: m.compare || ""});
    m.y_channel = S.lgMapData.y_channel; m.x_channel = S.lgMapData.x_channel; m.filters = S.lgMapData.filters;
  } catch (err) { S.lgMapErr = err.message || String(err); }
}
const n1 = v => (Math.round(v * 100) / 100).toString();
const span2 = p => !p ? "" : p[0] === p[1] ? n1(p[0]) : `${n1(p[0])}…${n1(p[1])}`;
function logChart(sr) {
  if (!sr || !sr.lanes.length) return `<div class="muted">${esc(T("Choose channels for the chart."))}</div>`;
  const W = 1000, L = 200, H = 64, G = 8, top = 6;
  const span = (sr.to - sr.from) || 1;
  const X = tm => L + (tm - sr.from) / span * (W - L - 10);
  let svg = "";
  sr.lanes.forEach((lane, k) => {
    const y0 = top + k * (H + G);
    const vals = lane.v;
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (hi === lo) { hi = lo + 1; lo = lo - 1; }
    const Y = v => y0 + H - 4 - (v - lo) / (hi - lo) * (H - 8);
    const pts = lane.t.map((tm, i) => `${X(tm).toFixed(1)},${Y(vals[i]).toFixed(1)}`).join(" ");
    const knock = lane.name.startsWith("Knock Correction");
    svg += `<rect class="lane" x="${L}" y="${y0}" width="${W - L - 10}" height="${H}"/>
      <text class="lbl" x="6" y="${y0 + 18}">${esc(lane.name.replace("Knock Correction ", "Knock "))}</text>
      <text class="rng" x="6" y="${y0 + 37}">${esc(n1(Math.min(...vals)))} … ${esc(n1(Math.max(...vals)))} ${esc(lane.units || "")}</text>
      <polyline class="ln${knock ? " kn" : ""}" points="${pts}"/>`;
    if (knock && lo < 0 && hi > 0) svg += `<line class="zero" x1="${L}" x2="${W - 10}" y1="${Y(0)}" y2="${Y(0)}"/>`;
  });
  const h = top + sr.lanes.length * (H + G);
  const marks = sr.knock.map(tm => `<line class="km" x1="${X(tm)}" x2="${X(tm)}" y1="0" y2="${h}"><title>${esc(T("knock detected at {t} s", {t: n1(tm)}))}</title></line>`).join("");
  const ticks = [];
  for (let i = 0; i <= 8; i++) { const tm = sr.from + span * i / 8; ticks.push(`<text class="tick" x="${X(tm)}" y="${h + 12}" text-anchor="middle">${esc(n1(tm))}</text>`); }
  return `<svg id="lgChart" class="lgchart" viewBox="0 0 ${W} ${h + 18}" data-from="${sr.from}" data-to="${sr.to}" data-l="${L}" data-w="${W}">
    ${svg}${marks}${ticks.join("")}<rect id="lgSel" class="sel" x="0" y="0" width="0" height="${h}" visibility="hidden"/></svg>`;
}
function logMapHtml(m) {
  const head = `<tr><th></th>${m.x.map(x => `<th>${esc(x)}</th>`).join("")}</tr>`;
  const cmp = !!m.compare, val = !!m.value_channel;
  const body = m.rows.map((row, r) => `<tr><th>${esc(m.y[r])}</th>${row.map((c, k) => {
    let cls = cmp ? "c-" + (c.st || "none") : c.k ? "hk" : c.r ? "hr" : c.n ? "hn" : "h0";
    if (val && !c.m && !cmp) cls = c.n ? "hn" : "h0";
    const sel = S.lgCell && S.lgCell[0] === r && S.lgCell[1] === k ? " sel" : "";
    let main = esc(c.v), sub = "";
    if (val && c.m !== undefined) { main = esc(c.m); sub = esc(c.v); }
    if (cmp) sub = [c.was ? esc(T("was {v}", {v: c.was})) : "", c.a.n || c.n ? `⚡${c.a.k}→${c.k}` : ""].filter(Boolean).join(" · ");
    else if (c.n && !val) sub = `${c.n}${c.k ? " ⚡" + c.k : ""}`;
    else if (val && c.n) sub = `${esc(c.v)} · ${c.n}`;
    const style = val && !cmp && !c.n ? "" : ` style="background:${c.bg};color:${c.fg}"`;
    return `<td class="${cls}${sel}" data-lgcell="${r},${k}"${style}>${main}${sub ? `<i>${sub}</i>` : ""}</td>`;
  }).join("")}</tr>`).join("");
  const legend = cmp
    ? `<span class="c c-fixed">${esc(T("knock gone"))}</span><span class="c c-new">${esc(T("new knock"))}</span><span class="c c-still">${esc(T("still knocks"))}</span><span class="c c-ok">${esc(T("visited in both, no knock"))}</span><span class="c c-one">${esc(T("visited in one log only"))}</span>`
    : `<span class="c hn">${esc(T("rows here"))}</span><span class="c hr">${esc(T("retard (recovering)"))}</span><span class="c hk">⚡ ${esc(T("knock detected"))}</span>`;
  return `<div class="axis">${esc(T("rows — {name}", {name: m.y_name || "-"}))} [${esc(m.y_channel || "-")}] · ${esc(T("columns — {name}", {name: m.x_name || "-"}))} [${esc(m.x_channel || "-")}]</div>
    ${cmp ? `<div class="note">${esc(T("Before: {a} (firmware {fa}) → after: {b} (firmware {fb}). Map values are the \"after\" ones; \"was\" marks cells the flash changed.", {a: m.compare, fa: m.compare_firmware, b: S.lgV.name, fb: m.firmware}))}</div>` : ""}
    ${val ? `<div class="note">${esc(T("Cells show the mean of {ch} {units}; small: the map value and the rows.", {ch: m.value_channel, units: m.value_units ? "(" + m.value_units + ")" : ""}))}
      ${/Fuel Trim/.test(m.value_channel) ? "<br>" + esc(T("Red (positive): the ECU adds fuel, the mixture was lean there. Blue (negative): it takes fuel away, rich. Without a wideband this shows the closed-loop correction only, not the full-load mixture.")) : ""}</div>` : ""}
    <div class="mapwrap"><table class="map lgmap">${head}${body}</table></div>
    <div class="legend">${legend}
      <span class="muted small">${esc(T("Rows used: {n}, outside the axes: {out}. A row counts at the nearest breakpoint.", {n: m.used, out: m.outside}))}</span></div>`;
}
function hitText(m, c) {
  if (!c || !c.n) return T("not visited");
  let out = T("rows {n}", {n: c.n});
  if (c.m !== undefined) out += "; " + T("{ch} mean {mean} (min {lo}, max {hi}) {units}", {ch: m.value_channel, mean: c.m, lo: c.lo, hi: c.hi, units: m.value_units || ""});
  if (c.r) out += "; " + T("knock {k} (cyl {cyl}), retard rows {rr}, deepest {w}°", {k: c.k, cyl: c.cyl.join(",") || "-", rr: c.r, w: n1(c.w)});
  return out;
}
function cellDetail(m) {
  if (!S.lgCell) return "";
  const [r, k] = S.lgCell, c = m.rows[r] && m.rows[r][k];
  if (!c) return "";
  const where = `${esc(m.y_channel || "")} ${esc(m.y[r])} · ${esc(m.x_channel || "")} ${esc(m.x[k])}: ${esc(T("map {value} {units}", {value: (c.was ? c.was + " → " : "") + c.v, units: m.units}))}`;
  const zoom = c.t.length ? "<br>" + c.t.map(tm => `<button class="chip" data-lgzoom="${tm - 3},${tm + 3}">${esc(n1(tm))} s</button>`).join(" ") : "";
  if (m.compare) return `<div class="note">${where}<br>${esc(T("before: {text}", {text: hitText(m, c.a)}))}<br>${esc(T("after:  {text}", {text: hitText(m, c)}))}${zoom}</div>`;
  return `<div class="note">${where}<br>${esc(hitText(m, c))}${zoom}</div>`;
}
function renderLogs() {
  const g = S.lg;
  if (!g) { $("view").innerHTML = ""; return; }
  const fwOpts = g.firmwares.map(f => `<option value="${f.role}"${S.lgRole === f.role ? " selected" : ""}>${esc(f.label)} — ${esc(f.name)}</option>`).join("") +
    `<option value="file"${S.lgRole === "file" ? " selected" : ""}>${esc(T("another file…"))}</option>`;
  const head = `<div class="top"><div><h1>${esc(T("Logs"))}</h1>
    <div class="sub">${esc(T("TunerPro logs of the project. Each one is bound to the firmware that was in the car: the map overlay reads exactly that firmware, and an edit of another firmware citing the log is a risk you confirm."))}</div></div></div>`;
  if (!g.project) {
    $("view").innerHTML = head + `<div class="start"><h2>${esc(T("Create the project first"))}</h2>
      <p>${esc(T("Logs are kept in the project's logs/ folder, where Claude Code reads them."))}</p>
      <a class="btn primary big" href="#" data-goto="ai">${esc(T("AI assistant"))}</a></div>`;
    return;
  }
  const add = `<section class="panel"><header><b>${esc(T("Add a TunerPro log"))}</b>
      <span class="muted">${esc(T("A copy goes into logs/; the original is not touched. Say honestly which firmware was in the car when the log was recorded."))}</span></header>
    <div class="srv-grid"><label>${esc(T("Firmware in the car"))}<select id="lgRole">${fwOpts}</select></label>
      <label>${esc(T("Note (fuel, weather, what you did)"))}<input id="lgNote" value="${esc(S.lgNote || "")}" placeholder="${esc(T("98 RON, +12 °C, 3rd gear pulls"))}"></label></div>
    <div class="actions"><button class="btn primary" id="btnLgAdd">${esc(T("Choose the log…"))}</button>
      <span class="muted small">${esc(T("A .csv export or TunerPro's own .xdl (decoded with the ADX: {name})", {name: g.adx || T("asked when needed")}))}</span>
      <button class="btn" id="btnLgAdx">${esc(T("ADX…"))}</button></div></section>`;
  const list = g.logs.map(l => `<button class="cat-btn${S.lgSel === l.name ? " on" : ""}" data-lg="${esc(l.name)}"><span>${esc(l.name)}
      <small class="muted">${l.error ? esc(l.error) : esc(T("{dur} s · {rate} Hz", {dur: l.duration, rate: l.rate}))} · ${esc(l.firmware || "—")}</small>
      ${l.problem ? `<small class="err">⚠ ${esc(l.problem)}</small>` : ""}
      ${l.old ? `<small class="err">⟳ ${esc(T("decoded by an older version"))}</small>` : ""}</span>${l.events ? `<span class="tag bad">⚡ ${l.events}</span>` : ""}</button>`).join("") ||
    `<div class="muted small">${esc(T("No logs yet."))}</div>`;
  $("view").innerHTML = head + recorderPanel(fwOpts) + `<div class="browse"><nav class="cats">${list}</nav><div class="browse-main">${S.lgV ? logBody(S.lgV) : add}</div></div>` + (S.lgV ? add : "");
  lrPoll();
}
// ---- the logger: the program reads the ECU through the cable
function recorderPanel(fwOpts) {
  const r = S.lr;
  if (!r) return "";
  const st = r.status, rec = r.recording;
  const ports = r.ports.map(p => `<option value="${esc(p.device)}"${(S.lrPort || r.port) === p.device ? " selected" : ""}>${esc(p.device)} — ${esc(p.description)}${p.ftdi ? " (FTDI)" : ""}</option>`).join("") ||
    `<option value="">${esc(T("no COM ports found"))}</option>`;
  const live = st && st.live ? st.live : {};
  const v = (k, u) => live[k] === null || live[k] === undefined ? "—" : `${live[k]} ${u}`;
  const states = {starting: T("starting"), connecting: T("connecting…"), recording: T("recording"),
                  reconnecting: T("connection lost — reconnecting"), no_port: T("the port cannot be opened"), stopped: T("stopped")};
  const status = st ? `<div class="lrstat${rec ? " on" : ""}">
      <div><b>${esc(states[st.state] || st.state)}</b> · ${esc(st.name)} · ${esc(T("{s} s · {rows} rows · {hz} Hz", {s: st.seconds, rows: st.rows, hz: st.rate}))}</div>
      <div class="lrlive"><span>${esc(T("rpm"))} <b>${esc(v("Engine Speed", ""))}</b></span><span>${esc(T("coolant"))} <b>${esc(v("Coolant Temperature", "°C"))}</b></span><span>${esc(T("oil"))} <b>${esc(v("Oil Temperature", "°C"))}</b></span></div>
      ${st.errors || st.reconnects ? `<div class="muted small">${esc(T("missed replies: {e} · reconnects: {r}", {e: st.errors, r: st.reconnects}))}${st.message ? " · " + esc(st.message) : ""}</div>` : ""}</div>` : "";
  const test = r.test ? `<details class="lrtest"${r.test.ok ? "" : " open"}><summary>${r.test.ok
      ? "✓ " + esc(T("The ECU answers: rpm {n}, coolant {c} °C, oil {o} °C", {n: r.test.values["Engine Speed"] ?? "—", c: r.test.values["Coolant Temperature"] ?? "—", o: r.test.values["Oil Temperature"] ?? "—"}))
      : "✗ " + esc(T("No connection: {error}", {error: r.test.error}))}</summary>
      <div class="muted small">${esc(T("Exchange journal (also saved to logs/{file}):", {file: r.test.journal_file || ""}))}</div>
      <pre class="lgtext">${esc(r.test.journal.map(l => `${String(l.t).padEnd(8)} ${l.dir.padEnd(5)} ${l.baud ? String(l.baud).padEnd(7) : "".padEnd(7)} ${l.hex || ""} ${l.text || ""}`).join("\n"))}</pre></details>` : "";
  return `<section class="panel"><header><b>${esc(T("Record with the cable"))}</b>
      <span class="muted">${esc(T("The program reads the ECU itself through the K+DCAN cable, as the ADX describes ({adx}). Ignition on; with a high-speed ADX connect before starting the engine. Only you start and stop it — the AI cannot.", {adx: r.adx || T("asked when needed")}))}</span></header>
    <div class="srv-grid"><label>${esc(T("COM port"))}<select id="lrPort"${rec ? " disabled" : ""}>${ports}</select></label>
      <label>${esc(T("Firmware in the car"))}<select id="lgRole2"${rec ? " disabled" : ""}>${fwOpts}</select></label>
      <label>${esc(T("Note (fuel, weather, what you did)"))}<input id="lrNote" value="${esc(S.lrNote || "")}"${rec ? " disabled" : ""}></label></div>
    <div class="actions">${rec ? `<button class="btn primary" id="btnLrStop">■ ${esc(T("Stop"))}</button>`
      : `<button class="btn" id="btnLrTest">${esc(T("Check the connection"))}</button><button class="btn primary" id="btnLrStart">● ${esc(T("Start recording"))}</button>`}
      <button class="btn" id="btnLrPorts"${rec ? " disabled" : ""}>↻</button></div>
    ${status}${test}
    <div class="muted small">${esc(T("FTDI cable: in Device Manager → the port → Advanced, a latency timer of 1 ms may raise the rate."))}</div></section>`;
}
let lrTimer = null;
function lrPoll() {
  clearTimeout(lrTimer);
  if (S.view !== "logs" || !S.lr || !S.lr.recording) return;
  lrTimer = setTimeout(async () => {
    try {
      const r = await api("logger_state", {});
      const was = S.lr.recording;
      S.lr = r;
      if (was && !r.recording) return loadLogs();
      const panel = $("lrPort") && $("lrPort").closest("section");
      const fw = $("lgRole2") ? $("lgRole2").innerHTML : "";
      if (panel) { const tmp = document.createElement("div"); tmp.innerHTML = recorderPanel(fw); panel.replaceWith(tmp.firstElementChild); }
    } catch (err) { /* the window is closing */ }
    lrPoll();
  }, 1000);
}

function logBody(v) {
  const ev = v.events.map((e, i) => `<tr class="click" data-lgzoom="${e.start - 2},${e.end + 2}"><td>#${i + 1}</td><td>${esc(n1(e.start))}–${esc(n1(e.end))}</td>
      <td>${e.det}</td><td>${esc(span2(e.rpm))}</td><td>${esc(span2(e.load_ign))}</td><td>${esc(span2(e.throttle))}</td>
      <td>${esc(span2(e.iat))}</td><td>${esc(Object.entries(e.cyl).map(([c, w]) => `${c}: ${n1(w)}°`).join(", "))}</td></tr>`).join("");
  const flags = v.flags.map(f => `<span class="tag${f.normal ? "" : " bad"}">${esc(f.flag)} · ${f.rows} · ${esc(n1(f.first))} s</span>`).join(" ");
  const stats = v.filter_stats;
  const m = S.lgMap, md = S.lgMapData;
  const chOpts = sel => `<option value="">${esc(T("(auto)"))}</option>` + v.channels.map(c => `<option${c === sel ? " selected" : ""}>${esc(c)}</option>`).join("");
  const fl = {warm: T("warm engine only (coolant ≥ 80 °C)"), steady: T("no throttle transients"), no_overrun: T("no overrun fuel cut"),
              closed_loop: T("closed-loop lambda only")};
  const valOpts = `<option value="">${esc(T("knock and rows"))}</option>` +
    (v.trims.length ? `<optgroup label="${esc(T("fuel trims"))}">${v.trims.map(c => `<option${m && m.value_channel === c ? " selected" : ""}>${esc(c)}</option>`).join("")}</optgroup>` : "") +
    `<optgroup label="${esc(T("any channel (mean per cell)"))}">${v.channels.filter(c => !v.trims.includes(c)).map(c => `<option${m && m.value_channel === c ? " selected" : ""}>${esc(c)}</option>`).join("")}</optgroup>`;
  const cmpOpts = `<option value="">—</option>` + v.others.map(o => `<option${m && m.compare === o ? " selected" : ""}>${esc(o)}</option>`).join("");
  const mapPanel = v.problem ? `<div class="alert">${esc(T("No map overlay: {why}.", {why: v.problem}))}</div>` :
    !v.maps.length ? `<div class="muted">${esc(T("No maps with axes in the XDF of this firmware."))}</div>` :
    `<div class="srv-grid"><label>${esc(T("Map"))}<select id="lgMapSel">${v.maps.map(x => `<option value="${esc(x.title)}"${m && m.map === x.title ? " selected" : ""}>${esc(x.title)}</option>`).join("")}</select></label>
      <label>${esc(T("Row axis channel"))}<select id="lgY">${chOpts(m && m.y_channel)}</select></label>
      <label>${esc(T("Column axis channel"))}<select id="lgX">${chOpts(m && m.x_channel)}</select></label>
      <label>${esc(T("Cells show"))}<select id="lgVal">${valOpts}</select></label>
      <label>${esc(T("Compare with an earlier log (before)"))}<select id="lgCmp"${v.others.length ? "" : " disabled"}>${cmpOpts}</select></label></div>
     <div class="toolbar">${Object.keys(fl).map(f => `<button class="chip${m && m.filters && m.filters.includes(f) ? " on" : ""}" data-lgf="${f}">${esc(fl[f])}${typeof stats[f] === "number" ? ` <span class="muted">−${stats[f]}</span>` : ` <span class="muted">(${esc(stats[f])})</span>`}</button>`).join("")}</div>
     ${S.lgMapErr ? `<div class="alert">${esc(S.lgMapErr)}</div>` : md ? logMapHtml(md) + cellDetail(md) : ""}`;
  const range = S.lgRange;
  return `<section class="panel"><header><b>${esc(v.name)}</b>
      <span class="muted">${esc(T("{rows} rows · {dur} s · {rate} Hz", {rows: v.rows, dur: v.duration, rate: v.rate}))} · ${esc(T("firmware in the car: {name}", {name: v.firmware || "—"}))}${v.added ? " · " + esc(T("added {when}", {when: v.added})) : ""}</span>
      </header>
      ${v.problem ? `<div class="alert">⚠ ${esc(v.problem)}</div>` : ""}
      ${v.old ? `<div class="alert">${esc(T("This log was decoded by an older version of the decoder; some channels may be wrong. Its raw file is kept."))}
        <button class="btn" data-lgredecode="${esc(v.name)}">⟳ ${esc(T("Decode again"))}</button>
        <button class="btn" data-lgredecode="*">⟳ ${esc(T("Decode all such logs again"))}</button></div>` : ""}
      ${v.gaps.length ? `<div class="alert">${esc(T("Gaps in the recording: {list}", {list: v.gaps.map(g => n1(g[0]) + "→" + n1(g[1]) + " s").join(", ")}))}</div>` : ""}
      ${v.empty.length ? `<div class="alert">${esc(T("Empty in every row (not logged or not decoded): {list}", {list: v.empty.join(", ")}))}</div>` : ""}
      ${v.stuck.length ? `<div class="note warn">${esc(T("Never change (check before trusting): {list}", {list: v.stuck.join(", ")}))}</div>` : ""}
      ${v.constant.length ? `<details class="small muted"><summary>${esc(T("Constant in this log: {n} channel(s)", {n: v.constant.length}))}</summary>${esc(v.constant.join(", "))}</details>` : ""}</section>
    ${conditionsPanel(v)}
    <section class="panel"><header><b>${esc(T("Knock events: {n}", {n: v.events.length}))}</b><span class="muted">${esc(T("All of them, unfiltered. Click a row to zoom the chart."))}</span></header>
      ${v.events.length ? `<div class="mapwrap"><table class="plain"><tr><th>#</th><th>${esc(T("time, s"))}</th><th>${esc(T("detected"))}</th><th>rpm</th><th>${esc(T("load"))}</th><th>${esc(T("throttle"))}${v.throttle_units ? ", " + esc(v.throttle_units) : ""}</th><th>IAT</th><th>${esc(T("deepest per cylinder"))}</th></tr>${ev}</table></div>` : `<div class="muted">${esc(T("No knock in this log."))}</div>`}
      ${flags ? `<div>${esc(T("Flags that were ON:"))} ${flags}</div>` : ""}</section>
    <section class="panel"><header><b>${esc(T("Chart"))}</b><span class="muted">${esc(T("Drag across the chart to zoom. Red lines: knock detected."))}</span></header>
      <div class="toolbar"><select id="lgAddCh"><option value="">${esc(T("+ channel"))}</option>${v.channels.filter(c => !S.lgChart.includes(c)).map(c => `<option>${esc(c)}</option>`).join("")}</select>
        ${S.lgChart.map(c => `<button class="chip on" data-lgrm="${esc(c)}">${esc(c)} ×</button>`).join("")}
        ${range ? `<button class="btn" id="btnLgAll">${esc(T("Whole log"))}</button>` : ""}</div>
      ${logChart(S.lgSeries)}</section>
    <section class="panel"><header><b>${esc(T("Over the firmware map"))}</b>
      <span class="muted">${esc(T("Where the engine ran in this log and where knock was detected, on the map of the firmware the log was recorded on."))}</span></header>${mapPanel}</section>
    ${v.files.length ? `<section class="panel"><header><b>${esc(T("Claude's analysis"))}</b><span class="muted">analysis/</span></header>
      <div class="toolbar">${v.files.map(f => `<button class="chip${S.lgFile && S.lgFile.name === f.name ? " on" : ""}" data-lgfile="${esc(f.name)}">${f.kind === "image" ? "▣" : "≡"} ${esc(f.name)}</button>`).join("")}</div>
      ${S.lgFile ? (S.lgFile.image ? `<img class="lgimg" src="${S.lgFile.image}" alt="${esc(S.lgFile.name)}">` : `<pre class="lgtext">${esc(S.lgFile.text)}</pre>`) : ""}</section>` : ""}`;
}
function conditionsPanel(v) {
  if (!v.conditions) return "";
  const c = v.conditions, open = S.lgCondEdit || v.missing.length;
  const where = {"": "—", public_road: T("public road"), closed_road: T("closed road section"), track: T("track"), dyno: T("dyno")};
  const brief = [where[c.where] && c.where ? where[c.where] : "", c.fuel, c.air_temp, c.complaint,
                 c.changed ? T("changed: {what}", {what: c.changed}) : "", c.note].filter(Boolean).join(" · ");
  if (!open) return `<section class="panel"><header><b>${esc(T("Conditions"))}</b><span>${esc(brief)}</span></header>
      <div class="toolbar"><button class="btn" id="btnLgCondEdit">${esc(T("Edit"))}</button></div></section>`;
  const f = (id, label, val, ph) => `<label>${esc(label)}<input id="${id}" value="${esc(val)}" placeholder="${esc(ph)}"></label>`;
  return `<section class="panel"><header><b>${esc(T("Conditions"))}</b>
      <span class="muted">${esc(T("Claude reads this before judging the log. Can be edited at any time."))}</span></header>
    ${v.missing.length ? `<div class="alert">${esc(T("Not filled in — Claude will ask about it first."))}</div>` : ""}
    <div class="srv-grid">
      <label>${esc(T("Where"))}<select id="lcWhere">${Object.entries(where).map(([k, n]) => `<option value="${k}"${c.where === k ? " selected" : ""}>${esc(n)}</option>`).join("")}</select></label>
      ${f("lcFuel", T("Fuel"), c.fuel, T("98 RON"))}
      ${f("lcAir", T("Air temperature"), c.air_temp, "+12 °C")}
      ${f("lcComplaint", T("What bothers you"), c.complaint, T("rough idle, nothing"))}
      ${f("lcChanged", T("What changed since the previous log"), c.changed, T("nothing / firmware v3 / new plugs"))}
      ${f("lcNote", T("Note"), c.note, T("3rd gear pulls"))}</div>
    <div class="toolbar"><button class="btn primary" id="btnLgCondSave">${esc(T("Save"))}</button></div></section>`;
}
async function lgRefresh(what) {
  try {
    if (what === "series" || what === "both") await loadSeries();
    if (what === "map" || what === "both") await loadLogMap();
  } catch (err) { fail(err); }
  renderLogs();
}
$("view").addEventListener("click", async e => {
  if (S.view !== "logs") return;
  const t = e.target;
  try {
    const lg = t.closest("[data-lg]");
    if (lg) { S.lgRange = null; S.lgCell = null; return await openLog(lg.dataset.lg); }
    if (t.id === "btnLgAdd") {
      const r = await api("logs_add", {role: $("lgRole").value, note: $("lgNote").value}, T("Waiting for the file…"));
      S.lg = r;
      if (r.added) { S.lgNote = ""; S.lgRange = null; S.lgCell = null; await openLog(r.added, false); toast(esc(T("Log added: {name}", {name: r.added}))); }
      return renderLogs();
    }
    const rd = t.closest("[data-lgredecode]");
    if (rd) {
      const name = rd.dataset.lgredecode;
      const r = await api("logs_redecode", name === "*" ? {all: true} : {log: name}, T("Decoding…"));
      S.lg = r; if (r.message) toast(esc(r.message).replace(/\n/g, "<br>"));
      if (S.lgSel) await openLog(S.lgSel, false);
      return renderLogs();
    }
    if (t.id === "btnLgCondEdit") { S.lgCondEdit = true; return renderLogs(); }
    if (t.id === "btnLgCondSave") {
      const r = await api("logs_note", {log: S.lgV.name, conditions: {where: $("lcWhere").value, fuel: $("lcFuel").value,
        air_temp: $("lcAir").value, complaint: $("lcComplaint").value, changed: $("lcChanged").value, note: $("lcNote").value}});
      S.lgV.conditions = r.conditions; S.lgV.missing = r.missing; S.lgV.note = r.conditions.note; S.lgCondEdit = false;
      toast(esc(T("Saved.")));
      return renderLogs();
    }
    if (t.id === "btnLrPorts") { S.lr = await api("logger_state", {}); return renderLogs(); }
    if (t.id === "btnLrTest" || t.id === "btnLrStart") {
      const body = {port: $("lrPort").value, role: $("lgRole2").value, note: $("lrNote").value};
      S.lr = await api(t.id === "btnLrTest" ? "logger_test" : "logger_start", body,
                       t.id === "btnLrTest" ? T("Checking the connection…") : T("Connecting…"));
      return renderLogs();
    }
    if (t.id === "btnLrStop") {
      const r = await api("logger_stop", {}, T("Stopping…"));
      S.lr = r; S.lg = r.logs;
      if (r.status && r.status.rows) { S.lgRange = null; S.lgCell = null; await openLog(r.status.name, false); }
      return renderLogs();
    }
    if (t.id === "btnLgAdx") { S.lg = await api("logs_pick_adx", {}); return renderLogs(); }
    const zoom = t.closest("[data-lgzoom]");
    if (zoom) { const [a, b] = zoom.dataset.lgzoom.split(",").map(Number); S.lgRange = [Math.max(S.lgV.t0, a), Math.min(S.lgV.t1, b)]; return lgRefresh("series"); }
    if (t.id === "btnLgAll") { S.lgRange = null; return lgRefresh("series"); }
    const rm = t.closest("[data-lgrm]");
    if (rm) { S.lgChart = S.lgChart.filter(c => c !== rm.dataset.lgrm); return lgRefresh("series"); }
    const f = t.closest("[data-lgf]");
    if (f && S.lgMap) {
      const set = new Set(S.lgMap.filters || []);
      set.has(f.dataset.lgf) ? set.delete(f.dataset.lgf) : set.add(f.dataset.lgf);
      S.lgMap.filters = [...set]; S.lgCell = null;
      return lgRefresh("map");
    }
    const cell = t.closest("[data-lgcell]");
    if (cell) { S.lgCell = cell.dataset.lgcell.split(",").map(Number); return renderLogs(); }
    const file = t.closest("[data-lgfile]");
    if (file) { S.lgFile = S.lgFile && S.lgFile.name === file.dataset.lgfile ? null : await api("logs_file", {file: file.dataset.lgfile}); return renderLogs(); }
  } catch (err) { fail(err); }
});
$("view").addEventListener("change", e => {
  if (S.view !== "logs") return;
  const id = e.target.id;
  if (id === "lgRole" || id === "lgRole2") S.lgRole = e.target.value;
  if (id === "lrPort") S.lrPort = e.target.value;
  if (id === "lgAddCh" && e.target.value) { S.lgChart.push(e.target.value); lgRefresh("series"); }
  if (id === "lgMapSel") { S.lgMap = Object.assign({}, S.lgMap || {}, {map: e.target.value, y_channel: "", x_channel: ""}); S.lgCell = null; lgRefresh("map"); }
  if (id === "lgVal") {
    const ch = e.target.value;
    S.lgMap.value_channel = ch;
    const trim = ch && (S.lgV.trims.includes(ch) || /Lambda/.test(ch));
    const f = new Set(S.lgMap.filters || ["warm", "steady", "no_overrun"]);
    trim ? f.add("closed_loop") : f.delete("closed_loop");
    S.lgMap.filters = [...f]; S.lgCell = null; lgRefresh("map");
  }
  if (id === "lgCmp") { S.lgMap.compare = e.target.value; S.lgCell = null; lgRefresh("map"); }
  if (id === "lgY" || id === "lgX") { S.lgMap[id === "lgY" ? "y_channel" : "x_channel"] = e.target.value; S.lgCell = null; lgRefresh("map"); }
});
$("view").addEventListener("input", e => {
  if (S.view === "logs" && e.target.id === "lgNote") S.lgNote = e.target.value;
  if (S.view === "logs" && e.target.id === "lrNote") S.lrNote = e.target.value;
  const lc = {lcFuel: "fuel", lcAir: "air_temp", lcComplaint: "complaint", lcChanged: "changed", lcNote: "note", lcWhere: "where"}[e.target.id];
  if (S.view === "logs" && lc && S.lgV && S.lgV.conditions) { S.lgV.conditions[lc] = e.target.value; S.lgCondEdit = true; }
});
// drag across the chart to zoom into that time range
let lgDrag = null;
$("view").addEventListener("mousedown", e => {
  const svg = e.target.closest && e.target.closest("#lgChart");
  if (!svg || S.view !== "logs") return;
  const box = svg.getBoundingClientRect(), W = Number(svg.dataset.w), L = Number(svg.dataset.l);
  const toX = cx => Math.max(L, Math.min(W - 10, (cx - box.left) / box.width * W));
  lgDrag = {svg, toX, x0: toX(e.clientX)};
  e.preventDefault();
});
addEventListener("mousemove", e => {
  if (!lgDrag) return;
  const x = lgDrag.toX(e.clientX), sel = $("lgSel");
  sel.setAttribute("visibility", "visible");
  sel.setAttribute("x", Math.min(x, lgDrag.x0)); sel.setAttribute("width", Math.abs(x - lgDrag.x0));
});
addEventListener("mouseup", e => {
  if (!lgDrag) return;
  const d = lgDrag; lgDrag = null;
  const x1 = d.toX(e.clientX);
  if (Math.abs(x1 - d.x0) < 6) { const sel = $("lgSel"); if (sel) sel.setAttribute("visibility", "hidden"); return; }
  const svg = d.svg, W = Number(svg.dataset.w), L = Number(svg.dataset.l), a = Number(svg.dataset.from), b = Number(svg.dataset.to);
  const tm = x => a + (x - L) / (W - L - 10) * (b - a);
  S.lgRange = [tm(Math.min(x1, d.x0)), tm(Math.max(x1, d.x0))];
  lgRefresh("series");
});

// ---------------------------------------------------------------- Reference
async function loadWiki() {
  try {
    S.wk = await api("wiki", {query: S.wq, cautions: S.wcaut});
    if (S.wk.job && !S.wjob) { S.wjob = S.wk.job; wikiPoll(); }
    renderWiki();
  } catch (err) { fail(err); }
}
function renderWiki() {
  const w = S.wk;
  const head = `<div class="top"><div><h1>${esc(T("Reference"))}</h1>
    <div class="sub">${esc(w.available ? T("MS4X Wiki, snapshot of {date} · pages {pages} of {expected} · parameters linked {params} · source {source}", {date: w.fetched, pages: w.pages, expected: w.expected, params: w.params, source: w.source}) : T("MS4X Wiki offline"))}</div>
    ${w.available ? (w.missing.length ? `<div class="alert">${esc(T("The reference is incomplete, missing pages: {list}", {list: w.missing.join(", ")}))}<br>${esc(T("Press \"Update from site\" again: pages that are already there are kept."))}</div>`
                                      : `<div class="tag ok">✓ ${esc(T("Complete: all {n} pages", {n: w.expected}))}</div>`) : ""}
    ${w.available && (w.extra.length || w.skipped.length) ? `<details class="small"><summary>${esc(T("Found on the site: {added} MS43 page(s) added, {skipped} other page(s) skipped", {added: w.extra.length, skipped: w.skipped.length}))}</summary>
      ${w.extra.length ? `<div>${esc(T("Added:"))} ${esc(w.extra.join(", "))}</div>` : ""}
      ${w.skipped.length ? `<div class="muted">${esc(T("Skipped (not about the MS43) — click to add one anyway:"))}</div>
        <div class="toolbar">${w.skipped.map(n => `<button class="chip" data-wadd="${esc(n)}">+ ${esc(n)}</button>`).join("")}</div>` : ""}</details>` : ""}</div>
    ${wikiJobHtml()}
    <div class="actions"><button class="btn" id="btnWikiDl"${S.wjob ? " disabled" : ""}>${esc(T("Update from site"))}</button>
      <button class="btn" id="btnWikiImp">${esc(T("Import from file…"))}</button>
      ${w.available ? `<button class="btn" id="btnWikiExp">${esc(T("Save a copy…"))}</button>` : ""}</div></div>`;
  if (!w.available) {
    $("view").innerHTML = head + `<div class="start"><h2>${esc(T("There is no local copy of the reference yet"))}</h2>
      <p>${esc(T("The program will download pages from ms4x.net into the local copy.\nIt needs access to the site.\n\nContinue?").split("\n")[0])}</p>
      <p>${esc(T("Without the reference the AI assistant still reads the firmware and the XDF, but cannot check what a parameter does — it must say so."))}</p>
      <div class="actions"><button class="btn primary big" id="btnWikiDl2"${S.wjob ? " disabled" : ""}>${esc(T("Update from site"))}</button>
        <button class="btn big" id="btnWikiImp2">${esc(T("Import from file…"))}</button></div>
      <p class="muted small">${esc(w.hint || "")}</p></div>`;
    return;
  }
  const keepFocus = document.activeElement && document.activeElement.id === "wq";
  $("view").innerHTML = head + `<div class="toolbar"><div class="search"><input id="wq" placeholder="${esc(T("Search the reference: lambda, boost, checksum…"))}" value="${esc(S.wq)}"></div>
      <button class="chip${S.wcaut ? " on" : ""}" id="btnCaut">⚠ ${esc(T("All warnings"))}</button></div>
    <div class="browse"><nav class="cats wikilist">${w.sections.map(s =>
      `<button class="cat-btn${S.wsel === s.id ? " on" : ""}" data-wsec="${s.id}"><span>${s.caution ? "⚠ " : ""}${esc(s.heading)}<small class="muted">${esc(s.page)}</small></span></button>`).join("") ||
      `<div class="muted">${esc(T("Nothing found."))}</div>`}</nav>
    <div class="browse-main wikitext">${S.wtext ? wikiTextHtml(S.wtext) : `<div class="empty-state"><b>${esc(T("Choose a section on the left"))}</b>${esc(T("Sections: {n}", {n: w.sections.length}))}</div>`}</div></div>`;
  if (keepFocus) { const q = $("wq"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
function wikiJobHtml() {
  const j = S.wjob;
  if (!j) return "";
  const stage = {pages: T("Downloading pages"), listing: T("Reading the list of pages on the site…"),
                 new: T("Checking new pages on the site")}[j.stage] || "";
  const pct = j.n ? Math.round(100 * j.i / j.n) : 0;
  return `<div class="wjob"><div class="small"><b>${esc(stage)}</b>${j.n ? ` ${j.i} / ${j.n}` : ""}${j.name ? ` · <span class="muted">${esc(j.name)}</span>` : ""}</div>
    <div class="bar${j.n ? "" : " indet"}"><div style="width:${j.n ? pct : 100}%"></div></div></div>`;
}
let wjobTimer = null;
function wikiPoll() {
  clearTimeout(wjobTimer);
  wjobTimer = setTimeout(async () => {
    let r;
    try { r = await api("wiki_progress", {}); } catch (err) { S.wjob = null; fail(err); return; }
    if (!r.job) { S.wjob = null; if (S.view === "wiki") renderWiki(); return; }
    if (!r.job.done) {
      S.wjob = r.job;
      if (S.view === "wiki") { const el = document.querySelector(".wjob"); if (el) el.outerHTML = wikiJobHtml(); else renderWiki(); }
      return wikiPoll();
    }
    S.wjob = null; S.wk = r; S.wsel = null; S.wtext = null;
    if (S.view === "wiki") renderWiki();
    toast((r.message ? esc(r.message) : esc(T("Pages downloaded: {n}", {n: r.downloaded}))).replace(/\n/g, "<br>") +
          (r.errors && r.errors.length ? "<br>" + esc(T("Failed:")) + " " + esc(r.errors.slice(0, 5).join("; ")) : ""), !r.written);
  }, 400);
}
function wikiTextHtml(x) {
  return `<h2 class="h2">${esc(x.heading)}</h2><div class="muted small">${esc(x.page)}</div>
    ${x.lines.map(l => `<p class="${l.warn ? "warnbox" : ""}">${l.warn ? "⚠ " : ""}${esc(l.text)}</p>`).join("")}
    ${x.translated ? `<details class="orig"><summary>${esc(T("original (English)"))}</summary>${x.lines.map(l => `<p>${esc(l.orig)}</p>`).join("")}</details>` : ""}
    <a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.url)}</a>`;
}
$("view").addEventListener("click", async e => {
  if (S.view !== "wiki") return;
  const t = e.target, sec = t.closest("[data-wsec]");
  if (sec) {
    S.wsel = Number(sec.dataset.wsec);
    try { S.wtext = await api("wiki_section", {id: S.wsel}); renderWiki(); } catch (err) { fail(err); }
    return;
  }
  const wadd = t.closest("[data-wadd]");
  if (wadd) {
    try {
      S.wk = await api("wiki_add", {page: wadd.dataset.wadd}, T("Downloading the reference…"));
      S.wsel = null; S.wtext = null; renderWiki();
      if (S.wk.message) toast(esc(S.wk.message).replace(/\n/g, "<br>"));
    } catch (err) { fail(err); }
    return;
  }
  if (t.id === "btnCaut") { S.wcaut = !S.wcaut; S.wsel = null; S.wtext = null; return loadWiki(); }
  if (t.id === "btnWikiDl" || t.id === "btnWikiDl2") {
    try {
      const r = await api("wiki_download", {});
      S.wk = r; S.wjob = r.job; renderWiki(); wikiPoll();
    } catch (err) { fail(err); }
    return;
  }
  if (t.id === "btnWikiImp" || t.id === "btnWikiImp2" || t.id === "btnWikiExp") {
    try {
      S.wk = await api(t.id === "btnWikiExp" ? "wiki_export" : "wiki_import", {});
      S.wsel = null; S.wtext = null; renderWiki();
      if (S.wk.message) toast(esc(S.wk.message).replace(/\n/g, "<br>"));
    } catch (err) { fail(err); }
  }
});
$("view").addEventListener("input", e => {
  if (e.target.id === "wq") { S.wq = e.target.value; S.wcaut = false; debounce(() => { S.wsel = null; S.wtext = null; loadWiki(); }); }
});

// ---------------------------------------------------------------- drawer
async function openParam(title, opts) {
  S.selected = title;
  markSelected();
  try {
    const p = await api("param", Object.assign({title}, opts || {}));
    $("drawerIn").innerHTML = drawerHtml(p);
    $("drawer").classList.add("open");
  } catch (err) { fail(err); }
}
function closeDrawer() {
  $("drawer").classList.remove("open");
  S.selected = null;
  markSelected();
}
function drawerHtml(p) {
  const sec = (title, html) => html ? `<h3>${esc(title)}</h3>${html}` : "";
  return `<button class="x" id="btnClose" title="${esc(T("Close"))}">×</button>
    <h2 class="mono">${esc(p.title)}</h2>
    <div class="pname">${esc(p.name)}</div><div class="kind">${esc(p.kind)}${p.units ? " · " + esc(p.units) : ""}</div>
    ${p.desc && p.desc !== p.name ? `<p class="desc">${esc(p.desc)}</p>` : ""}
    ${"value" in p ? sec(T("Value in the firmware"), `<div class="ba one"><div><b>${esc(p.value)}${p.units ? " " + esc(p.units) : ""}</b></div></div>`) : ""}
    ${"a" in p ? sec(T("Before → after"), `<div class="ba"><div><span>${esc(fwLabel("bin_a", "A"))}</span><b>${esc(p.a)}</b></div>
      <div><span>${esc(fwLabel("bin_b", "B"))}</span><b>${esc(p.b)}</b></div></div>`) : ""}
    ${sec(T("What the values mean"), p.meanings.map(([v, m]) => `<div class="note"><b>${esc(v)}</b> — ${esc(m)}</div>`).join(""))}
    ${sec(T("What it does"), p.note ? `<div class="note">${esc(p.note)}</div>` : "")}
    ${sec(T("How to tune"), p.tune ? `<div class="note">${esc(p.tune)}</div>` : "")}
    ${sec(T("After the change"), p.steps.map(s => `<div class="note">${esc(s)}</div>`).join(""))}
    ${sec(T("Warnings"), p.warnings.map(w => `<div class="warnbox">⚠ ${esc(w)}</div>`).join(""))}
    ${sec(T("Details"), `<div class="facts">${p.facts.map(([k, v]) => `<span>${esc(k)}</span><b class="mono">${esc(v)}</b>`).join("")}</div>
      ${p.desc_orig ? `<details class="orig"><summary>${esc(T("original description (English)"))}</summary><p>${esc(p.desc_orig)}</p></details>` : ""}`)}
    ${sec("MS4X Wiki", p.wiki.length ? `<div class="wiki">${p.wiki.map(w => `<div class="head">${esc(w.head)}</div>
      <p>${esc(w.text)}</p>${w.orig ? `<details class="orig"><summary>${esc(T("original (English)"))}</summary><p>${esc(w.orig)}</p></details>` : ""}
      <a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.url)}</a>`).join("")}</div>`
      : `<div class="kind">${esc(T("The local reference says nothing about this parameter. Download it in the Reference mode."))}</div>`)}`;
}
$("drawer").addEventListener("click", e => { if (e.target.id === "btnClose") closeDrawer(); });
addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

// ---------------------------------------------------------------- start
(async function init() {
  try {
    S.state = await api("state");
    S.view = sessionStorage.getItem("ms43view") || "ai";
    sessionStorage.removeItem("ms43view");
    renderSide();
    if (S.state.has_compare) await runCompare(true);
    else renderView();
  } catch (err) { fail(err); }
})();
