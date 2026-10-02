"""一条片子：光是当时的人，竖着的字是重复最多的原话。"""

from __future__ import annotations

import json

from reception.shot import build_shot


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_shot(shot: dict) -> str:
    payload = json.dumps(shot, ensure_ascii=False).replace("<", "\\u003c")
    title = _esc(shot["title"])
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__SHOT_TITLE__</title>
<style>
body { margin: 0; background: #070605; color: #f6efe4; font: 16px/1.5 "WenQuanYi Micro Hei", "Noto Sans CJK SC", sans-serif; }
main { max-width: 1440px; margin: 0 auto; padding: 14px 12px 48px; }
h1 { font-size: 14px; font-weight: 500; margin: 0 0 8px; color: #b7a894; letter-spacing: 0.06em; }
.frame { position: relative; height: min(74vh, 760px); min-height: 520px; overflow: hidden; background: #070605; }
canvas { width: 100%; height: 100%; display: block; cursor: ew-resize; touch-action: none; }
.bar { display: flex; align-items: center; gap: 14px; margin: 12px 0 0; }
button { background: transparent; color: #f6efe4; border: 1px solid rgba(246, 239, 228, 0.35); border-radius: 999px; padding: 6px 16px; font: inherit; cursor: pointer; }
button:hover { border-color: rgba(246, 239, 228, 0.7); }
#where { color: #b7a894; font-size: 14px; }
.evidence { margin-top: 14px; background: #14110e; border-radius: 12px; padding: 12px 16px; }
.evidence li { margin: 6px 0; }
.meta, .note, details { color: #9a8d7c; }
.note { margin: 10px 0 0; font-size: 14px; }
details { margin-top: 12px; }
summary { cursor: pointer; }
@media (max-width: 700px) {
  .frame { height: 72vh; min-height: 460px; }
  h1 { letter-spacing: 0; }
}
</style>
</head>
<body>
<main>
<h1 id="title"></h1>
<div class="frame"><canvas id="screen"></canvas></div>
<div class="bar"><button type="button" id="toggle">暂停</button><span id="where"></span></div>
<p class="note" id="note"></p>
<div class="evidence" id="evidence" hidden></div>
<details>
<summary>这张图怎么来的</summary>
<p id="method"></p>
</details>
</main>
<script>
const shot = __SHOT_DATA__;
const font = '"WenQuanYi Micro Hei", "Noto Sans CJK SC", sans-serif';
document.getElementById("title").textContent = shot.title;
document.getElementById("note").textContent = shot.note;
document.getElementById("method").textContent = shot.method;
const canvas = document.getElementById("screen");
const evidence = document.getElementById("evidence");
const toggle = document.getElementById("toggle");
const where = document.getElementById("where");
const ctx = canvas.getContext("2d");
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let play = Number(shot.play) || 0.5;
let playing = !reduceMotion;
let last = 0;
let hits = [];
let pinned = null;
let mistCanvas = null;
let mistKey = "";
let field = null;
let columns = null;
let columnKey = "";

function resize() {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(1, Math.round(rect.width * dpr));
  const height = Math.max(1, Math.round(rect.height * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
    mistCanvas = null;
    columns = null;
  }
  return { width: rect.width, height: rect.height, dpr: dpr };
}

function metrics(width, height) {
  const narrow = width < 720;
  const pad = narrow ? 18 : 36;
  const base = height * 0.67;
  const maxRise = height * (narrow ? 0.28 : 0.30);
  return { narrow: narrow, pad: pad, base: base, maxRise: maxRise, span: Math.max(1, width - pad * 2) };
}

function buildField() {
  if (field) return field;
  const samples = 160;
  const raw = new Array(samples).fill(0);
  shot.dots.forEach(function (dot) {
    const index = Math.min(samples - 1, Math.max(0, Math.floor(dot[0] * samples)));
    raw[index] += 1;
  });
  const radius = 7;
  const smooth = new Array(samples).fill(0);
  for (let i = 0; i < samples; i += 1) {
    let sum = 0;
    let weight = 0;
    for (let k = -radius; k <= radius; k += 1) {
      const j = i + k;
      if (j < 0 || j >= samples) continue;
      const w = radius - Math.abs(k) + 1;
      sum += raw[j] * w;
      weight += w;
    }
    smooth[i] = sum / weight;
  }
  const peak = Math.max.apply(null, smooth.concat([1]));
  field = smooth.map(function (value) { return value / peak; });
  return field;
}

function ampAt(percent) {
  const curve = buildField();
  const index = Math.min(curve.length - 1, Math.max(0, Math.floor(percent * curve.length)));
  return curve[index];
}

function motePlace(dot, m) {
  const rise = 8 + ampAt(dot[0]) * m.maxRise;
  const unit = dot[1] / 1000;
  const lift = Math.pow(unit, 1.65);
  return {
    x: m.pad + dot[0] * m.span,
    y: m.base - 3 - lift * rise,
    lift: lift,
    amp: ampAt(dot[0]),
  };
}

function ensureMist(width, height, dpr, m) {
  const key = width + "x" + height;
  if (mistCanvas && mistKey === key) return;
  mistKey = key;
  const sharp = document.createElement("canvas");
  sharp.width = Math.round(width * dpr);
  sharp.height = Math.round(height * dpr);
  const ink = sharp.getContext("2d");
  ink.setTransform(dpr, 0, 0, dpr, 0, 0);
  ink.clearRect(0, 0, width, height);
  ink.globalCompositeOperation = "lighter";
  shot.dots.forEach(function (dot) {
    const mote = motePlace(dot, m);
    const hot = 1 - mote.lift;
    const alpha = 0.10 + hot * 0.22 + mote.amp * 0.08;
    const red = 255;
    const green = 168 + Math.round(hot * 62);
    const blue = 86 + Math.round(hot * 90);
    ink.fillStyle = "rgba(" + red + "," + green + "," + blue + "," + alpha + ")";
    const size = 1.15 + hot * 1.35 + mote.amp * 0.45;
    ink.fillRect(mote.x, mote.y, size, size);
  });
  mistCanvas = document.createElement("canvas");
  mistCanvas.width = sharp.width;
  mistCanvas.height = sharp.height;
  const glow = mistCanvas.getContext("2d");
  glow.setTransform(dpr, 0, 0, dpr, 0, 0);
  glow.clearRect(0, 0, width, height);
  glow.globalCompositeOperation = "lighter";
  glow.filter = "blur(14px)";
  glow.globalAlpha = 0.95;
  glow.drawImage(sharp, 0, 0, width, height);
  glow.filter = "blur(4px)";
  glow.globalAlpha = 0.8;
  glow.drawImage(sharp, 0, 0, width, height);
  glow.filter = "none";
  glow.globalAlpha = 1;
  glow.globalCompositeOperation = "source-over";
  glow.drawImage(sharp, 0, 0, width, height);
}

function columnSize(count, maxCount, chars, narrow) {
  const ratio = Math.pow(count / maxCount, 0.78);
  const hi = narrow ? 24 : 56;
  const lo = narrow ? 15 : 22;
  let size = Math.round(lo + (hi - lo) * ratio);
  const sky = narrow ? 220 : 340;
  while (size > 13 && chars * size * 1.04 > sky) size -= 1;
  return size;
}

function layoutColumns(width, height, m) {
  const key = width + "x" + height;
  if (columns && columnKey === key) return columns;
  columnKey = key;
  const hubs = shot.knots.filter(function (knot) { return knot.hub; });
  hubs.sort(function (a, b) {
    return b.n - a.n || b.family_n - a.family_n || a.percent - b.percent;
  });
  const strongest = hubs.length ? hubs[0].n : 1;
  const floor = Math.max(2, Math.floor(strongest / 3));
  const ranked = hubs.filter(function (knot) { return knot.n >= floor; });
  const placed = [];
  const limit = m.narrow ? 6 : 8;
  const margin = 20;
  const top = 26;
  ranked.forEach(function (knot) {
    if (placed.length >= limit) return;
    const chars = Array.from(knot.text);
    if (!chars.length) return;
    const size = columnSize(knot.n, strongest, chars.length, m.narrow);
    const widthPx = size;
    const heightPx = 16 + chars.length * size * 1.04;
    const natural = m.pad + knot.percent * m.span;
    const gap = m.narrow ? 3 : 10;
    function rectAt(cx) {
      return {
        left: cx - widthPx / 2 - gap,
        right: cx + widthPx / 2 + gap,
        top: top,
        bottom: top + heightPx + 4,
      };
    }
    function blocked(cx) {
      const rect = rectAt(cx);
      return placed.some(function (other) {
        return !(rect.right < other.rect.left || rect.left > other.rect.right || rect.bottom < other.rect.top || rect.top > other.rect.bottom);
      });
    }
    function inBounds(cx) {
      return cx - widthPx / 2 >= margin && cx + widthPx / 2 <= width - margin;
    }
    const companions = placed.filter(function (other) {
      return Math.abs(other.knot.percent - knot.percent) <= 0.03;
    });
    let x = Math.min(width - margin - widthPx / 2, Math.max(margin + widthPx / 2, natural));
    if (companions.length >= 2) return;
    if (companions.length === 1) {
      if (knot.n < 10) return;
      const edge = Math.max.apply(null, companions.map(function (other) { return other.rect.right; }));
      x = edge + widthPx / 2 + gap + 1;
      if (!inBounds(x) || blocked(x)) return;
    } else if (!inBounds(x) || blocked(x)) {
      return;
    }
    placed.push({
      knot: knot,
      chars: chars,
      x: x,
      top: top,
      size: size,
      rect: rectAt(x),
    });
  });
  columns = placed;
  return columns;
}

function spokenNow() {
  if (pinned && Math.abs(pinned.percent - play) <= 0.012) return pinned;
  const pool = columns || [];
  let best = null;
  pool.forEach(function (item) {
    const distance = Math.abs(item.knot.percent - play);
    const nearer = !best || distance + 0.02 < best.distance;
    const stronger = best && Math.abs(distance - best.distance) <= 0.02 && item.knot.n > best.knot.n;
    if (nearer || stronger) {
      best = { knot: item.knot, distance: distance };
    }
  });
  return best ? best.knot : null;
}

function fitLine(text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let line = text;
  while (line.length > 1 && ctx.measureText(line + "…").width > maxWidth) line = line.slice(0, -1);
  return line + "…";
}

function draw() {
  const view = resize();
  const width = view.width;
  const height = view.height;
  const m = metrics(width, height);
  ctx.setTransform(view.dpr, 0, 0, view.dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const backdrop = ctx.createRadialGradient(width * 0.5, m.base, 40, width * 0.5, m.base * 0.7, width * 0.72);
  backdrop.addColorStop(0, "#1c140e");
  backdrop.addColorStop(1, "#070605");
  ctx.fillStyle = backdrop;
  ctx.fillRect(0, 0, width, height);
  ensureMist(width, height, view.dpr, m);
  ctx.drawImage(mistCanvas, 0, 0, width, height);
  const placed = layoutColumns(width, height, m);
  const spoken = spokenNow();
  hits = [];
  placed.forEach(function (item) {
    if (spoken && item.knot === spoken) return;
    drawColumn(item, false);
  });
  const head = m.pad + play * m.span;
  const bandTop = m.base - m.maxRise * 0.38;
  const shaft = ctx.createLinearGradient(head - 64, 0, head + 64, 0);
  shaft.addColorStop(0, "rgba(255, 196, 120, 0)");
  shaft.addColorStop(0.5, "rgba(255, 228, 196, 0.22)");
  shaft.addColorStop(1, "rgba(255, 196, 120, 0)");
  ctx.fillStyle = shaft;
  ctx.fillRect(head - 64, bandTop, 128, m.base - bandTop);
  ctx.fillStyle = "rgba(255, 246, 234, 0.95)";
  ctx.fillRect(head - 0.6, bandTop, 1.2, Math.max(0, m.base - bandTop));
  const active = placed.find(function (item) { return spoken && item.knot === spoken; });
  if (active) drawColumn(active, true);
  ctx.strokeStyle = "rgba(255, 214, 170, 0.28)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(m.pad, m.base);
  ctx.lineTo(m.pad + m.span, m.base);
  ctx.stroke();
  ctx.font = "12px " + font;
  ctx.fillStyle = "rgba(183, 168, 148, 0.8)";
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  ctx.fillText("片头", m.pad, m.base + 18);
  ctx.textAlign = "right";
  ctx.fillText("片尾", m.pad + m.span, m.base + 18);
  if (spoken) drawLockup(width, height, m, spoken);
  const vignette = ctx.createRadialGradient(width / 2, height * 0.45, width * 0.2, width / 2, height * 0.45, width * 0.75);
  vignette.addColorStop(0, "rgba(0, 0, 0, 0)");
  vignette.addColorStop(1, "rgba(0, 0, 0, 0.38)");
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, width, height);
  where.textContent = "片长的 " + Math.round(play * 100) + "%";
  toggle.textContent = playing ? "暂停" : "播放";
}

function drawColumn(item, hot) {
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.font = "600 12px " + font;
  ctx.fillStyle = hot ? "rgba(255, 228, 190, 1)" : "rgba(231, 196, 138, 0.78)";
  ctx.shadowColor = "rgba(0, 0, 0, 0.7)";
  ctx.shadowBlur = 8;
  ctx.fillText(item.size >= 32 ? item.knot.n + "次" : String(item.knot.n), item.x, item.top);
  ctx.font = "700 " + item.size + "px " + font;
  ctx.fillStyle = hot ? "#fffaf3" : "rgba(246, 236, 220, 0.62)";
  ctx.shadowColor = hot ? "rgba(255, 186, 96, 0.85)" : "rgba(0, 0, 0, 0.75)";
  ctx.shadowBlur = hot ? 18 : 10;
  item.chars.forEach(function (char, index) {
    ctx.fillText(char, item.x, item.top + 16 + index * item.size * 1.04);
  });
  ctx.shadowBlur = 0;
  hits.push({
    left: item.rect.left,
    right: item.rect.right,
    top: item.rect.top,
    bottom: item.rect.bottom,
    knot: item.knot,
  });
}

function drawLockup(width, height, m, spoken) {
  const narrow = m.narrow;
  const maxWidth = width * 0.9;
  let size = narrow ? 40 : 72;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = "700 " + size + "px " + font;
  while (size > 26 && ctx.measureText(spoken.text).width > maxWidth) {
    size -= 2;
    ctx.font = "700 " + size + "px " + font;
  }
  const cx = width / 2;
  const y = m.base + Math.min(height - m.base - 28, Math.max(size * 0.72, (height - m.base) * 0.42));
  ctx.font = "700 " + size + "px " + font;
  ctx.shadowColor = "rgba(255, 196, 120, 0.85)";
  ctx.shadowBlur = 22;
  ctx.fillStyle = "#fffaf3";
  ctx.fillText(spoken.text, cx, y);
  const spokenWidth = ctx.measureText(spoken.text).width;
  ctx.shadowBlur = 0;
  ctx.font = "500 " + (narrow ? 14 : 18) + "px " + font;
  ctx.fillStyle = "rgba(231, 196, 138, 0.96)";
  ctx.fillText(spoken.n + " 次", cx, y + size * 0.5 + 16);
  hits.push({
    left: cx - Math.max(spokenWidth, 80) / 2,
    right: cx + Math.max(spokenWidth, 80) / 2,
    top: y - size * 0.55,
    bottom: y + size * 0.5 + 28,
    knot: spoken,
  });
  const echoes = shot.knots.filter(function (knot) {
    return knot.family === spoken.family && knot.text !== spoken.text;
  }).slice(0, 2);
  ctx.font = "500 " + (narrow ? 13 : 15) + "px " + font;
  ctx.fillStyle = "rgba(232, 210, 170, 0.78)";
  echoes.forEach(function (knot, index) {
    const line = fitLine(knot.text + "  " + knot.n + "次", maxWidth);
    ctx.fillText(line, cx, y + size * 0.5 + 40 + index * 20);
  });
}

function showKnot(knot) {
  const hub = shot.knots.find(function (item) { return item.family === knot.family && item.hub; }) || knot;
  evidence.hidden = false;
  evidence.replaceChildren();
  const head = document.createElement("div");
  head.textContent = knot.text;
  evidence.appendChild(head);
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = knot.n + " 次 · 片长的 " + Math.round(knot.percent * 100) + "% · " + shot.bvid;
  evidence.appendChild(meta);
  const list = document.createElement("ul");
  const lines = knot.samples && knot.samples.length ? knot.samples : (hub.samples || [knot.text]);
  lines.forEach(function (line) {
    const li = document.createElement("li");
    li.textContent = line;
    list.appendChild(li);
  });
  evidence.appendChild(list);
  evidence.scrollIntoView({ block: "nearest" });
}

function seek(clientX) {
  const rect = canvas.getBoundingClientRect();
  const m = metrics(rect.width, rect.height);
  play = Math.min(1, Math.max(0, (clientX - rect.left - m.pad) / m.span));
  if (pinned && Math.abs(pinned.percent - play) > 0.012) pinned = null;
  draw();
}

let pointer = null;
canvas.addEventListener("pointerdown", function (event) {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const hit = hits.find(function (item) {
    return x >= item.left && x <= item.right && y >= item.top && y <= item.bottom;
  });
  pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false, hit: hit };
  if (hit) {
    playing = false;
    pinned = hit.knot;
    play = hit.knot.percent;
    showKnot(hit.knot);
    draw();
    return;
  }
  canvas.setPointerCapture(event.pointerId);
});
canvas.addEventListener("pointermove", function (event) {
  if (!pointer || event.pointerId !== pointer.id || pointer.hit) return;
  if (Math.abs(event.clientX - pointer.x) + Math.abs(event.clientY - pointer.y) < 4) return;
  pointer.moved = true;
  playing = false;
  seek(event.clientX);
});
canvas.addEventListener("pointerup", function (event) {
  if (!pointer || event.pointerId !== pointer.id) return;
  if (!pointer.hit && !pointer.moved) {
    playing = false;
    seek(event.clientX);
  }
  if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  pointer = null;
});
toggle.addEventListener("click", function () {
  playing = !playing;
  if (playing) pinned = null;
  draw();
});

function tick(now) {
  if (!last) last = now;
  if (playing) {
    play += (now - last) / 46000;
    if (play > 1) play -= 1;
    if (pinned && Math.abs(pinned.percent - play) > 0.012) pinned = null;
    draw();
  }
  last = now;
  requestAnimationFrame(tick);
}
draw();
requestAnimationFrame(tick);
window.addEventListener("resize", function () { draw(); });
window.__film = {
  seek: function (value) {
    pinned = null;
    play = Math.min(1, Math.max(0, Number(value) || 0));
    playing = false;
    draw();
  },
  pause: function () { playing = false; draw(); },
  resume: function () { pinned = null; playing = true; },
  spoken: function () {
    const knot = spokenNow();
    return knot ? knot.text : "";
  },
  layout: function () {
    return (columns || []).map(function (item) {
      return { text: item.knot.text, x: Math.round(item.x), n: item.knot.n, size: item.size, left: Math.round(item.rect.left), right: Math.round(item.rect.right) };
    });
  },
};
</script>
</body>
</html>
"""
    return html.replace("__SHOT_TITLE__", title).replace("__SHOT_DATA__", payload)
