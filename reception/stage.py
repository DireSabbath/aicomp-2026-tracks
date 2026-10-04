"""一条片子的三维光层：左右是片长，高低是人多少，纵深是发送先后。"""

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
.frame { position: relative; height: min(74vh, 760px); min-height: 520px; overflow: hidden; background: #070605; touch-action: none; }
canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
#world { cursor: all-scroll; }
#ink { pointer-events: none; }
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
<div class="frame">
<canvas id="world"></canvas>
<canvas id="ink"></canvas>
</div>
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
const SPAN_X = 6.4;
const SPAN_Z = 2.7;
document.getElementById("title").textContent = shot.title;
document.getElementById("note").textContent = shot.note;
document.getElementById("method").textContent = shot.method;
const world = document.getElementById("world");
const ink = document.getElementById("ink");
const evidence = document.getElementById("evidence");
const toggle = document.getElementById("toggle");
const where = document.getElementById("where");
const ctx = ink.getContext("2d");
const gl = world.getContext("webgl", { alpha: false, antialias: true, preserveDrawingBuffer: true });
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let play = Number(shot.play) || 0.5;
let playing = !reduceMotion;
let pitch = 0.62;
let last = 0;
let clock = 0;
let hits = [];
let pinned = null;
let monuments = null;
let field = null;
let cloud = null;
let ready = false;

function resize() {
  const rect = world.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(1, Math.round(rect.width * dpr));
  const height = Math.max(1, Math.round(rect.height * dpr));
  if (world.width !== width || world.height !== height) {
    world.width = width;
    world.height = height;
    ink.width = width;
    ink.height = height;
  }
  return { width: rect.width, height: rect.height, dpr: dpr };
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

function worldX(percent, offset) {
  return (percent - 0.5) * SPAN_X + (offset || 0);
}

function worldZ(depth) {
  return (0.5 - (Number(depth) || 0.5)) * SPAN_Z;
}

function normalize(v) {
  const length = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / length, v[1] / length, v[2] / length];
}

function cross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

function dot3(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function lookAt(eye, target, up) {
  const z = normalize([eye[0] - target[0], eye[1] - target[1], eye[2] - target[2]]);
  const x = normalize(cross(up, z));
  const y = cross(z, x);
  return [
    x[0], y[0], z[0], 0,
    x[1], y[1], z[1], 0,
    x[2], y[2], z[2], 0,
    -dot3(x, eye), -dot3(y, eye), -dot3(z, eye), 1,
  ];
}

function perspective(fov, aspect, near, far) {
  const f = 1 / Math.tan(fov / 2);
  const nf = 1 / (near - far);
  return [
    f / aspect, 0, 0, 0,
    0, f, 0, 0,
    0, 0, (far + near) * nf, -1,
    0, 0, 2 * far * near * nf, 0,
  ];
}

function multiply(a, b) {
  const out = new Array(16).fill(0);
  for (let col = 0; col < 4; col += 1) {
    for (let row = 0; row < 4; row += 1) {
      out[col * 4 + row] =
        a[row] * b[col * 4] +
        a[4 + row] * b[col * 4 + 1] +
        a[8 + row] * b[col * 4 + 2] +
        a[12 + row] * b[col * 4 + 3];
    }
  }
  return out;
}

function camera() {
  const rect = world.getBoundingClientRect();
  const aspect = Math.max(0.45, rect.width / Math.max(1, rect.height));
  const halfWidth = Math.tan(0.31) * aspect;
  const dist = Math.max(8.6, 4.7 / halfWidth);
  const focus = (play - 0.5) * (aspect < 1 ? 0.15 : 1.05);
  const eye = [focus, 0.15 + Math.sin(pitch) * dist * 0.72, Math.cos(pitch) * dist];
  const target = [focus * 0.2, 0.32, 0];
  return { eye: eye, target: target };
}

function viewProj(width, height) {
  const cam = camera();
  const view = lookAt(cam.eye, cam.target, [0, 1, 0]);
  const proj = perspective(0.62, Math.max(0.4, width / Math.max(1, height)), 0.12, 40);
  return multiply(proj, view);
}

function project(mvp, x, y, z, width, height) {
  const w = mvp[3] * x + mvp[7] * y + mvp[11] * z + mvp[15];
  if (w <= 0.08) return null;
  const nx = (mvp[0] * x + mvp[4] * y + mvp[8] * z + mvp[12]) / w;
  const ny = (mvp[1] * x + mvp[5] * y + mvp[9] * z + mvp[13]) / w;
  if (nx < -1.4 || nx > 1.4 || ny < -1.4 || ny > 1.4) return null;
  return {
    x: (nx * 0.5 + 0.5) * width,
    y: (1 - (ny * 0.5 + 0.5)) * height,
    w: w,
  };
}

function compile(type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error(gl.getShaderInfoLog(shader));
    return null;
  }
  return shader;
}

function link(vsSource, fsSource) {
  const vs = compile(gl.VERTEX_SHADER, vsSource);
  const fs = compile(gl.FRAGMENT_SHADER, fsSource);
  if (!vs || !fs) return null;
  const program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error(gl.getProgramInfoLog(program));
    return null;
  }
  return program;
}

