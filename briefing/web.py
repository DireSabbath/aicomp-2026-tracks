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
  h3 { font-size: 17px; margin: 18px 0 8px; }
  p.note, .meta { color: var(--muted); }
  .meta { font-size: 14px; margin: 4px 0; }
  nav { display: flex; gap: 8px; margin: 20px 0; }
  nav button { font: inherit; background: transparent; border: 1px solid var(--line); padding: 6px 12px; cursor: pointer; }
  nav button[aria-pressed="true"] { background: var(--ink); color: var(--paper); }
  section { display: none; padding-bottom: 48px; }
  section.active { display: block; }
  .chart { background: white; border: 1px solid var(--line); padding: 12px; overflow-x: auto; }
  svg { width: 100%; height: auto; }
  .stream { background: white; border: 1px solid var(--line); padding: 8px 12px; margin-top: 8px; }
  .detail, .brief, .card { background: white; border: 1px solid var(--line); padding: 12px 16px; margin-top: 12px; }
  .diff { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  .diff h3 { font-size: 16px; margin: 0 0 8px; }
  ul { margin: 8px 0 0; padding-left: 18px; }
  li { margin: 4px 0; }
  button.link { font: inherit; background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; text-align: left; }
  @media (max-width: 800px) {
    .diff { grid-template-columns: 1fr; }
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
signoff.textContent = report.protocol.purpose;
const rule = document.createElement("p");
rule.className = "note";
rule.textContent = report.protocol.signoff + report.protocol.claim_rule;
signoff.after(rule);
const frozen = document.createElement("p");
frozen.className = "meta";
const proto = report.protocol;
frozen.textContent = `词取 ${proto.word_min_chars} 到 ${proto.word_max_chars} 个字。完整说法是去掉标点后 ${proto.phrase_min_chars} 到 ${proto.phrase_max_chars} 个字，并且整条弹幕就是这句。至少 ${proto.min_videos} 条视频、${proto.min_rows} 次，才写入这一类的结论。两边最密相差不超过片长的 ${proto.peak_tolerance_pct}%，记成位置差不多。`;
rule.after(frozen);

function show(name) {
  document.querySelectorAll("nav button").forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.view === name ? "true" : "false");
  });
  document.querySelectorAll("main section").forEach((section) => {
    section.classList.toggle("active", section.id === name);
  });
  window.scrollTo(0, 0);
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

function seriesSvg(series, peakSegment, yMax, height) {
  const width = 800;
  height = height || 220;
  const padX = 36, padTop = 16, padBottom = 36;
  const segs = series[0].counts.length;
  const max = Math.max(1, yMax);
  const x = (index) => padX + (index / Math.max(1, segs - 1)) * (width - padX * 2);
  const y = (value) => height - padBottom - (Math.min(value, max) / max) * (height - padTop - padBottom);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const peaks = Array.isArray(peakSegment) ? peakSegment : [peakSegment];
  peaks.forEach((segment) => {
    const peak = Math.max(0, Math.min(segs - 1, segment - 1));
    const mark = document.createElementNS("http://www.w3.org/2000/svg", "line");
    mark.setAttribute("x1", String(x(peak)));
    mark.setAttribute("x2", String(x(peak)));
    mark.setAttribute("y1", String(padTop));
    mark.setAttribute("y2", String(height - padBottom));
    mark.setAttribute("stroke", "#8c3a2f");
    mark.setAttribute("stroke-dasharray", "3 3");
    svg.appendChild(mark);
  });
  series.forEach((line) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", line.stroke);
    path.setAttribute("stroke-width", line.width);
    path.setAttribute("points", line.counts.map((value, index) => `${x(index)},${y(value)}`).join(" "));
    svg.appendChild(path);
  });
  [0, 25, 50, 75, 100].forEach((pct) => {
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", String(x((pct / 100) * (segs - 1))));
    label.setAttribute("y", String(height - 10));
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("font-size", "12");
    label.setAttribute("fill", "#5c564c");
    label.textContent = pct === 0 ? "开头" : pct === 100 ? "片尾" : `${pct}%`;
    svg.appendChild(label);
  });
  return svg;
}

function oneChart(counts, peakSegment, height) {
  return seriesSvg(
    [{ counts, stroke: "#8c3a2f", width: "2.5" }],
    peakSegment,
    Math.max(...counts, 1),
    height || 220,
  );
}

function typeChart(type) {
  const yMax = Math.max(1, ...type.volume_median) * 1.25;
  const lines = type.volume_lines.map((line) => ({ counts: line.counts, stroke: "#c4b8a8", width: "1" }));
  lines.push({ counts: type.volume_median, stroke: "#1c1915", width: "2.5" });
  return seriesSvg(lines, type.volume_tied_segments, yMax, 220);
}

function chartBox(node) {
  const box = el("div");
  box.className = "chart";
  box.appendChild(node);
  return box;
}

