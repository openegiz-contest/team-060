// Dispatcher console: draws the pit from the twins' attributes and animates it from their features.
"use strict";

const NS = "kz.aktogay.pit:";
const POLL_MS = 1000;
const C = { ore: "#e8a33d", waste: "#8b7d6b", empty: "#7d93a8", bad: "#e5534b", ok: "#4fbf8a", acc: "#4aa3df",
            road: "#c2b49a", ramp: "#d8c7a4", text: "#e6e9ec", mut: "#8b97a3" };
const WAITING = new Set(["queue_shovel", "queue_crusher", "queue_dump", "queue_fuel", "no_route", "no_task"]);

let statics = {};          // thingId -> attributes
let state = {};            // thingId -> {feature: value}
let anim = {};             // truck thingId -> {from, to, t0}
let view = null;           // {cx, cy, wx, wy, scale}
let selected = null;
let pending = {};          // scenario key -> {value, until}
const hist = { ore: [], waste: [], cos: [] };

const cv = document.getElementById("map");
const ctx = cv.getContext("2d");
const val = (id, f, d = null) => { const t = state[NS + id]; return t && t[f] !== undefined ? t[f] : d; };
const fmt = (n, d = 0) => n === null || n === undefined || n === "" ? "—" :
  Number(n).toLocaleString("ru-RU", { minimumFractionDigits: d, maximumFractionDigits: d });

// ------------------------------------------------------------------ data
async function loadStatic() {
  const r = await fetch("api/static");
  if (!r.ok) throw new Error("static " + r.status);
  const arr = await r.json();
  statics = {};
  for (const t of arr) statics[t.thingId] = t.attributes || {};
  if (!statics[NS + "mine"]) throw new Error("twins not created yet");
  fit();
}

async function poll() {
  try {
    if (!statics[NS + "mine"]) await loadStatic();
    const r = await fetch("api/state");
    if (!r.ok) throw new Error("state " + r.status);
    const arr = await r.json();
    const now = performance.now();
    for (const t of arr) {
      const feats = {};
      for (const [k, v] of Object.entries(t.features || {})) feats[k] = v.properties ? (v.properties.value !== undefined ? v.properties.value : v.properties) : v;
      if (statics[t.thingId] && statics[t.thingId].kind === "truck" && feats.x !== undefined) {
        const to = { x: feats.x, y: feats.y, h: feats.heading || 0 };
        const a = anim[t.thingId];
        anim[t.thingId] = { from: a ? currentPos(a, now) : to, to, t0: now };
      }
      state[t.thingId] = feats;
    }
    setConn(true);
    updatePanel();
  } catch (e) {
    setConn(false, e.message);
  }
  setTimeout(poll, POLL_MS);
}

function setConn(ok, msg) {
  const el = document.getElementById("conn");
  el.className = "conn" + (ok ? " ok" : "");
  el.textContent = ok ? "данные: Eclipse Ditto ●" : "нет данных: " + (msg || "");
}

function currentPos(a, now) {
  const k = Math.min(1, Math.max(0, (now - a.t0) / POLL_MS));
  let dh = ((a.to.h - a.from.h + 540) % 360) - 180;
  return { x: a.from.x + (a.to.x - a.from.x) * k, y: a.from.y + (a.to.y - a.from.y) * k, h: a.from.h + dh * k };
}

// ------------------------------------------------------------------ view
function fit() {
  const pts = [];
  for (const a of Object.values(statics)) if (a.polyline) for (const p of a.polyline) pts.push(p);
  const nodes = (statics[NS + "mine"] || {}).nodes || {};
  for (const p of Object.values(nodes)) pts.push(p);
  if (nodes.CRUSHER) pts.push([nodes.CRUSHER[0] + 750, nodes.CRUSHER[1]]);  // stockpile and labels
  if (nodes.DUMP) pts.push([nodes.DUMP[0] - 420, nodes.DUMP[1] + 150]);
  if (!pts.length) return;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  resize();
  const w = cv.width / devicePixelRatio, h = cv.height / devicePixelRatio;
  const scale = Math.min(w / (x1 - x0 + 300), h / (y1 - y0 + 300));
  view = { cx: w / 2, cy: h / 2, wx: (x0 + x1) / 2, wy: (y0 + y1) / 2, scale };
}
function resize() {
  const r = cv.getBoundingClientRect();
  cv.width = r.width * devicePixelRatio; cv.height = r.height * devicePixelRatio;
}
const S = (x, y) => [view.cx + (x - view.wx) * view.scale, view.cy - (y - view.wy) * view.scale];
const W = (sx, sy) => [view.wx + (sx - view.cx) / view.scale, view.wy - (sy - view.cy) / view.scale];