function setupGl() {
  if (!gl) return false;
  const points = link(
    [
      "attribute vec3 aPos;",
      "attribute float aPercent;",
      "attribute float aAmp;",
      "attribute float aSlot;",
      "uniform mat4 uMvp;",
      "uniform float uPlay;",
      "uniform float uTime;",
      "uniform float uScale;",
      "uniform float uMirror;",
      "uniform float uHalo;",
      "varying float vAlpha;",
      "varying float vHot;",
      "void main() {",
      "  vec3 p = aPos;",
      "  p.y *= uMirror;",
      "  p.y += sin(uTime + aSlot * 6.28318) * 0.02 * step(0.0, uMirror);",
      "  float along = 1.0 - smoothstep(0.0, 0.05, abs(aPercent - uPlay));",
      "  vec4 clip = uMvp * vec4(p, 1.0);",
      "  gl_Position = clip;",
      "  float depth = max(clip.w, 0.8);",
      "  float size = (4.0 + aAmp * 7.5 + along * 3.5) * uScale;",
      "  if (uHalo > 0.5) size *= 2.1;",
      "  gl_PointSize = clamp(size * (5.3 / depth), 1.6, 42.0);",
      "  float fade = clamp(1.15 - clip.w / 16.0, 0.4, 1.0);",
      "  float alpha = (0.26 + aAmp * 0.42 + along * 0.2) * fade;",
      "  if (uMirror < 0.0) alpha *= 0.16;",
      "  if (uHalo > 0.5) alpha *= 0.2;",
      "  vAlpha = alpha;",
      "  vHot = along;",
      "}",
    ].join("\\n"),
    [
      "precision mediump float;",
      "varying float vAlpha;",
      "varying float vHot;",
      "void main() {",
      "  vec2 uv = gl_PointCoord - vec2(0.5);",
      "  float d = length(uv);",
      "  if (d > 0.5) discard;",
      "  float disc = smoothstep(0.5, 0.0, d);",
      "  float beam = smoothstep(0.14, 0.0, abs(uv.x)) + smoothstep(0.14, 0.0, abs(uv.y));",
      "  float spark = max(disc, beam * vHot * 0.7);",
      "  vec3 color = mix(vec3(0.72, 0.34, 0.08), vec3(1.0, 0.78, 0.48), spark);",
      "  gl_FragColor = vec4(color, vAlpha * spark);",
      "}",
    ].join("\\n")
  );
  const flat = link(
    [
      "attribute vec3 aPos;",
      "uniform mat4 uMvp;",
      "varying float vY;",
      "void main() {",
      "  gl_Position = uMvp * vec4(aPos, 1.0);",
      "  vY = aPos.y;",
      "}",
    ].join("\\n"),
    [
      "precision mediump float;",
      "uniform vec4 uColor;",
      "uniform float uFlat;",
      "varying float vY;",
      "void main() {",
      "  float h = clamp(vY / 1.5, 0.0, 1.0);",
      "  float alpha = uColor.a * mix((1.0 - h) * (0.45 + h), 1.0, uFlat);",
      "  gl_FragColor = vec4(uColor.rgb, alpha);",
      "}",
    ].join("\\n")
  );
  if (!points || !flat) return false;
  const data = [];
  shot.dots.forEach(function (dot) {
    const percent = dot[0];
    const slot = (dot[1] % 1000) / 1000;
    const depth = dot.length > 2 ? dot[2] : 0.5;
    const amp = ampAt(percent);
    const lift = Math.pow(slot, 1.5);
    const y = 0.02 + lift * (0.08 + amp * 1.38);
    const z = worldZ(depth) + (slot - 0.5) * 0.16;
    data.push(worldX(percent, 0), y, z, percent, amp, slot);
  });
  const cloudBuf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, cloudBuf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
  const grid = [];
  for (let i = 0; i <= 8; i += 1) {
    const x = -SPAN_X / 2 + (i / 8) * SPAN_X;
    grid.push(x, 0, -SPAN_Z / 2, x, 0, SPAN_Z / 2);
  }
  for (let i = 0; i <= 4; i += 1) {
    const z = -SPAN_Z / 2 + (i / 4) * SPAN_Z;
    grid.push(-SPAN_X / 2, 0, z, SPAN_X / 2, 0, z);
  }
  const gridBuf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, gridBuf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(grid), gl.STATIC_DRAW);
  const sheetBuf = gl.createBuffer();
  cloud = {
    points: points,
    flat: flat,
    cloudBuf: cloudBuf,
    gridBuf: gridBuf,
    sheetBuf: sheetBuf,
    count: data.length / 6,
    gridCount: grid.length / 3,
  };
  return true;
}

