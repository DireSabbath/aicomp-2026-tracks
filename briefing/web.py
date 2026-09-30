"""单页演示。正文只用 textContent 写入，避免把弹幕拼进 HTML。"""

from __future__ import annotations

import json


def render_page(report: dict) -> str:
    payload = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c")
    return _PAGE.replace("/*__DATA__*/", payload)


_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>一类视频的弹幕简报</title>
<style>
  :root { color-scheme: light; --ink: #1c1915; --muted: #5c564c; --line: #d9d2c5; --paper: #f6f3ec; --accent: #8c3a2f; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 16px/1.55 "Source Han Serif SC", "Noto Serif SC", "Songti SC", serif; color: var(--ink); background: var(--paper); }
  header, main { width: min(1100px, calc(100% - 32px)); margin: 0 auto; }
  header { padding: 28px 0 8px; }
  h1 { font-size: 28px; font-weight: 600; margin: 0 0 8px; }
  h2 { font-size: 20px; margin: 28px 0 8px; }
  h3 { font-size: 17px; margin: 16px 0 8px; }
  p.note { color: var(--muted); margin: 0; }
  nav { display: flex; gap: 8px; margin: 20px 0; }
  nav button { font: inherit; background: transparent; border: 1px solid var(--line); padding: 6px 12px; cursor: pointer; }
  nav button[aria-pressed="true"] { background: var(--ink); color: var(--paper); }
  section { display: none; padding-bottom: 48px; }
  section.active { display: block; }
  .chart { background: white; border: 1px solid var(--line); padding: 12px; overflow-x: auto; }
  svg { width: 100%; height: auto; }
  .claims { display: grid; gap: 8px; margin-top: 16px; }
  .claim { display: grid; grid-template-columns: 160px 1fr; gap: 8px; align-items: center; background: white; border: 1px solid var(--line); padding: 8px; cursor: pointer; }
  .claim strong { font-weight: 600; }
  .cells { display: grid; grid-template-columns: repeat(20, 1fr); gap: 2px; height: 36px; align-items: end; }
  .cells i { display: block; width: 100%; background: var(--accent); }
  .detail, .brief, .diff { background: white; border: 1px solid var(--line); padding: 12px 16px; margin-top: 16px; }
  .diff { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  .diff h3 { font-size: 16px; margin: 0 0 8px; }
  ul { margin: 8px 0 0; padding-left: 18px; }
  li { margin: 4px 0; }
  button.link { font: inherit; background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; text-align: left; }
  .meta { color: var(--muted); font-size: 14px; }
  @media (max-width: 800px) {
    .claim, .diff { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<header>
  <h1>一类视频的弹幕简报</h1>
  <p class="note" id="signoff"></p>
</header>
<main>
  <nav>
    <button type="button" data-view="type" aria-pressed="true">类型</button>
    <button type="button" data-view="claim" aria-pressed="false">说法</button>
    <button type="button" data-view="compare" aria-pressed="false">对照</button>
  </nav>
  <section id="type" class="active"></section>
  <section id="claim"></section>
  <section id="compare"></section>
</main>
<script>
const report = /*__DATA__*/;
const signoff = document.getElementById("signoff");
signoff.textContent = report.protocol.signoff + " " + report.protocol.claim_rule;

function show(name) {
  document.querySelectorAll("nav button").forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.view === name ? "true" : "false");
  });
  document.querySelectorAll("main section").forEach((section) => {
    section.classList.toggle("active", section.id === name);
  });
}
document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    location.hash = button.dataset.view;
  });
});
window.addEventListener("hashchange", applyHash);

function el(tag, text) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  return node;
}

