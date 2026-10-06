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
api("ping").catch(() => {});
setInterval(() => api("ping").catch(() => {}), 20000);
addEventListener("pagehide", () => {
  if (reloading) return;
  fetch("/api/bye", {method: "POST", keepalive: true,
    headers: {"Content-Type": "application/json", "X-Token": BOOT.token}, body: "{}"});
});

// ---------------------------------------------------------------- state
const S = {state: null, view: "cmp", cmp: null, filter: "", chip: "all", selected: null,
           maps: {}, fw: {browse: "bin_b", cross: "bin_b", patch: "bin_b", ve: "bin_b"},
           br: null, brq: "", brcat: "", crossTab: "cmp", cr: null, pp: null, pt: null,
           ptFilter: "all", ve: null, veSetup: null, veCols: {}, veConfirm: false,
           wk: null, wq: "", wsel: null, wtext: null};

const NAV = [
  ["cmp", "⇄", T("Compare A and B"), T("what was changed in the tune")],
  ["browse", "⌕", T("Browse firmware"), T("search, all maps and values")],
  ["cross", "⇆", T("Different software versions"), T("compare and port edits")],
  ["patch", "✓", T("Patches"), T("which are applied")],
  ["ve", "∿", T("VE tuning"), T("map correction from a log")],
  ["wiki", "❡", T("Reference"), T("MS4X Wiki offline")],
  ["ai", "✦", T("AI assistant"), T("connect to Claude")],
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
  if (role === "velog" || role.startsWith("bin") || role.startsWith("xdf")) { S.ve = null; S.veSetup = null; }
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
                 patch: renderPatches, ve: loadVe, wiki: loadWiki};
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
    if (fw.dataset.fwkey === "ve") { S.ve = null; S.veSetup = null; }
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
  if (row) openParam(row.dataset.title, {source: row.dataset.src || "cmp", role: row.dataset.role});
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
function desktopCard(e) {
  return `<div class="srv" data-desk="${esc(e.name)}">
    <div class="srv-top"><b class="mono">${esc(e.name)}</b>
      ${e.problems.length ? `<span class="pill bad">! ${esc(T("needs attention"))}</span>` : `<span class="pill ok">✓ ${esc(T("in the config"))}</span>`}
      <span class="grow"></span>
      <button class="btn" data-desk-act="desk_check">${esc(T("Check"))}</button>
      <button class="btn" data-desk-act="desk_remove">${esc(T("Disconnect"))}</button></div>
    <div class="facts"><span>XDF</span><b class="mono">${esc(e.xdf || "—")}</b>
      <span>${esc(T("Firmware"))}</span><b class="mono">${esc(e.bin || "—")}</b>
      <span>${esc(T("Answer language"))}</span><b>${esc(e.lang || "—")}</b></div>
    ${e.problems.map(p => `<div class="warn">${esc(p)} — ${esc(T("connect it again below."))}</div>`).join("")}
    ${checkHtml((S.aiChecks || {})["desk:" + e.name])}
  </div>`;
}
function renderAI() {
  const a = S.ai, d = a.desktop;
  const questions = [T("What is my rev limit, and is it higher than stock?"),
    T("Show the ignition map ip_iga_ron98_pl__n__maf."),
    T("What does c_conf_cat = 4 mean, and what breaks if I change it?"),
    T("I am removing the catalysts — what do I change and what matters?")];
  $("view").innerHTML = `<h1>${esc(T("AI assistant"))}</h1>
    <div class="sub">${esc(T("Let Claude read your firmware and the MS4X Wiki and answer questions about it. Read-only: nothing is ever written to the firmware."))}</div>
    <section class="panel"><header><b>${esc(T("Claude Code — live server"))}</b>
      <span class="muted">${esc(T("Runs while this window is open. Choosing another file in the project takes effect at once, no restart of Claude Code needed."))}</span></header>
      ${a.servers.map(serverCard).join("")}
      <button class="btn" data-ai-add="1">+ ${esc(T("Add a server"))}</button>
      <span class="muted small">${esc(T("Several servers can run at once, e.g. one for the stock and one for the tune."))}</span>
    </section>
    <section class="panel"><header><b>Claude Desktop</b>
      <span class="muted">${esc(T("Claude Desktop starts the server itself from its config file. After a change, quit Claude Desktop completely (tray icon → Quit) and start it again."))}</span></header>
      ${d.running ? `<div class="alert">${esc(T("Claude Desktop is running now. Quit it before connecting, otherwise it may overwrite the change."))}</div>` : ""}
      ${d.entries.map(desktopCard).join("") || `<div class="muted">${esc(T("No ms43 servers in the Claude Desktop config yet."))}</div>`}
      <div class="srv"><div class="srv-grid">
        <label>${esc(T("Server name"))}<input id="deskName" class="mono" value="${esc(d.entries.length ? d.entries[0].name : "ms43")}"></label>
        <label>${esc(T("Firmware the AI sees"))}<select id="deskRole">${roleOptions("bin_b")}</select></label>
        <label>${esc(T("Answer language"))}<select id="deskLang">${langOptions(S.state.lang)}</select></label>
      </div><div class="srv-code"><span class="muted small mono">${esc(d.config)}</span><span class="grow"></span>
        <button class="btn primary" id="deskInstall">${esc(T("Connect / update"))}</button></div></div>
    </section>
    <section class="panel"><header><b>${esc(T("What to ask"))}</b></header>
      ${questions.map(q => `<div class="note">${esc(q)}</div>`).join("")}</section>`;
}
async function aiAction(name, body, busyText) {
  try {
    const r = await api(name, body, busyText);
    if (r.check) (S.aiChecks = S.aiChecks || {})[(name.startsWith("desk") ? "desk:" : "code:") + body.name] = r.check;
    S.ai = r;
    renderAI();
    if (r.message) toast(esc(r.message).replace(/\n/g, "<br>"));
  } catch (err) { fail(err); }
}
$("view").addEventListener("click", e => {
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
  const act = t.closest("[data-ai]");
  if (act) {
    const name = act.closest("[data-srv]").dataset.srv;
    const body = {name};
    if (act.dataset.ai === "ai_code") body.register = !!act.dataset.register;
    const busyText = {ai_check: T("Checking the server…"), ai_code: T("Talking to Claude Code…")}[act.dataset.ai];
    return aiAction(act.dataset.ai, body, busyText);
  }
  const desk = t.closest("[data-desk-act]");
  if (desk) {
    const name = desk.closest("[data-desk]").dataset.desk;
    return aiAction(desk.dataset.deskAct, {name}, desk.dataset.deskAct === "desk_check" ? T("Checking the server…") : null);
  }
  if (t.id === "deskInstall") {
    return aiAction("desk_install", {name: $("deskName").value.trim(), role: $("deskRole").value,
                                     lang: $("deskLang").value});
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
  bin2: T("Firmware of the other version"), patchlist: T("Patchlist XDF"), velog: T("Log (CSV)")});
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

// ---------------------------------------------------------------- VE tuning
async function loadVe() {
  const role = S.fw.ve, need = [role === "bin2" ? "xdf2" : "xdf", role];
  if (!missing(need).length && !S.veSetup) {
    try { S.veSetup = await api("ve_setup", {role}); } catch (err) { fail(err); }
  }
  renderVe();
}
function renderVe() {
  const role = S.fw.ve, need = [role === "bin2" ? "xdf2" : "xdf", role, "velog"];
  const st = S.veSetup, f = S.state.files;
  let html = `<h1>${esc(T("VE tuning"))}</h1>
    <div class="sub">${esc(T("Correction of the VE map from a wideband lambda log: if the mixture is leaner than the target, there was more air than the ECU thought. Cells with too few samples are left alone."))}</div>
    ${fwSwitch("ve", ["bin_a", "bin_b", "bin2"])}${fileCard("velog", T("Log (CSV)"), T("choose the wideband log (.csv)"))}`;
  if (missing(need).length || !st) {
    $("view").innerHTML = html + needBox(need, "", "", "", "");
    return;
  }
  const v = S.vePrev || {};
  const sel = (id, opts, cur) => `<select id="${id}">${opts.map(([val, label]) => `<option value="${esc(val)}"${val === cur ? " selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
  const colOpts = [["", "—"]].concat(st.columns.map(c => [c, c]));
  const colLabels = {rpm: T("engine speed"), load: T("load / air mass"), lambda: T("wideband lambda"),
    target: T("target lambda"), trim: T("fuel trim"), coolant: T("coolant temperature")};
  html += `<section class="panel"><header><b>${esc(T("Settings"))}</b>
      <span class="muted">${esc(T("Log: {rows} rows, {cols} columns. Check that the columns are recognised right.", {rows: st.rows, cols: st.columns.length}))}</span></header>
    ${st.log_error ? `<div class="alert">${esc(st.log_error)}</div>` : ""}
    <div class="srv-grid"><label>${esc(T("Map"))}${sel("veMap", st.maps.map(m => [m, m]), v.map || st.maps[0])}</label>
      <label>${esc(T("Mode"))}${sel("veMode", [["lambda", T("by the sensor (open loop)")], ["trim", T("by the fuel trims")], ["both", T("both (closed loop)")]], v.mode || "lambda")}</label>
      <label>${esc(T("Fuel"))}${sel("veFuel", [["gasoline", T("gasoline")], ["e85", "E85"], ["e10", "E10"], ["methanol", T("methanol")]], v.fuel || "gasoline")}</label></div>
    <div class="srv-grid">${Object.keys(colLabels).map(k => `<label>${esc(colLabels[k])}${sel("veCol_" + k, colOpts, (S.veCols[k] !== undefined ? S.veCols[k] : st.guess[k]) || "")}</label>`).join("")}</div>
    <div class="srv-grid"><label>${esc(T("target lambda"))}<input id="veTarget" type="number" step="0.01" value="${esc(v.target || "1.00")}"></label>
      <label>${esc(T("min. samples per cell"))}<input id="veMin" type="number" value="${esc(v.min_samples || "8")}"></label>
      <label>${esc(T("max. correction, %"))}<input id="veStep" type="number" value="${esc(v.max_step || "25")}"></label>
      <label>${esc(T("sensor delay"))}<input id="veDelay" type="number" value="${esc(v.delay || "0")}"></label></div>
    <div><button class="btn primary" id="btnVe">${esc(T("Calculate correction"))}</button></div></section>`;
  const r = S.ve;
  if (r) {
    html += `<div class="top"><div><h2 class="h2">${esc(r.name)}</h2><div class="sub mono">${esc(r.map)}</div></div>
      <div class="actions"><button class="btn" data-vesave="html">${esc(T("HTML report"))}</button>
      <button class="btn primary" id="btnVeWrite">${esc(T("Write a new .bin…"))}</button></div></div>
      ${S.veConfirm ? `<div class="alert"><b>${esc(T("Confirmation"))}</b><br>${esc(T("A NEW firmware file with the changed map will be created.\nThe source file is not changed.\n\nCells to change: {n}\n\nIMPORTANT: checksums are not recalculated — do it in TunerPro.", {n: r.stats.changed}))}
        <div class="actions" style="margin-top:8px"><button class="btn primary" data-vesave="bin">${esc(T("Write"))}</button><button class="btn" id="btnVeCancel">${esc(T("Cancel"))}</button></div></div>` : ""}
      ${statsHtml([[r.stats.used + " / " + r.stats.total, T("samples used")], [r.stats.coverage + "%", T("map coverage")], [r.stats.changed, T("cells changed")], [r.skipped.reduce((a, s) => a + s[1], 0), T("samples dropped")]])}
      ${r.skipped.length ? `<div class="muted small">${r.skipped.map(([k, n]) => esc(k) + ": " + n).join(" · ")}</div>` : ""}
      ${r.notes.map(n => `<div class="warnbox">⚠ ${esc(n)}</div>`).join("")}
      <section class="cat"><header>${esc(T("Proposed correction"))}<span>${esc(T("the small number in a cell is how many log samples landed there"))}</span></header>
        <div style="padding:8px 16px 14px">${mapHtml(r.grid)}</div></section>
      ${r.wiki.length ? `<section class="cat"><header>${esc(T("What the MS4X Wiki says about it"))}<span>${r.wiki.length}</span></header><div class="wiki" style="padding:4px 16px 14px">${r.wiki.map(w =>
        `<div class="head">${esc(w.head)}</div><p>${esc(w.text)}</p>${w.orig ? `<details class="orig"><summary>${esc(T("original (English)"))}</summary><p>${esc(w.orig)}</p></details>` : ""}<a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.url)}</a>`).join("")}</div></section>` : ""}`;
  }
  $("view").innerHTML = html;
}
$("view").addEventListener("click", async e => {
  if (S.view !== "ve") return;
  const t = e.target;
  if (t.id === "btnVe") {
    const columns = {};
    for (const k of ["rpm", "load", "lambda", "target", "trim", "coolant"]) columns[k] = S.veCols[k] = $("veCol_" + k).value;
    S.vePrev = {map: $("veMap").value, mode: $("veMode").value, fuel: $("veFuel").value, target: $("veTarget").value,
                min_samples: $("veMin").value, max_step: $("veStep").value, delay: $("veDelay").value};
    try {
      S.ve = await api("ve_run", Object.assign({role: S.fw.ve, columns}, S.vePrev), T("Calculating the correction…"));
      S.veConfirm = false;
      renderVe();
    } catch (err) { fail(err); }
  }
  if (t.id === "btnVeWrite") { S.veConfirm = true; return renderVe(); }
  if (t.id === "btnVeCancel") { S.veConfirm = false; return renderVe(); }
  const save = t.closest("[data-vesave]");
  if (save) {
    try {
      const r = await api("ve_save", {kind: save.dataset.vesave}, T("Saving…"));
      S.veConfirm = false;
      renderVe();
      if (r.path && save.dataset.vesave === "bin") {
        toast(esc(T("Cells written: {n}\nFile: {path}\n\nChecksums were NOT recalculated.", {n: r.cells, path: r.path})).replace(/\n/g, "<br>"));
      } else savedToast(r.path);
    } catch (err) { fail(err); }
  }
});

// ---------------------------------------------------------------- Reference
async function loadWiki() {
  try { S.wk = await api("wiki", {query: S.wq, cautions: S.wcaut}); renderWiki(); } catch (err) { fail(err); }
}
function renderWiki() {
  const w = S.wk;
  const head = `<div class="top"><div><h1>${esc(T("Reference"))}</h1>
    <div class="sub">${esc(w.available ? T("MS4X Wiki, snapshot of {date} · pages {pages} · parameters linked {params} · source {source}", {date: w.fetched, pages: w.pages, params: w.params, source: w.source}) : T("MS4X Wiki offline"))}</div></div>
    <div class="actions"><button class="btn" id="btnWikiDl">${esc(T("Update from site"))}</button></div></div>`;
  if (!w.available) {
    $("view").innerHTML = head + `<div class="start"><h2>${esc(T("There is no local copy of the reference yet"))}</h2>
      <p>${esc(T("The program will download pages from ms4x.net into the local copy.\nIt needs access to the site.\n\nContinue?").split("\n")[0])}</p>
      <button class="btn primary big" id="btnWikiDl2">${esc(T("Update from site"))}</button></div>`;
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
  if (t.id === "btnCaut") { S.wcaut = !S.wcaut; S.wsel = null; S.wtext = null; return loadWiki(); }
  if (t.id === "btnWikiDl" || t.id === "btnWikiDl2") {
    try {
      S.wk = await api("wiki_download", {}, T("Downloading the reference…"));
      S.wsel = null; S.wtext = null; renderWiki();
      toast(esc(T("Pages downloaded: {n}\nCache: {path}", {n: S.wk.downloaded, path: ""})).replace(/\n/g, "<br>") +
            (S.wk.errors.length ? "<br>" + esc(T("Failed:")) + " " + esc(S.wk.errors.join("; ")) : ""));
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
    S.view = sessionStorage.getItem("ms43view") || "cmp";
    sessionStorage.removeItem("ms43view");
    renderSide();
    if (S.state.has_compare) await runCompare(true);
    else renderView();
  } catch (err) { fail(err); }
})();