function columnSize(count, maxCount, chars, narrow) {
  const ratio = Math.pow(count / maxCount, 0.78);
  const hi = narrow ? 22 : 46;
  const lo = narrow ? 14 : 20;
  let size = Math.round(lo + (hi - lo) * ratio);
  const sky = narrow ? 150 : 250;
  while (size > 12 && chars * size * 1.02 > sky) size -= 1;
  return size;
}

function layoutMonuments(narrow) {
  if (monuments) return monuments;
  const hubs = shot.knots.filter(function (knot) { return knot.hub; });
  hubs.sort(function (a, b) {
    return b.n - a.n || b.family_n - a.family_n || a.percent - b.percent;
  });
  const strongest = hubs.length ? hubs[0].n : 1;
  const floor = Math.max(2, Math.floor(strongest / 3));
  const ranked = hubs.filter(function (knot) { return knot.n >= floor; });
  const placed = [];
  const limit = narrow ? 6 : 8;
  ranked.forEach(function (knot) {
    if (placed.length >= limit) return;
    const chars = Array.from(knot.text);
    if (!chars.length) return;
    const companions = placed.filter(function (other) {
      return Math.abs(other.knot.percent - knot.percent) <= 0.03;
    });
    if (companions.length >= 2) return;
    let offset = 0;
    if (companions.length === 1) {
      if (knot.n < 10) return;
      offset = 0.42;
    }
    const x = worldX(knot.percent, offset);
    const blocked = placed.some(function (other) {
      return Math.abs(other.wx - x) < 0.34 && Math.abs(other.wz - worldZ(knot.depth)) < 0.45;
    });
    if (blocked) return;
    placed.push({
      knot: knot,
      chars: chars,
      size: columnSize(knot.n, strongest, chars.length, narrow),
      wx: x,
      wy: 0.22 + ampAt(knot.percent) * 1.15,
      wz: worldZ(knot.depth),
    });
  });
  monuments = placed;
  return monuments;
}

function spokenNow() {
  if (pinned && Math.abs(pinned.percent - play) <= 0.012) return pinned;
  const pool = monuments || [];
  let best = null;
  pool.forEach(function (item) {
    const distance = Math.abs(item.knot.percent - play);
    const nearer = !best || distance + 0.02 < best.distance;
    const stronger = best && Math.abs(distance - best.distance) <= 0.02 && item.knot.n > best.knot.n;
    if (nearer || stronger) best = { knot: item.knot, distance: distance };
  });
  return best ? best.knot : null;
}

function fitLine(text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let line = text;
  while (line.length > 1 && ctx.measureText(line + "…").width > maxWidth) line = line.slice(0, -1);
  return line + "…";
}