window.addEventListener("resize", () => { if (view) { const s = view.scale; resize(); view.cx = cv.width / devicePixelRatio / 2; view.cy = cv.height / devicePixelRatio / 2; view.scale = s; } });
cv.addEventListener("wheel", e => {
  e.preventDefault(); if (!view) return;
  const [wx, wy] = W(e.offsetX, e.offsetY);
  view.scale *= e.deltaY < 0 ? 1.15 : 1 / 1.15;
  const [sx, sy] = S(wx, wy);
  view.cx += e.offsetX - sx; view.cy += e.offsetY - sy;
}, { passive: false });
let drag = null;
cv.addEventListener("mousedown", e => { drag = { x: e.offsetX, y: e.offsetY, moved: false }; });
window.addEventListener("mouseup", e => { if (drag && !drag.moved && e.target === cv) pick(e.offsetX, e.offsetY); drag = null; });
cv.addEventListener("mousemove", e => {
  if (!drag || !view) return;
  const dx = e.offsetX - drag.x, dy = e.offsetY - drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
  view.cx += dx; view.cy += dy; drag.x = e.offsetX; drag.y = e.offsetY;
});

// ------------------------------------------------------------------ drawing
function draw() {
  requestAnimationFrame(draw);
  if (!view) return;
  const w = cv.width / devicePixelRatio, h = cv.height / devicePixelRatio;
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  ctx.fillStyle = "#1a1f1a"; ctx.fillRect(0, 0, w, h);
  drawGrid(w, h);
  const mine = statics[NS + "mine"];
  if (!mine) return;
  drawPit(mine.rim);
  drawSurface(mine.nodes);
  drawRoads();
  drawFacilities(mine.nodes);
  drawTrucks();
  drawScale(w, h);
}

function drawGrid(w, h) {
  ctx.strokeStyle = "rgba(255,255,255,0.035)"; ctx.lineWidth = 1;
  const step = 250;
  const [x0, y1] = W(0, 0), [x1, y0] = W(w, h);
  for (let x = Math.floor(x0 / step) * step; x < x1; x += step) { const [sx] = S(x, 0); ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, h); ctx.stroke(); }
  for (let y = Math.floor(y0 / step) * step; y < y1; y += step) { const [, sy] = S(0, y); ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(w, sy); ctx.stroke(); }
}

function drawPit(rim) {
  const n = Math.round(rim.depth / rim.bench);
  for (let i = 0; i <= n; i++) {
    const z = -i * rim.bench;
    const f = rim.floor_f + (1 - rim.floor_f) * (z + rim.depth) / rim.depth;
    const [cx, cy] = S(0, 0);
    ctx.beginPath();
    ctx.ellipse(cx, cy, rim.a * f * view.scale, rim.b * f * view.scale, 0, 0, Math.PI * 2);
    const l = 30 - i * 2.2;
    ctx.fillStyle = `hsl(32, 14%, ${l}%)`;
    ctx.fill();
    ctx.strokeStyle = i === 0 ? "rgba(230,210,170,.55)" : "rgba(230,210,170,.18)";
    ctx.lineWidth = i === 0 ? 2 : 1;
    ctx.stroke();
    if (i > 0 && i % 2 === 0 && view.scale > 0.25) {
      const [lx, ly] = S(rim.a * f * Math.cos(-2.2), rim.b * f * Math.sin(-2.2));
      ctx.fillStyle = "rgba(230,220,200,.45)"; ctx.font = "10px sans-serif"; ctx.fillText(`${z} м`, lx - 30, ly);
    }
  }
}