function whenText(ctime) {
  if (ctime == null) return "没有发送日期";
  return new Date((ctime + 8 * 3600) * 1000).toISOString().slice(0, 10);
}

function neighborLine(claim) {
  if (!claim.neighbors || !claim.neighbors.length) return "同一处最密的地方，没有其他已写入结论的说法。";
  const bits = claim.neighbors.map((item) => `${item.text}（最密在${item.peak_where}）`);
  return `同一处最密的还有：${bits.join("、")}。`;
}

function renderClaim(typeTitle, claim) {
  show("claim");
  const pane = document.getElementById("claim");
  pane.replaceChildren();
  const back = document.createElement("button");
  back.type = "button";
  back.className = "link";
  back.textContent = "返回说法列表";
  back.addEventListener("click", () => { location.hash = "claim"; });
  pane.appendChild(back);
  pane.appendChild(el("h2", typeTitle));
  pane.appendChild(el("h3", claim.text));
  pane.appendChild(el("p", claim.reading));
  if (claim.span_days != null) {
    const span = el("p");
    span.className = "meta";
    span.textContent = `这些原话最早和最晚相隔 ${claim.span_days} 天。日期是北京时间。`;
    pane.appendChild(span);
  }
  pane.appendChild(el("p", neighborLine(claim)));
  pane.appendChild(chartBox(oneChart(claim.segment_counts, claim.peak_segment, 180)));
  pane.appendChild(el("h3", "依据弹幕"));
  const list = el("ul");
  claim.evidence.forEach((item) => {
    list.appendChild(el("li", `${item.bvid} · ${item.where} · ${whenText(item.ctime)} · ${item.text}`));
  });
  pane.appendChild(list);
  pane.appendChild(el("p", "这里只列出一小批原话，方便回去核对。总数以上面的次数为准。不显示是谁发的。"));
}

function openListed(typeIndex, layer, index) {
  const type = report.types[typeIndex];
  const list = layer === "phrase" ? type.phrases : type.words;
  const claim = type && list[index];
  if (!claim) {
    location.hash = "claim";
    return;
  }
  renderClaim(type.title, claim);
}

function jumpToClaim(typeIndex, layer, text, fallback) {
  const type = report.types[typeIndex];
  const list = layer === "phrase" ? type.phrases : type.words;
  const index = list.findIndex((item) => item.text === text);
  if (index >= 0) {
    location.hash = `${layer}-${typeIndex}-${index}`;
    return;
  }
  renderClaim(type.title, fallback);
}

function streamBlock(typeIndex, layer, claim, index) {
  const box = el("div");
  box.className = "stream";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "link";
  button.textContent = claim.text;
  button.addEventListener("click", () => { location.hash = `${layer}-${typeIndex}-${index}`; });
  box.appendChild(button);
  const meta = el("p", claim.summary);
  meta.className = "meta";
  box.appendChild(meta);
  box.appendChild(chartBox(oneChart(claim.segment_counts, claim.peak_segment, 150)));
  return box;
}

const typePane = document.getElementById("type");
report.types.forEach((type, typeIndex) => {
  const block = el("div");
  block.appendChild(el("h2", type.title));
  const baseline = type.volume_lines[0];
  block.appendChild(el("h3", "只看一条"));
  block.appendChild(el("p", baseline
    ? `清单里按视频号排在最前的是 ${baseline.bvid}。${type.baseline_reading}这一条图的高低按它自己的最高点来画。`
    : "这一类没有可定位的视频。"));
  if (baseline) block.appendChild(chartBox(oneChart(baseline.counts, type.baseline_peak_segment, 220)));
  block.appendChild(el("h3", "这一类放在一起"));
  block.appendChild(el("p", `${type.volume_reading}细线是每一条视频，粗线是这些视频的中间水平。粗线高的地方，就是这一类通常比较热闹的位置。横轴是片子从开头到结尾。特别冲的细线会在图顶被截断，免得一条视频把整类压扁。`));
  block.appendChild(chartBox(typeChart(type)));
  block.appendChild(el("h3", "反复提到的词"));
  block.appendChild(el("p", "线从左到右是片子的进度，高低是这个词在那个位置出现的次数。点开能看到它盖住多少条视频、哪些视频里没有，以及原话。"));
  type.words.forEach((claim, index) => block.appendChild(streamBlock(typeIndex, "word", claim, index)));
  block.appendChild(el("h3", "重复的完整说法"));
  block.appendChild(el("p", "这是去掉标点之后、整条弹幕都是这一句的次数。书名号、逗号不同而剩下的字相同，算同一句。"));
  type.phrases.forEach((claim, index) => block.appendChild(streamBlock(typeIndex, "phrase", claim, index)));
  typePane.appendChild(block);
});