function drawPoints(mvp, mirror, halo, scale) {
  const prog = cloud.points;
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, cloud.cloudBuf);
  const stride = 24;
  const aPos = gl.getAttribLocation(prog, "aPos");
  const aPercent = gl.getAttribLocation(prog, "aPercent");
  const aAmp = gl.getAttribLocation(prog, "aAmp");
  const aSlot = gl.getAttribLocation(prog, "aSlot");
  gl.enableVertexAttribArray(aPos);
  gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, stride, 0);
  gl.enableVertexAttribArray(aPercent);
  gl.vertexAttribPointer(aPercent, 1, gl.FLOAT, false, stride, 12);
  gl.enableVertexAttribArray(aAmp);
  gl.vertexAttribPointer(aAmp, 1, gl.FLOAT, false, stride, 16);
  gl.enableVertexAttribArray(aSlot);
  gl.vertexAttribPointer(aSlot, 1, gl.FLOAT, false, stride, 20);
  gl.uniformMatrix4fv(gl.getUniformLocation(prog, "uMvp"), false, mvp);
  gl.uniform1f(gl.getUniformLocation(prog, "uPlay"), play);
  gl.uniform1f(gl.getUniformLocation(prog, "uTime"), reduceMotion ? 0 : clock);
  gl.uniform1f(gl.getUniformLocation(prog, "uScale"), scale);
  gl.uniform1f(gl.getUniformLocation(prog, "uMirror"), mirror);
  gl.uniform1f(gl.getUniformLocation(prog, "uHalo"), halo);
  gl.drawArrays(gl.POINTS, 0, cloud.count);
}

function drawFlat(mvp, buffer, count, mode, color, flat) {
  const prog = cloud.flat;
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  const aPos = gl.getAttribLocation(prog, "aPos");
  gl.enableVertexAttribArray(aPos);
  gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 12, 0);
  gl.uniformMatrix4fv(gl.getUniformLocation(prog, "uMvp"), false, mvp);
  gl.uniform4f(gl.getUniformLocation(prog, "uColor"), color[0], color[1], color[2], color[3]);
  gl.uniform1f(gl.getUniformLocation(prog, "uFlat"), flat);
  gl.drawArrays(mode, 0, count);
}

