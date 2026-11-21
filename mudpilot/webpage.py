"""The phone page itself (served by webremote.py). Plain HTML/CSS/JS, no outside libraries, no inline
script or style (the page's Content-Security-Policy forbids both)."""

HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#15171c">
<meta name="referrer" content="no-referrer">
<title>MudPilot</title>
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icon.svg">
<link rel="stylesheet" href="/app.css">
</head>
<body>
<main id="pair" hidden>
  <h1>MudPilot</h1>
  <p>On the PC: Settings &rarr; Phone alerts &rarr; <b>Pair a phone</b>, then type the 6-digit code here.</p>
  <form id="pairform">
    <input id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="123456">
    <button type="submit">Pair</button>
  </form>
  <p id="pairmsg" class="err"></p>
</main>
<main id="list" hidden>
  <header><h1>MudPilot</h1><span id="total" class="mut"></span></header>
  <div id="cards"></div>
  <p id="listmsg" class="mut small"></p>
</main>
<main id="char" hidden>
  <header>
    <button id="back" class="icon" aria-label="All characters">&#8249;</button>
    <h1 id="cname"></h1>
    <span id="cpill" class="pill"></span>
  </header>
  <section id="cstats"></section>
  <section id="cparty"></section>
  <div class="termbar"><span class="mut small">Screen</span>
    <span><button id="fminus" class="small">A&minus;</button><button id="fplus" class="small">A+</button></span></div>
  <pre id="term"></pre>
  <p class="mut small foot">Watch-only. MudPilot keeps running on the PC whether this page is open or not.</p>