function seriesSvg(series, peakSegment, yMax) {
  const width = 800, height = 220, padX = 36, padTop = 16, padBottom = 36;
  const segs = series[0].counts.length;
  const max = Math.max(1, yMax);
  const x = (index) => padX + (index / Math.max(1, segs - 1)) * (width - padX * 2);
  const y = (value) => height - padBottom - (Math.min(value, max) / max) * (height - padTop - padBottom);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const peak = Math.max(0, Math.min(segs - 1, peakSegment - 1));
  const mark = document.createElementNS("http://www.w3.org/2000/svg", "line");
  mark.setAttribute("x1", String(x(peak)));
  mark.setAttribute("x2", String(x(peak)));
  mark.setAttribute("y1", String(padTop));
  mark.setAttribute("y2", String(height - padBottom));
  mark.setAttribute("stroke", "#8c3a2f");
  mark.setAttribute("stroke-dasharray", "3 3");
  svg.appendChild(mark);
  series.forEach((line) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", line.stroke);
    path.setAttribute("stroke-width", line.width);
    path.setAttribute("points", line.counts.map((value, index) => `${x(index)},${y(value)}`).join(" "));
    svg.appendChild(path);
  });
  for (let index = 0; index < segs; index++) {
    const number = index + 1;
    if (segs > 8 && number !== 1 && number !== segs && number % 5 !== 0) continue;
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", String(x(index)));
    label.setAttribute("y", String(height - 10));
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("font-size", "12");
    label.setAttribute("fill", "#5c564c");
    label.textContent = String(number);
    svg.appendChild(label);
  }
  return svg;
}

function oneChart(counts, peakSegment) {
  return seriesSvg(
    [{ counts, stroke: "#1c1915", width: "2.5" }],
    peakSegment,
    Math.max(...counts, 1),
  );
}

function typeChart(type) {
  const yMax = Math.max(1, ...type.volume_median) * 1.25;
  const lines = type.volume_lines.map((line) => ({ counts: line.counts, stroke: "#c4b8a8", width: "1" }));
  lines.push({ counts: type.volume_median, stroke: "#1c1915", width: "2.5" });
  return seriesSvg(lines, type.volume_peak_segment, yMax);
}

function cells(counts) {
  const wrap = el("div");
  wrap.className = "cells";
  wrap.style.gridTemplateColumns = `repeat(${counts.length}, 1fr)`;
  const max = Math.max(1, ...counts);
  counts.forEach((value) => {
    const cell = document.createElement("i");
    cell.style.height = value ? `${Math.max(8, (value / max) * 100)}%` : "8%";
    cell.style.opacity = value ? "1" : "0.18";
    wrap.appendChild(cell);
  });
  return wrap;
}

function claimButton(claim, typeTitle) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "link";
  button.textContent = claim.text;
  button.addEventListener("click", () => openClaim(typeTitle, claim));
  return button;
}

function openClaim(typeTitle, claim) {
  show("claim");
  const pane = document.getElementById("claim");
  pane.replaceChildren();
  pane.appendChild(el("h2", typeTitle));
  pane.appendChild(el("p", claim.text));
  const meta = el("p");
  meta.className = "meta";
  const span = claim.span_days == null ? "没有发送时间" : `发送时间跨度 ${claim.span_days} 天`;
  meta.textContent = `覆盖 ${claim.n_videos} 条视频、${claim.n_rows} 条弹幕。进入第 ${claim.entry_segment} 段，高峰在第 ${claim.peak_segment} 段，退出第 ${claim.exit_segment} 段。缺席 ${claim.absent_videos} 条视频。${span}。`;
  pane.appendChild(meta);
  const list = el("ul");
  claim.evidence.forEach((item) => {
    const when = item.ctime == null ? "无发送时间" : new Date((item.ctime + 8 * 3600) * 1000).toISOString().slice(0, 10);
    list.appendChild(el("li", `${item.bvid} 第 ${item.segment} 段 ${item.progress_ms} 毫秒 ${when} ${item.text}`));
  });
  pane.appendChild(list);
  pane.appendChild(el("p", "名单只列出抽查用的一小批依据，条数以覆盖数字为准。日期按北京时间。不显示发言者。"));
}

const typePane = document.getElementById("type");
function chartBox(node) {
  const box = el("div");
  box.className = "chart";
  box.appendChild(node);
  return box;
}