function drawWorld(width, height, dpr) {
  const mvp = new Float32Array(viewProj(width, height));
  gl.viewport(0, 0, world.width, world.height);
  gl.clearColor(0.027, 0.024, 0.02, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
  gl.disable(gl.DEPTH_TEST);
  const scale = (height / 760) * dpr;
  drawFlat(mvp, cloud.gridBuf, cloud.gridCount, gl.LINES, [1, 0.78, 0.55, 0.2], 1);
  const x = worldX(play, 0);
  const sheet = new Float32Array([
    x, 0, -0.28,
    x, 0, 0.28,
    x, 1.35, -0.28,
    x, 1.35, 0.28,
  ]);
  gl.bindBuffer(gl.ARRAY_BUFFER, cloud.sheetBuf);
  gl.bufferData(gl.ARRAY_BUFFER, sheet, gl.DYNAMIC_DRAW);
  drawFlat(mvp, cloud.sheetBuf, 4, gl.TRIANGLE_STRIP, [1, 0.9, 0.7, 0.16], 0);
  drawPoints(mvp, -1, 0, scale);
  drawPoints(mvp, 1, 0, scale);
  drawPoints(mvp, 1, 1, scale);
  return mvp;
}

function drawLabel(text, x, y, align) {
  ctx.font = "12px " + font;
  ctx.fillStyle = "rgba(214, 196, 168, 0.82)";
  ctx.textAlign = align || "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y);
}

function drawColumn(item, hot, width, height) {
  const scale = Math.max(0.62, Math.min(1.25, 5.4 / item.point.w));
  const size = Math.max(13, Math.round(item.size * scale));
  const x = item.point.x;
  const top = item.point.y - size * 0.2;
  if (top > height * 0.7) return;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.font = "600 12px " + font;
  ctx.fillStyle = hot ? "rgba(255, 232, 200, 1)" : "rgba(231, 196, 138, 0.8)";
  ctx.shadowColor = "rgba(0, 0, 0, 0.75)";
  ctx.shadowBlur = 8;
  ctx.fillText(size >= 28 ? item.knot.n + "次" : String(item.knot.n), x, top);
  ctx.font = "700 " + size + "px " + font;
  ctx.fillStyle = hot ? "#fffaf3" : "rgba(255, 246, 232, 0.94)";
  ctx.shadowColor = "rgba(0, 0, 0, 0.9)";
  ctx.shadowBlur = 10;
  ctx.lineWidth = Math.max(3, size * 0.14);
  ctx.strokeStyle = "rgba(8, 6, 4, 0.82)";
  item.chars.forEach(function (char, index) {
    const cy = top + 15 + index * size * 1.02;
    ctx.strokeText(char, x, cy);
    ctx.fillText(char, x, cy);
  });
  ctx.shadowBlur = 0;
  const heightPx = 15 + item.chars.length * size * 1.02;
  hits.push({
    left: x - size * 0.7,
    right: x + size * 0.7,
    top: top,
    bottom: top + heightPx,
    knot: item.knot,
  });
  item.screen = { x: x, y: top, left: x - size * 0.7, right: x + size * 0.7, top: top, bottom: top + heightPx };
}

function drawLockup(width, height, spoken, narrow) {
  const maxWidth = width * 0.9;
  let size = narrow ? 36 : 64;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = "700 " + size + "px " + font;
  while (size > 24 && ctx.measureText(spoken.text).width > maxWidth) {
    size -= 2;
    ctx.font = "700 " + size + "px " + font;
  }
  const x = width / 2;
  const y = height * 0.84;
  ctx.shadowColor = "rgba(255, 196, 120, 0.9)";
  ctx.shadowBlur = 22;
  ctx.fillStyle = "#fffaf3";
  ctx.fillText(spoken.text, x, y);
  const spokenWidth = ctx.measureText(spoken.text).width;
  ctx.shadowBlur = 0;
  ctx.font = "500 " + (narrow ? 14 : 18) + "px " + font;
  ctx.fillStyle = "rgba(231, 196, 138, 0.96)";
  ctx.fillText(spoken.n + " 次", x, y + size * 0.48 + 8);
  hits.push({
    left: x - Math.max(spokenWidth, 80) / 2,
    right: x + Math.max(spokenWidth, 80) / 2,
    top: y - size * 0.55,
    bottom: y + size * 0.48 + 20,
    knot: spoken,
  });
  const echoes = shot.knots.filter(function (knot) {
    return knot.family === spoken.family && knot.text !== spoken.text;
  }).slice(0, 2);
  ctx.font = "500 " + (narrow ? 13 : 15) + "px " + font;
  ctx.fillStyle = "rgba(232, 210, 170, 0.8)";
  echoes.forEach(function (knot, index) {
    ctx.fillText(fitLine(knot.text + "  " + knot.n + "次", maxWidth), x, y + size * 0.48 + 30 + index * 18);
  });
}

function draw() {
  const view = resize();
  const width = view.width;
  const height = view.height;
  const narrow = width < 720;
  ctx.setTransform(view.dpr, 0, 0, view.dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const mvp = ready ? drawWorld(width, height, view.dpr) : null;
  const veil = ctx.createLinearGradient(0, height * 0.64, 0, height);
  veil.addColorStop(0, "rgba(7, 6, 5, 0)");
  veil.addColorStop(0.42, "rgba(7, 6, 5, 0.78)");
  veil.addColorStop(1, "rgba(7, 6, 5, 0.96)");
  ctx.fillStyle = veil;
  ctx.fillRect(0, height * 0.64, width, height * 0.36);
  const placed = layoutMonuments(narrow);
  const spoken = spokenNow();
  hits = [];
  if (mvp) {
    placed.forEach(function (item) {
      item.point = project(mvp, item.wx, item.wy, item.wz, width, height);
    });
    placed.forEach(function (item) {
      if (!item.point || (spoken && item.knot === spoken)) return;
      drawColumn(item, false, width, height);
    });
    const active = placed.find(function (item) { return spoken && item.knot === spoken; });
    if (active && active.point) drawColumn(active, true, width, height);
    const marks = [
      ["片头", project(mvp, worldX(0, 0), 0, SPAN_Z * 0.15, width, height), "left"],
      ["片尾", project(mvp, worldX(1, 0), 0, SPAN_Z * 0.15, width, height), "right"],
    ];
    if (shot.has_clock) {
      marks.push(["发送早", project(mvp, worldX(0.5, 0), 0, SPAN_Z / 2, width, height), "center"]);
      marks.push(["发送晚", project(mvp, worldX(1, 0), 0.02, -SPAN_Z / 2, width, height), "right"]);
    }
    marks.forEach(function (mark) {
      const point = mark[1];
      if (!point || point.y > height * 0.7 || point.y < 18 || point.x < 8 || point.x > width - 8) return;
      const crowded = hits.some(function (hit) {
        const cx = (hit.left + hit.right) / 2;
        const cy = (hit.top + hit.bottom) / 2;
        return Math.hypot(cx - point.x, cy - point.y) < 110;
      });
      if (!crowded) drawLabel(mark[0], point.x, point.y, mark[2]);
    });
  }
  if (spoken) drawLockup(width, height, spoken, narrow);
  where.textContent = "片长的 " + Math.round(play * 100) + "%";
  toggle.textContent = playing ? "暂停" : "播放";
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

function playAt(clientX) {
  const rect = world.getBoundingClientRect();
  const view = resize();
  if (!ready) {
    return Math.min(1, Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)));
  }
  const mvp = viewProj(view.width, view.height);
  let best = play;
  let bestDx = 1e9;
  for (let i = 0; i <= 48; i += 1) {
    const percent = i / 48;
    const point = project(mvp, worldX(percent, 0), 0.2, 0, view.width, view.height);
    if (!point) continue;
    const dx = Math.abs(point.x - (clientX - rect.left));
    if (dx < bestDx) {
      bestDx = dx;
      best = percent;
    }
  }
  return best;
}

let pointer = null;
world.addEventListener("pointerdown", function (event) {
  const rect = world.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const hit = hits.find(function (item) {
    return x >= item.left && x <= item.right && y >= item.top && y <= item.bottom;
  });
  pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false, hit: hit, axis: "" };
  if (hit) {
    playing = false;
    pinned = hit.knot;
    play = hit.knot.percent;
    showKnot(hit.knot);
    draw();
    return;
  }
  world.setPointerCapture(event.pointerId);
});
world.addEventListener("pointermove", function (event) {
  if (!pointer || event.pointerId !== pointer.id || pointer.hit) return;
  const dx = event.clientX - pointer.x;
  const dy = event.clientY - pointer.y;
  if (!pointer.axis) {
    if (Math.abs(dx) + Math.abs(dy) < 4) return;
    pointer.axis = Math.abs(dy) > Math.abs(dx) ? "y" : "x";
    pointer.moved = true;
    playing = false;
  }
  if (pointer.axis === "y") {
    pitch = Math.max(0.28, Math.min(0.95, pitch + (event.clientY - pointer.y) * 0.004));
    pointer.y = event.clientY;
    draw();
    return;
  }
  play = playAt(event.clientX);
  if (pinned && Math.abs(pinned.percent - play) > 0.012) pinned = null;
  pointer.x = event.clientX;
  draw();
});
world.addEventListener("pointerup", function (event) {
  if (!pointer || event.pointerId !== pointer.id) return;
  if (!pointer.hit && !pointer.moved) {
    playing = false;
    play = playAt(event.clientX);
    if (pinned && Math.abs(pinned.percent - play) > 0.012) pinned = null;
    draw();
  }
  if (world.hasPointerCapture(event.pointerId)) world.releasePointerCapture(event.pointerId);
  pointer = null;
});
toggle.addEventListener("click", function () {
  playing = !playing;
  if (playing) pinned = null;
  draw();
});