</main>
<script src="/app.js"></script>
</body>
</html>
'''

CSS = r''':root{--bg:#15171c;--card:#1e2128;--line:#2c3039;--text:#e6e6e6;--mut:#9aa0aa;--ok:#5cb85c;
--warn:#e0a030;--bad:#e05050;--hp:#5cb85c;--ma:#4a90e2;--acc:#7aa7ff}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:720px;margin:0 auto;padding:12px 12px calc(16px + env(safe-area-inset-bottom))}
header{display:flex;align-items:center;gap:10px;margin:2px 0 10px}
h1{font-size:20px;font-weight:600;margin:0;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
button{background:var(--card);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 14px;font:inherit}
button:active{transform:scale(.97)}
button.icon{font-size:26px;line-height:1;padding:2px 12px 6px}
button.small,.small{font-size:12px}
button.small{padding:4px 10px;margin-left:6px}
input{background:var(--card);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:22px;
letter-spacing:6px;width:9em;text-align:center}
form{display:flex;gap:10px;align-items:center;margin:16px 0}
.mut{color:var(--mut)}
.err{color:var(--bad)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;margin-bottom:8px;cursor:pointer}
.card.off{opacity:.6}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.name{font-weight:600;font-size:16px}
.sub{color:var(--mut);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar{height:6px;border-radius:3px;background:#2a2e36;overflow:hidden;margin-top:5px}
.bar i{display:block;height:100%;background:var(--hp)}
.bar.ma i{background:var(--ma)}
.bar.mid i{background:var(--warn)}
.bar.low i{background:var(--bad)}
.pill{font-size:12px;padding:2px 9px;border-radius:10px;background:#2a2e36;color:var(--mut);white-space:nowrap}
.pill.ok{background:#1f3a24;color:#8fd89a}
.pill.fight{background:#3d2f12;color:#f0c060}
.pill.bad{background:#3d1a1a;color:#f08a8a}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:8px 0}
.tile{background:var(--card);border-radius:10px;padding:6px 8px;min-width:0}
.tile .k{color:var(--mut);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile .v{font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tile.wide{grid-column:1/-1}
.tile.wide .v{font-size:14px;font-weight:500;white-space:normal}
.hpline{display:flex;justify-content:space-between;font-size:13px;color:var(--mut);margin-top:8px}
#cparty .p{display:flex;justify-content:space-between;font-size:14px;padding:5px 0;border-top:1px solid var(--line)}
#cparty .p:first-of-type{border-top:0}
#cparty{background:var(--card);border-radius:10px;padding:6px 10px;margin-bottom:10px}
#cparty:empty{display:none}
.termbar{display:flex;justify-content:space-between;align-items:center;margin:6px 0 4px}
#term{background:#0b0c0f;color:#c8c8c8;border-radius:10px;padding:8px;margin:0;height:60vh;overflow-y:auto;
font:12px/1.35 ui-monospace,"Cascadia Mono",Consolas,"Roboto Mono",monospace;white-space:pre-wrap;word-break:break-word}
.c0{color:#7a7a7a}.c1{color:#c83c3c}.c2{color:#3cb43c}.c3{color:#c8a03c}.c4{color:#5a6ee6}.c5{color:#b450b4}
.c6{color:#3cb4b4}.c7{color:#c8c8c8}
.b.c0{color:#a0a0a0}.b.c1{color:#ff6464}.b.c2{color:#64ff64}.b.c3{color:#ffff64}.b.c4{color:#8296ff}
.b.c5{color:#ff78ff}.b.c6{color:#64ffff}.b.c7,.b.cx{color:#fff}
.foot{margin-top:10px}
'''

JS = r'''"use strict";
let view = "list";
let KEY = "";
try { KEY = localStorage.getItem("mpkey") || ""; } catch (e) {}
(function takeHash() {
  const h = location.hash || "";
  const k = h.match(/k=([A-Za-z0-9_-]+)/);
  if (k) { KEY = k[1]; try { localStorage.setItem("mpkey", KEY); } catch (e) {} }
  const v = h.match(/v=(\w+)/);
  if (v) view = v[1];
  if (h) history.replaceState(null, "", location.pathname);
})();

const $ = (id) => document.getElementById(id);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function fmt(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return Math.round(n / 1e3) + "k";
  return String(Math.round(n));
}
function dur(s) {
  s = Math.max(0, Math.round(Number(s) || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? h + "h " + m + "m" : m + "m";
}
function pct(a, b, p) {
  if (p !== undefined && p !== null) return Math.max(0, Math.min(100, Number(p)));
  return b ? Math.max(0, Math.min(100, 100 * a / b)) : null;
}
function bar(p, ma) {
  const b = el("div", "bar" + (ma ? " ma" : "") + (!ma && p !== null && p < 35 ? " low" : !ma && p !== null && p < 65 ? " mid" : ""));
  const i = el("i");
  i.style.width = (p === null ? 0 : p) + "%";
  b.appendChild(i);
  return b;
}
function pill(d) {
  if (!d.connected) return ["disconnected", "bad"];
  if (!d.in_game) return ["at the menu", "bad"];
  if (d.in_combat) return ["fighting", "fight"];
  if (d.walking) return ["walking", "ok"];
  return ["idle", ""];
}

async function api(path, opts) {
  const o = Object.assign({ cache: "no-store" }, opts || {});
  o.headers = Object.assign({ "X-MudPilot-Key": KEY }, o.headers || {});
  const r = await fetch(path, o);
  if (r.status === 403 && path !== "/api/pair") { show("pair"); throw new Error("not paired"); }
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

function show(v) {
  view = v;
  for (const id of ["pair", "list", "char"]) $(id).hidden = id !== v;
  if (v === "list") pollList(true);
  if (v === "char") { pollMe(true); pollScreen(true); }
}

// ---------------------------------------------------------------- pairing
$("pairform").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const code = $("code").value.trim();
  if (!/^\d{6}$/.test(code)) { $("pairmsg").textContent = "Type the 6 digits MudPilot shows."; return; }
  $("pairmsg").textContent = "";
  try {
    const r = await fetch("/api/pair", { method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
    if (!r.ok) { $("pairmsg").textContent = "That code didn't work (wrong, used up or over 5 minutes old)."; return; }
    KEY = (await r.json()).key || "";
    try { localStorage.setItem("mpkey", KEY); } catch (e) {}
    $("code").value = "";
    show("list");
  } catch (e) { $("pairmsg").textContent = "Couldn't reach MudPilot."; }
});
$("code").addEventListener("input", () => { $("pairmsg").textContent = ""; });

// ---------------------------------------------------------------- all characters
let listT = 0;
async function pollList(now) {
  clearTimeout(listT);
  if (view !== "list") return;
  if (!document.hidden || now) {
    try { renderList((await api("/api/peers")).peers || []); $("listmsg").textContent = ""; }
    catch (e) { if (view === "list") $("listmsg").textContent = "Can't reach MudPilot on the PC right now — retrying."; }
  }
  listT = setTimeout(pollList, 3000);
}
function renderList(peers) {
  const box = $("cards");
  box.replaceChildren();
  let total = 0, on = 0;
  for (const p of peers) {
    const live = p.fresh && p.connected;
    if (live) { total += Number(p.exp_hr) || 0; on++; }
    const c = el("div", "card" + (live ? "" : " off"));
    const r1 = el("div", "row");
    r1.appendChild(el("span", "name", p.name || p.folder));
    const [pt, pc] = p.fresh ? pill(p) : ["closed", "bad"];
    const right = el("span", "pill " + pc, live && p.exp_hr ? fmt(p.exp_hr) + "/hr" : pt);
    r1.appendChild(right);
    c.appendChild(r1);
    const where = p.room_name || (p.room ? "room " + p.room.join("/") : "");
    const who = p.leader ? "follows " + p.leader : (p.party && p.party.length ? "leads " + p.party.length : "");
    c.appendChild(el("div", "sub", [where, who].filter(Boolean).join(" · ") || p.folder));
    c.appendChild(el("div", "sub", p.fresh ? (p.status || "") : "not running (last seen " + dur(p.age) + " ago)"));
    if (live) {
      c.appendChild(bar(pct(p.hp, p.max_hp, p.hp_pct), false));
      c.appendChild(bar(pct(p.ma, p.max_ma, p.ma_pct), true));
    }
    c.addEventListener("click", () => openPeer(p));
    box.appendChild(c);
  }
  $("total").textContent = on ? on + " on · " + fmt(total) + "/hr" : "";
}
function openPeer(p) {
  if (p.me) { show("char"); return; }
  if (!p.port) { $("listmsg").textContent = (p.name || p.folder) + ": its phone page isn't on (tick it in that MudPilot's Settings)."; return; }
  location.href = "http://" + location.hostname + ":" + p.port + "/#k=" + encodeURIComponent(KEY) + "&v=char";
}

// ---------------------------------------------------------------- one character
let meT = 0;
async function pollMe(now) {
  clearTimeout(meT);
  if (view !== "char") return;
  if (!document.hidden || now) {
    try { renderMe(await api("/api/me")); } catch (e) {}
  }
  meT = setTimeout(pollMe, 2000);
}
function tile(k, v, wide) {
  const t = el("div", "tile" + (wide ? " wide" : ""));
  t.appendChild(el("div", "k", k));
  t.appendChild(el("div", "v", v));
  return t;
}
function renderMe(d) {
  if (!d || !d.t) return;
  $("cname").textContent = d.name || "MudPilot";
  document.title = (d.name || "MudPilot") + " — MudPilot";
  const [pt, pc] = pill(d);
  $("cpill").textContent = pt;
  $("cpill").className = "pill " + pc;
  const s = $("cstats");
  s.replaceChildren();
  const hp = el("div", "hpline");
  hp.appendChild(el("span", "", "HP " + (d.hp || 0) + "/" + (d.max_hp || 0)));
  hp.appendChild(el("span", "", "MA " + (d.ma || 0) + "/" + (d.max_ma || 0)));
  s.appendChild(hp);
  s.appendChild(bar(pct(d.hp, d.max_hp), false));
  s.appendChild(bar(pct(d.ma, d.max_ma), true));
  const g = el("div", "grid");
  g.appendChild(tile("Exp/hr", fmt(d.exp_hr)));
  g.appendChild(tile("Last 30 min", fmt(d.exp_hr_30) + "/hr"));
  g.appendChild(tile("Exp made", fmt(d.exp_session)));
  g.appendChild(tile("Session", dur(d.session_secs)));
  g.appendChild(tile("Level", d.level ? String(d.level) : "?"));
  g.appendChild(tile("Next level", d.exp_needed ? fmt(d.exp_needed) : "?"));
  const where = (d.room_name || "") + (d.room ? " (" + d.room.join("/") + ")" : "");
  const doing = (d.path ? (d.loop ? "Looping " : "Walking ") + d.path + (d.loop && d.laps ? ", lap " + d.laps : "") + " — " : "") + (d.status || "");
  g.appendChild(tile(where || "Room unknown", doing || "Nothing", true));
  s.appendChild(g);
  const p = $("cparty");
  p.replaceChildren();
  if (d.leader) p.appendChild(el("div", "p", "Following " + d.leader));
  for (const m of d.party || []) {
    const r = el("div", "p");
    r.appendChild(el("span", "", m.name + (m.class ? " (" + m.class + ")" : "")));
    r.appendChild(el("span", "mut", "HP " + (m.hp ?? "?") + "% · MA " + (m.ma ?? "?") + "%"));
    p.appendChild(r);
  }
}

let seq = 0, scrT = 0, partialEl = null;
const MAXLINES = 400;
async function pollScreen(now) {
  clearTimeout(scrT);
  if (view !== "char") return;
  if (!document.hidden || now) {
    try { addScreen(await api("/api/screen?since=" + (now ? 0 : seq))); } catch (e) {}
  }
  scrT = setTimeout(pollScreen, 1000);
}
function lineEl(segs) {
  const d = el("div");
  for (const [t, fg, b] of segs) {
    const sp = el("span", "c" + (fg === null || fg === undefined ? "x" : fg) + (b ? " b" : ""), t);
    d.appendChild(sp);
  }
  if (!segs.length) d.textContent = " ";
  return d;
}
function addScreen(r) {
  const t = $("term");
  const atEnd = t.scrollHeight - t.scrollTop - t.clientHeight < 40;
  if (r.reset) { t.replaceChildren(); partialEl = null; }
  if (partialEl) { partialEl.remove(); partialEl = null; }
  for (const segs of r.lines || []) t.appendChild(lineEl(segs));
  while (t.childElementCount > MAXLINES) t.firstChild.remove();
  if (r.partial) { partialEl = el("div", "cx", r.partial); t.appendChild(partialEl); }
  seq = r.seq || 0;
  if (atEnd || r.reset) t.scrollTop = t.scrollHeight;
}

let fsize = 12;
try { fsize = Number(localStorage.getItem("mpfont")) || 12; } catch (e) {}
function setFont(n) {
  fsize = Math.max(8, Math.min(20, n));
  $("term").style.fontSize = fsize + "px";
  try { localStorage.setItem("mpfont", String(fsize)); } catch (e) {}
}
setFont(fsize);
$("fminus").addEventListener("click", () => setFont(fsize - 1));
$("fplus").addEventListener("click", () => setFont(fsize + 1));
$("back").addEventListener("click", () => show("list"));
document.addEventListener("visibilitychange", () => { if (!document.hidden) show(view); });

show(KEY ? (view === "char" ? "char" : "list") : "pair");
'''

MANIFEST = r'''{"name":"MudPilot","short_name":"MudPilot","start_url":"/","display":"standalone",
"background_color":"#15171c","theme_color":"#15171c",
"icons":[{"src":"/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any"}]}
'''

ICON = r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><rect width="96" height="96" rx="20" fill="#15171c"/>
<path d="M18 70V28l15 22 15-22 15 22 15-22v42" fill="none" stroke="#7aa7ff" stroke-width="8" stroke-linecap="round"
stroke-linejoin="round"/></svg>
'''

FILES = {
    "/": (HTML, "text/html; charset=utf-8"),
    "/index.html": (HTML, "text/html; charset=utf-8"),
    "/app.css": (CSS, "text/css; charset=utf-8"),
    "/app.js": (JS, "text/javascript; charset=utf-8"),
    "/manifest.json": (MANIFEST, "application/manifest+json"),
    "/icon.svg": (ICON, "image/svg+xml"),
}