report.types.forEach((type) => {
  const block = el("div");
  block.appendChild(el("h2", type.title));
  const baseline = type.volume_lines[0];
  block.appendChild(el("h3", "单条热度"));
  block.appendChild(el("p", baseline
    ? `清单按视频号排序后的第一条是 ${baseline.bvid}。只看这一条，数量高峰在第 ${type.baseline_peak_segment} 段。纵轴按这一条自己的最高点撑开。`
    : "这一类没有可定位的视频。"));
  if (baseline) block.appendChild(chartBox(oneChart(baseline.counts, type.baseline_peak_segment)));
  block.appendChild(el("h3", "这一类"));
  const tied = type.volume_tied_segments || [type.volume_peak_segment];
  const peakText = tied.length > 1
    ? `中位数最高的是第 ${tied.join("、")} 段。并列时高峰记在先出现的段，也就是第 ${type.volume_peak_segment} 段。`
    : `数量高峰在第 ${type.volume_peak_segment} 段。`;
  block.appendChild(el("p", `${type.n_videos} 条视频，${type.n_rows} 条弹幕。${peakText}细线是各视频，粗线是各段中位数。纵轴按中位数撑开，超出的细线在顶端截断。虚线标出记下的高峰段。横轴从左到右是片长百分比。`));
  block.appendChild(chartBox(typeChart(type)));
  block.appendChild(el("p", "下面是去掉空白后原文完全相同、且达到门槛后条数最多的说法。柱高是该说法在该段的条数。点开一条可看覆盖、进入、高峰、退出、缺席和依据。"));
  const claims = el("div");
  claims.className = "claims";
  type.claims.forEach((claim) => {
    const row = el("div");
    row.className = "claim";
    const name = el("div");
    name.appendChild(claimButton(claim, type.title));
    const small = el("div");
    small.className = "meta";
    small.textContent = `${claim.n_videos} 条视频 · ${claim.n_rows} 条 · 高峰第 ${claim.peak_segment} 段`;
    name.appendChild(small);
    row.appendChild(name);
    row.appendChild(cells(claim.segment_counts));
    claims.appendChild(row);
  });
  block.appendChild(claims);
  typePane.appendChild(block);
});

const claimPane = document.getElementById("claim");
claimPane.appendChild(el("p", "在类型页点开一条说法，这里列出它的覆盖、起伏和依据弹幕。"));

const compare = document.getElementById("compare");
const labels = {
  same_peak: "共享且高峰段相同",
  shifted: "共享但高峰段错开",
  only_a: `只在${report.types[0].title}`,
  only_b: `只在${report.types[1].title}`,
};
compare.appendChild(el("p", `共享栏里，斜线前是${report.types[0].title}的高峰段，斜线后是${report.types[1].title}的高峰段。`));
const grid = el("div");
grid.className = "diff";
Object.keys(labels).forEach((key) => {
  const card = el("div");
  const bucket = report.diff[key];
  card.appendChild(el("h3", `${labels[key]}（${bucket.count}）`));
  const list = el("ul");
  bucket.items.forEach((item) => {
    const owner = key === "only_b" ? report.types[1] : report.types[0];
    const li = el("li");
    li.appendChild(claimButton(item, owner.title));
    const extra = el("div");
    extra.className = "meta";
    extra.textContent = item.other_peak_segment
      ? `高峰第 ${item.peak_segment} 段 / 第 ${item.other_peak_segment} 段`
      : `高峰第 ${item.peak_segment} 段 · ${item.n_rows} 条`;
    li.appendChild(extra);
    list.appendChild(li);
  });
  card.appendChild(list);
  grid.appendChild(card);
});
compare.appendChild(grid);
const brief = el("div");
brief.className = "brief";
brief.appendChild(el("h2", "简报"));
report.briefing.forEach((sentence) => brief.appendChild(el("p", sentence)));
compare.appendChild(brief);

function applyHash() {
  const raw = (location.hash || "#type").slice(1);
  const claim = raw.match(/^claim-(\d+)-(\d+)$/);
  if (claim) {
    const type = report.types[Number(claim[1])];
    const item = type && type.claims[Number(claim[2])];
    if (type && item) openClaim(type.title, item);
    return;
  }
  if (raw === "compare" || raw === "claim" || raw === "type") show(raw);
}
applyHash();
</script>
</body>
</html>
"""