function claimCard(typeIndex, layer, claim, index) {
  const card = el("div");
  card.className = "card";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "link";
  button.textContent = claim.text;
  button.addEventListener("click", () => { location.hash = `${layer}-${typeIndex}-${index}`; });
  card.appendChild(button);
  card.appendChild(el("p", claim.reading));
  if (claim.span_days != null) {
    const span = el("p", `最早和最晚相隔 ${claim.span_days} 天。`);
    span.className = "meta";
    card.appendChild(span);
  }
  card.appendChild(el("p", neighborLine(claim)));
  return card;
}

function soloBlock(heading, items, count) {
  const wrap = el("div");
  wrap.appendChild(el("h3", `${heading}（${count}）`));
  if (!count) {
    wrap.appendChild(el("p", "没有要单独列出的条目。"));
    return wrap;
  }
  const list = el("ul");
  items.forEach((item) => {
    const sample = item.evidence && item.evidence[0];
    list.appendChild(el("li", sample ? `${item.text} · ${item.n_rows} 次 · 例如 ${sample.text}` : `${item.text} · ${item.n_rows} 次`));
  });
  wrap.appendChild(list);
  if (count > items.length) {
    const more = el("p", `上面列出 ${items.length} 条，这一类一共 ${count} 条。`);
    more.className = "meta";
    wrap.appendChild(more);
  }
  return wrap;
}

function renderClaimIndex() {
  show("claim");
  const pane = document.getElementById("claim");
  pane.replaceChildren();
  pane.appendChild(el("p", "写入这一类结论的，是至少出现在多条视频里的词和完整说法。只在一条视频里出现的，列在每类的最后，不写入结论。"));
  report.types.forEach((type, typeIndex) => {
    pane.appendChild(el("h2", type.title));
    pane.appendChild(el("h3", "反复提到的词"));
    type.words.forEach((claim, index) => pane.appendChild(claimCard(typeIndex, "word", claim, index)));
    pane.appendChild(el("h3", "重复的完整说法"));
    type.phrases.forEach((claim, index) => pane.appendChild(claimCard(typeIndex, "phrase", claim, index)));
    pane.appendChild(el("h3", "只在一条视频里出现，不写入这一类的结论"));
    pane.appendChild(soloBlock("词", type.solo_words, type.solo_word_count));
    pane.appendChild(soloBlock("完整说法", type.solo_phrases, type.solo_phrase_count));
  });
}

function renderDiffGrid(title, diff, layer) {
  const wrap = el("div");
  wrap.appendChild(el("h2", title));
  const labels = {
    same_peak: "两边都有，位置差不多",
    shifted: "两边都有，位置错开了",
    only_a: `只在${report.types[0].title}`,
    only_b: `只在${report.types[1].title}`,
  };
  const grid = el("div");
  grid.className = "diff";
  Object.keys(labels).forEach((key) => {
    const card = el("div");
    const bucket = diff[key];
    card.appendChild(el("h3", `${labels[key]}（${bucket.count}）`));
    const list = el("ul");
    bucket.items.forEach((item) => {
      const ownerIndex = key === "only_b" ? 1 : 0;
      const li = el("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "link";
      button.textContent = item.text;
      button.addEventListener("click", () => jumpToClaim(ownerIndex, layer, item.text, item));
      li.appendChild(button);
      const extra = el("div");
      extra.className = "meta";
      extra.textContent = item.other_peak_where
        ? `${item.n_videos} 条视频里出现过 · 最密在${item.peak_where} / ${item.other_peak_where}`
        : `${item.n_videos} 条视频里出现过 · 最密在${item.peak_where} · ${item.n_rows} 次`;
      li.appendChild(extra);
      list.appendChild(li);
    });
    card.appendChild(list);
    grid.appendChild(card);
  });
  wrap.appendChild(grid);
  return wrap;
}

const compare = document.getElementById("compare");
compare.appendChild(el("p", `对照${report.types[0].title}和${report.types[1].title}。位置差不多，是指两边最密的地方相差不超过片长的${proto.peak_tolerance_pct}%。斜线前是${report.types[0].title}，斜线后是${report.types[1].title}。`));
compare.appendChild(renderDiffGrid("词", report.diff, "word"));
compare.appendChild(renderDiffGrid("完整说法", report.phrase_diff, "phrase"));
const brief = el("div");
brief.className = "brief";
brief.appendChild(el("h2", "简报"));
report.briefing.forEach((sentence) => brief.appendChild(el("p", sentence)));
compare.appendChild(brief);

function applyHash() {
  const raw = (location.hash || "#type").slice(1);
  const listed = raw.match(/^(word|phrase)-(\d+)-(\d+)$/);
  if (listed) {
    openListed(Number(listed[2]), listed[1], Number(listed[3]));
    return;
  }
  if (raw === "claim") renderClaimIndex();
  else if (raw === "compare" || raw === "type") show(raw);
}
applyHash();
</script>
</body>
</html>
"""