function drawSurface(nodes) {
  // waste dump: a flat-topped pile around its tipping point
  const d = nodes.DUMP; const [dx, dy] = S(d[0], d[1]);
  ctx.beginPath(); ctx.ellipse(dx - 60 * view.scale, dy - 40 * view.scale, 330 * view.scale, 220 * view.scale, -0.3, 0, Math.PI * 2);
  ctx.fillStyle = "#3b352c"; ctx.fill(); ctx.strokeStyle = "rgba(200,180,140,.3)"; ctx.stroke();
  const r = nodes.ROM; const [rx, ry] = S(r[0], r[1]);
  const rom = val("rom", "level", 0);
  const rr = Math.max(40, Math.sqrt(rom) * 1.2) * view.scale;
  ctx.beginPath(); ctx.ellipse(rx + 60 * view.scale, ry - 40 * view.scale, rr * 1.4, rr, 0, 0, Math.PI * 2);
  ctx.fillStyle = "#6b4f28"; ctx.fill();
}

function roadAt(id) { return statics[NS + id]; }

function drawRoads() {
  for (const [id, a] of Object.entries(statics)) {
    if (a.kind !== "road") continue;
    const st = state[id] || {};
    const closed = st.state === "closed";
    const pts = a.polyline.map(p => S(p[0], p[1]));
    const wpx = Math.max(2.5, (a.road_kind === "ramp" ? 28 : a.road_kind === "surface" ? 26 : 20) * view.scale);
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.beginPath(); pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.strokeStyle = "rgba(0,0,0,.35)"; ctx.lineWidth = wpx + 3; ctx.setLineDash([]); ctx.stroke();
    ctx.strokeStyle = closed ? C.bad : (a.road_kind === "ramp" ? C.ramp : C.road);
    ctx.globalAlpha = closed ? 0.9 : 0.55;
    ctx.lineWidth = wpx; if (closed) ctx.setLineDash([wpx, wpx * 0.8]);
    ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
    if (selected === id) { ctx.strokeStyle = C.acc; ctx.lineWidth = 2; ctx.stroke(); }
    if (closed) {
      const [mx, my] = pts[Math.floor(pts.length / 2)];
      ctx.fillStyle = C.bad; ctx.beginPath(); ctx.arc(mx, my, 11, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2.5; ctx.beginPath();
      ctx.moveTo(mx - 5, my - 5); ctx.lineTo(mx + 5, my + 5); ctx.moveTo(mx + 5, my - 5); ctx.lineTo(mx - 5, my + 5); ctx.stroke();
      ctx.fillStyle = "#ffd5d2"; ctx.font = "bold 12px sans-serif"; ctx.fillText(a.name + " — закрыт", mx + 14, my + 4);
    }
  }
}

function label(x, y, text, color = C.text, size = 12, bold = false) {
  ctx.font = `${bold ? "600 " : ""}${size}px "Segoe UI", system-ui, sans-serif`;
  const w = ctx.measureText(text).width;
  ctx.fillStyle = "rgba(10,13,17,.72)"; ctx.fillRect(x - 3, y - size, w + 6, size + 5);
  ctx.fillStyle = color; ctx.fillText(text, x, y);
}

function bar(x, y, w, h, frac, color) {
  ctx.fillStyle = "rgba(0,0,0,.6)"; ctx.fillRect(x, y, w, h);
  ctx.fillStyle = color; ctx.fillRect(x, y + h * (1 - frac), w, h * frac);
  ctx.strokeStyle = "rgba(255,255,255,.4)"; ctx.lineWidth = 1; ctx.strokeRect(x, y, w, h);
}

function drawFacilities(nodes) {
  const t = performance.now() / 1000;
  // shovels
  for (const sid of ["sh01", "sh02", "sh03"]) {
    const a = statics[NS + sid]; if (!a) continue;
    const p = nodes[a.node]; const [x, y] = S(p[0], p[1]);
    const st = val(sid, "state", "idle"); const down = st === "down";
    const col = a.material === "ore" ? C.ore : C.waste;
    ctx.save(); ctx.translate(x, y);
    ctx.fillStyle = down ? "#5a2a28" : "#2d2a24"; ctx.strokeStyle = down ? C.bad : col; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(0, 0, 15, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    // boom swinging while loading
    const ang = st === "loading" ? Math.sin(t * 2.2) * 0.9 : 0.3;
    ctx.rotate(ang); ctx.strokeStyle = down ? C.bad : "#f2d38a"; ctx.lineWidth = 4;
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(26, -6); ctx.stroke();
    ctx.fillStyle = "#f2d38a"; ctx.fillRect(24, -11, 9, 10);
    ctx.restore();
    if (down) { ctx.strokeStyle = C.bad; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(x - 12, y - 12); ctx.lineTo(x + 12, y + 12); ctx.moveTo(x + 12, y - 12); ctx.lineTo(x - 12, y + 12); ctx.stroke(); }
    const q = val(sid, "queue", 0);
    label(x + 20, y + 26, `${a.name}${down ? " — ремонт" : ""}`, down ? "#ffb3ad" : col, 12, true);
    if (q > 0) { ctx.fillStyle = C.bad; ctx.beginPath(); ctx.arc(x + 14, y - 14, 9, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = "bold 11px sans-serif"; ctx.fillText(q, x + 10.5, y - 10); }
    if (a.material === "ore") label(x + 20, y + 42, `${fmt(val(sid, "face_grade"), 2)} % Cu`, C.mut, 11);
  }
  // crusher + coarse ore stockpile + mill feed
  { const p = nodes.CRUSHER; const [x, y] = S(p[0], p[1]);
    const st = val("crusher", "state", "idle"); const stopped = st === "stopped";
    ctx.fillStyle = stopped ? "#5a2a28" : "#2c3640"; ctx.strokeStyle = stopped ? C.bad : C.acc; ctx.lineWidth = 3;
    ctx.fillRect(x - 16, y - 16, 32, 32); ctx.strokeRect(x - 16, y - 16, 32, 32);
    if (st === "crushing") { ctx.save(); ctx.translate(x, y); ctx.rotate(t * 3); ctx.strokeStyle = "#cfe8ff"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(-8, 0); ctx.lineTo(8, 0); ctx.moveTo(0, -8); ctx.lineTo(0, 8); ctx.stroke(); ctx.restore(); }
    const pocket = val("crusher", "pocket", 0) / ((statics[NS + "crusher"] || {}).pocket_t || 700);
    bar(x + 22, y - 16, 8, 32, Math.min(1, pocket), C.ore);
    label(x - 16, y + 34, `ККД-1 ${stopped ? "— СТОП" : fmt(val("crusher", "throughput"), 0) + " т/ч"}`, stopped ? "#ffb3ad" : C.text, 12, true);
    const cosPct = val("cos", "level_pct", 0) / 100;
    const cx = x + 95, cy = y - 70;
    // conveyor to the stockpile
    ctx.strokeStyle = "#556270"; ctx.lineWidth = 3; ctx.setLineDash([6, 4]); ctx.lineDashOffset = st === "crushing" ? -t * 30 : 0;
    ctx.beginPath(); ctx.moveTo(x + 16, y - 16); ctx.lineTo(cx - 20, cy + 10); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = "#3d3326"; ctx.beginPath(); ctx.moveTo(cx - 26, cy + 14); ctx.lineTo(cx, cy - 4 - 20 * cosPct); ctx.lineTo(cx + 26, cy + 14); ctx.closePath(); ctx.fill();
    bar(cx + 32, cy - 22, 9, 36, cosPct, cosPct < 0.25 ? C.bad : C.acc);
    const hl = val("cos", "hours_left", -1);
    label(cx - 26, cy + 32, `Склад КДР ${fmt(val("cos", "level_pct"), 0)} %`, cosPct < 0.25 ? "#ffb3ad" : C.text, 12, true);
    label(cx - 26, cy + 48, hl >= 0 ? `мельница встанет через ${fmt(hl, 1)} ч` : "→ мельница 2 850 т/ч", hl >= 0 && hl < 6 ? "#ffb3ad" : C.mut, 11); }
  // ROM, dump, fuel
  { const p = nodes.ROM; const [x, y] = S(p[0], p[1]); label(x + 14, y + 4, `Рудный склад ${fmt(val("rom", "level") / 1000, 1)} тыс. т`, C.ore, 12, true); }
  { const p = nodes.DUMP; const [x, y] = S(p[0], p[1]); label(x - 50, y - 18, `Отвал вскрыши · ${fmt(val("dump", "waste_tph_1h"))} т/ч`, "#cbbfa9", 12, true); }
  { const p = nodes.FUEL; const [x, y] = S(p[0], p[1]);
    ctx.fillStyle = "#24313c"; ctx.strokeStyle = C.ok; ctx.lineWidth = 2; ctx.fillRect(x - 10, y - 10, 20, 20); ctx.strokeRect(x - 10, y - 10, 20, 20);
    ctx.fillStyle = C.ok; ctx.font = "bold 12px sans-serif"; ctx.fillText("⛽", x - 7, y + 5);
    label(x + 16, y + 4, "АЗС / стоянка", C.mut, 11); }
}

function drawTrucks() {
  const now = performance.now();
  for (const [id, a] of Object.entries(anim)) {
    const st = state[id] || {};
    const p = currentPos(a, now);
    const [x, y] = S(p.x, p.y);
    const loaded = (st.payload || 0) > 0;
    const parked = st.state === "parked";
    const waiting = WAITING.has(st.state);
    const col = parked ? "#4a5560" : loaded ? (st.material === "waste" ? C.waste : C.ore) : C.empty;
    const sc = Math.max(1.0, Math.min(1.8, view.scale * 3));
    ctx.save(); ctx.translate(x, y); ctx.rotate(-p.h * Math.PI / 180); ctx.scale(sc, sc);
    ctx.fillStyle = col; ctx.fillRect(-9, -5, 14, 10);           // body
    ctx.fillStyle = "#1c232b"; ctx.fillRect(5, -5, 5, 10);        // cab
    if (loaded) { ctx.fillStyle = "rgba(255,255,255,.25)"; ctx.fillRect(-8, -3.5, 12, 7); }
    if (waiting || st.state === "no_route") { ctx.strokeStyle = C.bad; ctx.lineWidth = 2; ctx.strokeRect(-11, -7, 23, 14); }
    if (selected === id) { ctx.strokeStyle = C.acc; ctx.lineWidth = 2; ctx.strokeRect(-13, -9, 27, 18); }
    ctx.restore();
    if (view.scale > 0.22 || selected === id) {
      ctx.fillStyle = "rgba(230,233,236,.85)"; ctx.font = "10px sans-serif";
      ctx.fillText(id.replace(NS, "").toUpperCase(), x + 10, y - 8);
    }
  }
}

function drawScale(w, h) {
  const m = 500; const px = m * view.scale;
  ctx.strokeStyle = C.mut; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(w - px - 20, h - 46); ctx.lineTo(w - 20, h - 46); ctx.stroke();
  ctx.fillStyle = C.mut; ctx.font = "11px sans-serif"; ctx.fillText("500 м", w - px / 2 - 34, h - 52);
  ctx.fillText("N ↑", w - 40, 24);
}

// ------------------------------------------------------------------ picking
function pick(sx, sy) {
  const nodes = (statics[NS + "mine"] || {}).nodes || {};
  let best = null, bd = 18;
  const now = performance.now();
  for (const [id, a] of Object.entries(anim)) {
    const p = currentPos(a, now); const [x, y] = S(p.x, p.y); const d = Math.hypot(x - sx, y - sy);
    if (d < bd) { bd = d; best = id; }
  }
  if (!best) for (const [id, a] of Object.entries(statics)) {
    let node = a.node; if (!node) continue;
    const p = nodes[node]; const [x, y] = S(p[0], p[1]);
    const cos = a.kind === "stockpile" && id.endsWith("cos");
    const d = Math.hypot(x + (cos ? 95 : 0) - sx, y - (cos ? 70 : 0) - sy);
    if (d < 24 && d < bd + 6) { bd = d; best = id; }
  }
  if (!best) for (const [id, a] of Object.entries(statics)) {
    if (a.kind !== "road") continue;
    for (let i = 0; i < a.polyline.length - 1; i++) {
      const [x1, y1] = S(a.polyline[i][0], a.polyline[i][1]), [x2, y2] = S(a.polyline[i + 1][0], a.polyline[i + 1][1]);
      const d = segDist(sx, sy, x1, y1, x2, y2);
      if (d < 9) { best = id; break; }
    }
    if (best) break;
  }
  selected = best; showCard();
}
function segDist(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1, l = dx * dx + dy * dy || 1;
  const k = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / l));
  return Math.hypot(px - x1 - k * dx, py - y1 - k * dy);
}

function showCard() {
  const el = document.getElementById("card");
  if (!selected) { el.classList.add("hidden"); return; }
  const a = statics[selected] || {}, f = state[selected] || {};
  const skip = new Set(["polyline", "_isType", "_parents", "nodes", "rim"]);
  const rows = Object.entries(a).filter(([k]) => !skip.has(k)).map(([k, v]) => `<tr><td>${k}</td><td>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`).join("");
  const feats = Object.entries(f).map(([k, v]) => `<tr><td>${k}</td><td><b>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</b></td></tr>`).join("");
  el.innerHTML = `<span class="x" onclick="selected=null;showCard()">✕</span><h3>${esc(a.name || selected)}</h3>
    <div class="id">${esc(selected)}</div><table><tr><td colspan=2><b>Состояние (features)</b></td></tr>${feats}
    <tr><td colspan=2><b>Атрибуты</b></td></tr>${rows}</table>`;
  el.classList.remove("hidden");
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ------------------------------------------------------------------ side panel
function kpi(title, value, sub, cls = "") { return `<div class="kpi ${cls}"><span>${title}</span><b>${value}</b><small>${sub}</small></div>`; }

function updatePanel() {
  document.getElementById("clock").textContent = val("mine", "sim_clock", "--:--");
  const recs = String(val("dispatch", "recommendations", "") || "").split("\n").filter(Boolean);
  document.getElementById("recos").innerHTML = recs.map(r => `<li class="${r.startsWith("Норма") ? "good" : ""}">${esc(r)}</li>`).join("") || "<li>—</li>";
  const ev = String(val("dispatch", "events", "") || "");
  document.getElementById("events").textContent = ev;
  const mill = (statics[NS + "cos"] || {}).mill_feed_tph || 2850;
  const ore = val("mine", "ore_tph_1h", 0), crIn = val("crusher", "ore_in_tph_1h", 0);
  const hl = val("cos", "hours_left", -1);
  const need = val("dispatch", "need_ore_trucks", 0), on = val("dispatch", "on_ore_trucks", 0);
  const hrs = val("mine", "sim_hours", 0);
  document.getElementById("kpis").innerHTML =
    kpi("Руда на ККД, т/ч (1 ч)", fmt(crIn), `потребность мельницы ${fmt(mill)} т/ч${hrs < 1 ? " · окно < 1 ч" : ""}`, crIn >= mill * 0.98 ? "ok" : (hrs > 0.5 ? "bad" : "")) +
    kpi("Склад перед мельницей", fmt(val("cos", "level_pct"), 1) + " %", hl >= 0 ? `опустеет через ${fmt(hl, 1)} ч` : "пополняется", hl >= 0 && hl < 6 ? "bad" : "ok") +
    kpi("Самосвалов на руде", `${on} / ${need}`, "факт / нужно по модели", on >= need ? "ok" : "bad") +
    kpi("Рудный рейс", fmt(val("dispatch", "ore_cycle"), 1) + " мин", `${fmt(val("dispatch", "ore_route"), 1)} км гружёным`) +
    kpi("Вскрыша, т/ч (1 ч)", fmt(val("mine", "waste_tph_1h")), `всего ${fmt(val("mine", "waste_total") / 1000, 1)} тыс. т`) +
    kpi("Руда на склад ROM", fmt(val("rom", "received_total") / 1000, 1) + " тыс. т", "доп. перевалка погрузчиком") +
    kpi("Самосвалы в ожидании", fmt(val("mine", "trucks_waiting")), `в движении ${fmt(val("mine", "trucks_moving"))}, на стоянке ${fmt(val("mine", "trucks_parked"))}`, val("mine", "trucks_waiting", 0) > 3 ? "bad" : "") +
    kpi("Содержание Cu в питании", fmt(val("mine", "feed_grade_1h"), 3) + " %", "средневзвешенно за 1 ч") +
    kpi("Дизель на тонну", fmt(val("mine", "fuel_per_t"), 3) + " л/т", `всего ${fmt(val("mine", "fuel_total"))} л`) +
    kpi("Электроэнергия на тонну", fmt(val("mine", "energy_per_t"), 3) + " кВт·ч/т", "экскаваторы + ККД");
  // scenario controls mirror the control twin
  const sc = val("control", "scenarios", {}) || {};
  const now = Date.now();
  for (const el of document.querySelectorAll("#scen input[data-k]")) {
    const k = el.dataset.k; if (pending[k] && pending[k].until > now) continue;
    el.checked = !!sc[k];
  }
  for (const seg of document.querySelectorAll("#scen .seg")) {
    const k = seg.dataset.k; const v = pending[k] && pending[k].until > now ? pending[k].value : sc[k];
    for (const b of seg.children) b.classList.toggle("on", String(b.dataset.v ?? b.textContent) === String(v));
  }
  // history
  hist.ore.push(crIn); hist.waste.push(val("mine", "waste_tph_1h", 0)); hist.cos.push(val("cos", "level_pct", 0));
  for (const k in hist) if (hist[k].length > 600) hist[k].shift();
  drawSpark();
  if (selected) showCard();
}

function drawSpark() {
  const c = document.getElementById("spark"); const g = c.getContext("2d");
  const w = c.clientWidth, h = c.clientHeight; c.width = w * devicePixelRatio; c.height = h * devicePixelRatio;
  g.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  g.clearRect(0, 0, w, h);
  const line = (arr, max, col) => { if (arr.length < 2) return; g.strokeStyle = col; g.lineWidth = 1.6; g.beginPath();
    arr.forEach((v, i) => { const x = i / (600 - 1) * w, y = h - 4 - (v / max) * (h - 8); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); };
  const max = Math.max(6000, ...hist.ore, ...hist.waste);
  g.strokeStyle = "rgba(255,255,255,.12)"; const my = h - 4 - (2850 / max) * (h - 8); g.setLineDash([4, 4]); g.beginPath(); g.moveTo(0, my); g.lineTo(w, my); g.stroke(); g.setLineDash([]);
  g.fillStyle = "rgba(255,255,255,.4)"; g.font = "10px sans-serif"; g.fillText("2 850 т/ч", 4, my - 3);
  line(hist.ore, max, C.ore); line(hist.waste, max, C.waste); line(hist.cos, 100, C.acc);
}

// ------------------------------------------------------------------ scenario controls
async function setScenario(k, v) {
  pending[k] = { value: v, until: Date.now() + 2500 };
  try {
    const r = await fetch("api/scenario", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [k]: v }) });
    if (!r.ok) throw new Error(await r.text());
  } catch (e) { alert("Не удалось изменить сценарий: " + e.message); delete pending[k]; }
}
for (const el of document.querySelectorAll("#scen input[data-k]")) el.addEventListener("change", () => setScenario(el.dataset.k, el.checked));
for (const seg of document.querySelectorAll("#scen .seg")) for (const b of seg.children) b.addEventListener("click", () => {
  const k = seg.dataset.k; const v = b.dataset.v ?? Number(b.textContent);
  for (const x of seg.children) x.classList.toggle("on", x === b);
  setScenario(k, v);
});
document.getElementById("reset").addEventListener("click", async () => {
  await fetch("api/reset", { method: "POST" });
});

poll();
draw();