function tick(now) {
  if (!last) last = now;
  const delta = Math.min(40, now - last);
  if (!reduceMotion && playing) clock += delta / 1000;
  if (playing) {
    play += delta / 46000;
    if (play > 1) play -= 1;
    if (pinned && Math.abs(pinned.percent - play) > 0.012) pinned = null;
    draw();
  }
  last = now;
  requestAnimationFrame(tick);
}
ready = setupGl();
draw();
requestAnimationFrame(tick);
window.addEventListener("resize", function () {
  monuments = null;
  draw();
});
window.__film = {
  seek: function (value) {
    pinned = null;
    play = Math.min(1, Math.max(0, Number(value) || 0));
    playing = false;
    draw();
  },
  pause: function () { playing = false; draw(); },
  resume: function () { pinned = null; playing = true; },
  tilt: function (value) {
    pitch = Math.max(0.28, Math.min(0.95, Number(value) || pitch));
    playing = false;
    draw();
  },
  pitch: function () { return pitch; },
  webgl: function () { return !!ready; },
  spoken: function () {
    const knot = spokenNow();
    return knot ? knot.text : "";
  },
  layout: function () {
    return (monuments || []).filter(function (item) { return item.screen; }).map(function (item) {
      return {
        text: item.knot.text,
        x: Math.round(item.screen.x),
        y: Math.round(item.screen.y),
        n: item.knot.n,
        left: Math.round(item.screen.left),
        right: Math.round(item.screen.right),
        top: Math.round(item.screen.top),
        bottom: Math.round(item.screen.bottom),
      };
    });
  },
};
</script>
</body>
</html>
"""
    return html.replace("__SHOT_TITLE__", title).replace("__SHOT_DATA__", payload)
