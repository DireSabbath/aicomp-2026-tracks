"""把两件事铺到片长带子上，点开是原话。"""

from __future__ import annotations

import json

from reception.analyze import (
    CROWD_RATIO,
    DENSITY_BINS,
    LAYER,
    SIMILAR,
    TIME_GAP,
    WINDOWS,
    build_type,
    match_types,
)
from reception.load import Pool


TITLES = {
    "heishenhua": "黑神话官方",
    "yuanshen-preview": "原神前瞻",
    "luoxiang": "罗翔说刑法",
    "new-sanguo": "吐槽新三国",
    "xiaoyuehan": "小约翰可汗",
}


def display_title(pool: Pool) -> str:
    return TITLES.get(pool.title, pool.title)


def _percent(value: float) -> int:
    return int(round(value * 100))


def where(start: float, end: float) -> str:
    left, right = _percent(start), _percent(end)
    if left == right:
        if left <= 0:
            return "片头"
        if left >= 100:
            return "片尾"
        return f"片长的{left}%附近"
    if left <= 0 and right >= 100:
        return "整条片子"
    if left <= 0:
        return f"开头到片长的{right}%"
    if right >= 100:
        return f"片长的{left}%到片尾"
    return f"片长的{left}%到{right}%"


def _crowd_distance(thing: dict, crowded: list[dict]) -> float:
    median = thing["median"]
    gaps = []
    for span in crowded:
        if span["start"] <= median < span["end"]:
            gaps.append(0)
        elif median < span["start"]:
            gaps.append(span["start"] - median)
        else:
            gaps.append(median - span["end"])
    return min(gaps) if gaps else 0


def readings(built: dict) -> list[str]:
    lines = []
    title = built["title"]
    crowded = built["crowded"]
    if crowded:
        places = "、".join(where(span["start"], span["end"]) for span in crowded)
        lines.append(f"{title}人多的地方在{places}。")
    else:
        lines.append(f"{title}没有挤在一处的弹幕。")
    gathered = [thing for thing in built["shown"] if thing.get("role") == "place" and thing["mode"] == "topic"]
    if gathered:
        thing = max(gathered, key=lambda item: (item["n_videos"], item["n_rows"], item["text"]))
        lines.append(f"人多的地方收着「{thing['text']}」。")
    choruses = [thing for thing in built["shown"] if thing.get("role") == "chorus"]
    if choruses:
        thing = max(choruses, key=lambda item: (item["n_videos"], item["n_rows"], item["text"]))
        lines.append(f"顺着整段片子都在说「{thing['text']}」。")
    dialogues = [thing for thing in built["shown"] if thing.get("role") == "place" and thing["mode"] == "dialogue"]
    if dialogues and crowded:
        thing = max(dialogues, key=lambda item: (_crowd_distance(item, crowded), item["n_videos"], item["text"]))
        lines.append(
            f"人少的地方在接话，例如「{thing['text']}」，落在{where(thing['median'], thing['median'])}，和人多的地方分开。"
        )
    elif dialogues:
        lines.append(f"人少的地方在接话，例如「{dialogues[0]['text']}」。")
    if built["solo_count"]:
        lines.append(f"只在一条视频里的事有{built['solo_count']}件，没有写进这一类。")
    if built["hidden"]:
        lines.append(f"这一类里还有{built['hidden']}件事，没有放到带子上。")
    return lines


def compare_readings(left: dict, right: dict, matched: dict) -> list[str]:
    lines = [f"对照的是{left['title']}和{right['title']}。"]
    aligned = [pair for pair in matched["pairs"] if not pair["shifted"]]
    shifted = [pair for pair in matched["pairs"] if pair["shifted"]]
    if aligned:
        lines.append(f"两边都有、位置也接近的，例如「{aligned[0]['left']}」。")
    if shifted:
        lines.append(f"两边都有、但位置错开的，例如「{shifted[0]['left']}」。")
    if matched["only_left"]:
        lines.append(f"只在{left['title']}的，例如「{matched['only_left'][0]}」。")
    if matched["only_right"]:
        lines.append(f"只在{right['title']}的，例如「{matched['only_right'][0]}」。")
    if not matched["pairs"] and not matched["only_left"] and not matched["only_right"]:
        lines.append("带子上还没有可以对照的事。")
    return lines


def method_text() -> str:
    return (
        f"字面接近是二字、三字的余弦，不低于 {SIMILAR}。"
        f"两句的中位位置相差超过片长的 {round(TIME_GAP * 100)}%，就不再并成一件事。"
        f"先把片长分成 {WINDOWS} 段：段里条数高于各段中位的，围着连接最多的那句收；其余段里，字面接得上的收到一起。"
        f"人多是把片长分成 {DENSITY_BINS} 格，连在一起、并且达到这一类峰值 {round(CROWD_RATIO * 100)}% 的那些格。"
        f"一件事有多少条落在自己中位位置前后 {round(TIME_GAP * 100)}% 以内，和这一类的中位比：更紧的是收在一处，更松的是顺着片子走。"
        f"收在一处的，每一段放视频数最多的那句，字大。"
        f"顺着片子走的，视频数最多的 {LAYER} 句用淡字重复写在带子上，其余每一段再放视频数最多的一句，字下面是它实际走过的一段。"
        f"两边字面接近的连成一条线。中位位置差超过片长的 {round(TIME_GAP * 100)}%，线就是斜的，光从先说的一边走到后说的一边。"
    )


def build_report(left: Pool, right: Pool) -> dict:
    built_left = build_type(left)
    built_right = build_type(right)
    built_left["title"] = display_title(left)
    built_right["title"] = display_title(right)
    matched = match_types(built_left, built_right)
    return {
        "left": built_left,
        "right": built_right,
        "match": matched,
        "readings": readings(built_left) + readings(built_right) + compare_readings(built_left, built_right, matched),
        "note": "试点按字面接近归并。同义不同字还没有并到一块。这些视频算不算同一类，还没有人签字。材料里没有发言者，页面不显示是谁发的。",
        "method": method_text(),
    }


def _page_thing(thing: dict) -> dict:
    return {
        "text": thing["text"],
        "start": thing["start"],
        "end": thing["end"],
        "median": thing["median"],
        "n_videos": thing["n_videos"],
        "n_rows": thing["n_rows"],
        "mode": thing["mode"],
        "role": thing.get("role", "place"),
        "rank": thing.get("rank", 0),
        "p25": thing.get("p25", thing["median"]),
        "p75": thing.get("p75", thing["median"]),
        "marks": thing.get("marks") or [thing["median"]],
        "evidence": thing["evidence"],
    }


def _page_report(report: dict) -> dict:
    def side(built: dict) -> dict:
        return {
            "title": built["title"],
            "n_videos": built["n_videos"],
            "n_placed": built["n_placed"],
            "n_skipped": built.get("n_skipped", 0),
            "crowded": built["crowded"],
            "shown": [_page_thing(thing) for thing in built["shown"]],
            "layers": [_page_thing(thing) for thing in built.get("layers") or built["shown"]],
            "hidden": built["hidden"],
            "solo_count": built["solo_count"],
        }

    return {
        "left": side(report["left"]),
        "right": side(report["right"]),
        "match": report["match"],
        "note": report["note"],
        "method": report["method"],
    }


def render_page(report: dict) -> str:
    payload = json.dumps(_page_report(report), ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>一类视频的观众接收</title>
<style>
body {{ margin: 0; font: 16px/1.5 "WenQuanYi Micro Hei", "Noto Sans CJK SC", "Source Han Sans SC", sans-serif; background: #f3ecdf; color: #241910; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 28px; margin: 0 0 16px; }}
.stage {{ position: relative; padding: 18px 0 12px; border-radius: 22px; background: radial-gradient(90% 55% at 50% 42%, rgba(232, 176, 108, 0.2), transparent 62%), #1c1612; color: #f6efe4; }}
.bridges {{ position: absolute; inset: 0; width: 100%; height: 100%; z-index: 1; pointer-events: none; }}
.gap {{ position: relative; z-index: 2; height: 128px; }}
.gap::before {{ content: ""; position: absolute; left: 10%; right: 10%; top: 18%; bottom: 18%; background: radial-gradient(closest-side, rgba(240, 215, 162, 0.12), transparent 72%); pointer-events: none; }}
.node {{ position: absolute; z-index: 4; width: 12px; height: 12px; padding: 0; border: 0; border-radius: 50%; background: #f0d7a2; box-shadow: 0 0 0 5px rgba(240, 215, 162, 0.18), 0 0 18px rgba(240, 215, 162, 0.95); cursor: pointer; transform: translate(-50%, -50%); }}
.node.aligned {{ width: 16px; height: 16px; background: #fff8ec; }}
.node.hot {{ box-shadow: 0 0 0 7px rgba(255, 248, 236, 0.28), 0 0 22px #fff8ec; }}
.strip-wrap {{ position: relative; z-index: 3; margin: 0; }}
.strip-title {{ font-weight: 700; padding: 0 80px 8px; }}
.strip {{ background: transparent; padding: 4px 0 0; }}
.film {{ position: relative; min-height: 72px; margin: 0 80px; border-radius: 12px; background: rgba(255, 248, 238, 0.03); }}
.crowd {{ position: absolute; top: 0; bottom: 0; background: rgba(232, 126, 72, 0.34); }}
.word {{ position: absolute; z-index: 5; transform: translateX(-50%); width: max-content; max-width: 8em; padding: 2px 8px; border: 0; background: transparent; cursor: pointer; font: inherit; line-height: 1.25; text-align: center; white-space: normal; color: #f6efe4; }}
.word.place {{ border-radius: 999px; background: #f7f1e8; color: #241910; }}
.word.place.topic {{ box-shadow: inset 0 0 0 2px #c46a52; }}
.word.place.dialogue {{ box-shadow: inset 0 0 0 2px #7dbea8; }}
.word.travel {{ border-radius: 0; padding-bottom: 4px; }}
.word.chorus {{ color: rgba(246, 239, 228, 0.48); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 6em; }}
.word.linked.place {{ box-shadow: 0 0 0 2px #f0d7a2, 0 0 16px rgba(240, 215, 162, 0.75); }}
.word.linked.travel, .word.linked.chorus {{ color: #f0d7a2; text-shadow: 0 0 12px rgba(240, 215, 162, 0.9); }}
.word.open {{ background: #f0d7a2; color: #1c1612; }}
.range {{ position: absolute; z-index: 1; height: 0; border-top: 2px solid rgba(246, 239, 228, 0.38); pointer-events: none; }}
.chorus-line {{ position: relative; margin: 2px 80px 6px; }}
.axis {{ display: flex; justify-content: space-between; color: #6d6256; font-size: 13px; margin: 8px 80px 0; }}
.key {{ display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin: 14px 0; color: #6d6256; font-size: 14px; }}
.chip {{ padding: 2px 8px; border-radius: 999px; background: #fffdf8; white-space: nowrap; }}
.chip.place {{ box-shadow: inset 0 0 0 2px #8c3a2f; }}
.chip.thread {{ background: transparent; border-radius: 0; box-shadow: inset 0 -2px 0 #c48a3a; }}
.note {{ margin: 8px 0 0; }}
details {{ margin-top: 18px; color: #6d6256; }}
summary {{ cursor: pointer; }}
.method {{ margin: 8px 0; }}
.evidence {{ margin-top: 12px; background: #fffdf8; border-radius: 12px; padding: 12px 16px; }}
.evidence li {{ margin: 6px 0; }}
.meta {{ color: #6d6256; font-size: 13px; }}
.sidehead {{ margin-top: 10px; font-weight: 700; }}
@media (max-width: 700px) {{
  h1 {{ font-size: 22px; }}
  .film, .axis, .chorus-line {{ margin-left: 28px; margin-right: 28px; }}
  .strip-title {{ padding-left: 28px; padding-right: 28px; }}
  .word {{ max-width: 7em; }}
  .gap {{ height: 96px; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .node {{ transition: none; }}
}}
</style>
</head>
<body>
<main>
<h1>一类视频的观众接收</h1>
<div class="stage" id="stage"></div>
<div class="axis"><span>片头</span><span>片尾</span></div>
<div class="key">
  <span class="chip place">大字收在这一处，越大视频越多</span>
  <span class="chip thread">线连着两边的同一句，斜的就是错开</span>
  <span>没有线的，只在这一边</span>
</div>
<p class="note" id="note"></p>
<div class="evidence" id="evidence" hidden></div>
<details>
<summary>这张图怎么来的</summary>
<p class="method" id="method"></p>
</details>
</main>
<script>
const report = {payload};
document.getElementById("note").textContent = report.note;
document.getElementById("method").textContent = report.method;
const linkedLeft = new Set(report.match.pairs.map((pair) => pair.left));
const linkedRight = new Set(report.match.pairs.map((pair) => pair.right));
const stage = document.getElementById("stage");
const evidence = document.getElementById("evidence");
const canvas = document.createElement("canvas");
canvas.className = "bridges";
stage.appendChild(canvas);
const gap = document.createElement("div");
gap.className = "gap";
let hot = -1;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
function layout(film) {{
  const buttons = [...film.querySelectorAll(".word")];
  buttons.forEach((button) => {{
    const median = Number(button.dataset.median);
    button.style.transform = "translateX(-50%)";
    button.style.right = "auto";
    button.style.left = (median * 100) + "%";
    button.style.top = "8px";
  }});
  const filmRect = film.getBoundingClientRect();
  buttons.forEach((button) => {{
    const rect = button.getBoundingClientRect();
    if (rect.width === 0) return;
    if (rect.left < filmRect.left) {{
      button.style.transform = "none";
      button.style.left = "0";
      button.style.right = "auto";
    }} else if (rect.right > filmRect.right) {{
      button.style.transform = "none";
      button.style.left = "auto";
      button.style.right = "0";
    }}
  }});
  const lanes = [];
  buttons.forEach((button) => {{
    const rect = button.getBoundingClientRect();
    let lane = 0;
    while (lanes[lane] && lanes[lane].some((other) => {{
      const taken = other.getBoundingClientRect();
      return rect.left < taken.right - 2 && rect.right > taken.left + 2;
    }})) lane += 1;
    if (!lanes[lane]) lanes[lane] = [];
    lanes[lane].push(button);
    button.dataset.lane = String(lane);
  }});
  const laneTop = [];
  let cursor = 8;
  lanes.forEach((group) => {{
    laneTop.push(cursor);
    const height = Math.max(...group.map((button) => button.offsetHeight), 18);
    cursor += height + 8;
  }});
  buttons.forEach((button) => {{
    button.style.top = laneTop[Number(button.dataset.lane)] + "px";
  }});
  film.style.height = Math.max(72, cursor + 8) + "px";
  film.querySelectorAll(".range").forEach((range) => {{
    const button = film.querySelector('.word[data-key="' + range.dataset.key + '"]');
    if (!button) return;
    range.style.top = (button.offsetTop + button.offsetHeight - 1) + "px";
  }});
}}
function mount(built, side) {{
  const linked = side === "left" ? linkedLeft : linkedRight;
  const wrap = document.createElement("section");
  wrap.className = "strip-wrap";
  const title = document.createElement("div");
  title.className = "strip-title";
  title.textContent = built.title;
  wrap.appendChild(title);
  const strip = document.createElement("div");
  strip.className = "strip";
  const film = document.createElement("div");
  film.className = "film";
  const chorusLine = document.createElement("div");
  chorusLine.className = "chorus-line";
  built.crowded.forEach((span) => {{
    const band = document.createElement("div");
    band.className = "crowd";
    band.style.left = (span.start * 100) + "%";
    band.style.width = ((span.end - span.start) * 100) + "%";
    film.appendChild(band);
  }});
  const words = built.layers || built.shown;
  const places = words.filter((thing) => (thing.role || "place") === "place");
  const maxVideos = Math.max(...places.map((thing) => thing.n_videos), 1);
  let key = 0;
  words.forEach((thing) => {{
    const role = thing.role || "place";
    const spots = role === "chorus" ? (thing.marks || [thing.median]) : [thing.median];
    const weight = thing.n_videos / maxVideos;
    let anchorIndex = 0;
    spots.forEach((spot, index) => {{
      if (Math.abs(Number(spot) - Number(thing.median)) < Math.abs(Number(spots[anchorIndex]) - Number(thing.median))) anchorIndex = index;
    }});
    spots.forEach((spot, index) => {{
      const button = document.createElement("button");
      button.type = "button";
      button.className = "word " + role + " " + thing.mode + (linked.has(thing.text) ? " linked" : "");
      button.style.left = (Number(spot) * 100) + "%";
      if (role === "place") {{
        button.style.fontSize = Math.round(16 + 18 * weight) + "px";
        button.style.fontWeight = "700";
      }} else if (role === "travel") {{
        button.style.fontSize = "15px";
        button.style.fontWeight = "600";
        button.dataset.key = String(key);
        const range = document.createElement("div");
        range.className = "range";
        range.dataset.key = String(key);
        let start = Number(thing.p25);
        let end = Number(thing.p75);
        if (end - start < 0.012) {{
          start = Math.max(0, Number(thing.median) - 0.006);
          end = Math.min(1, Number(thing.median) + 0.006);
        }}
        range.style.left = (start * 100) + "%";
        range.style.width = ((end - start) * 100) + "%";
        film.appendChild(range);
        key += 1;
      }} else {{
        button.style.fontSize = "13px";
      }}
      button.style.zIndex = role === "place" ? String(20 + thing.n_videos) : "10";
      button.dataset.median = String(spot);
      button.dataset.text = thing.text;
      button.dataset.side = side;
      button.dataset.anchor = index === anchorIndex ? "1" : "0";
      button.textContent = thing.text;
      button.addEventListener("click", () => {{
        const pairIndex = report.match.pairs.findIndex((pair) => (side === "left" ? pair.left : pair.right) === thing.text);
        if (pairIndex >= 0) focusPair(pairIndex);
        else focusThing(thing);
      }});
      if (role === "chorus") chorusLine.appendChild(button);
      else film.appendChild(button);
    }});
  }});
  layout(film);
  strip.appendChild(film);
  if (chorusLine.childElementCount) {{
    layout(chorusLine);
    strip.appendChild(chorusLine);
  }}
  wrap.appendChild(strip);
  return wrap;
}}
function findThing(side, text) {{
  const built = side === "left" ? report.left : report.right;
  return (built.layers || built.shown).find((thing) => thing.text === text);
}}
function percentLabel(value) {{
  return "片长的" + Math.round(Number(value) * 100) + "%";
}}
function fillList(thing) {{
  const list = document.createElement("ul");
  thing.evidence.forEach((row) => {{
    const li = document.createElement("li");
    li.textContent = row.content + " · " + percentLabel(row.percent) + " · " + row.bvid;
    list.appendChild(li);
  }});
  return list;
}}
function focusThing(thing) {{
  hot = -1;
  stage.querySelectorAll(".word").forEach((item) => item.classList.remove("open"));
  stage.querySelectorAll(".node").forEach((item) => item.classList.remove("hot"));
  evidence.hidden = false;
  evidence.replaceChildren();
  const head = document.createElement("div");
  head.textContent = thing.text;
  evidence.appendChild(head);
  const meta = document.createElement("div");
  meta.className = "meta";
  const kind = thing.role === "chorus" ? "，这一类到处在说" : thing.role === "travel" ? "，顺着片子走" : "，收在这一处";
  meta.textContent = thing.n_videos + " 条视频" + kind + "。没有连到另一边。";
  evidence.appendChild(meta);
  evidence.appendChild(fillList(thing));
  draw(performance.now());
}}
function focusPair(index) {{
  hot = index;
  const pair = report.match.pairs[index];
  stage.querySelectorAll(".word").forEach((item) => item.classList.remove("open"));
  stage.querySelectorAll(".node").forEach((item) => item.classList.toggle("hot", Number(item.dataset.index) === index));
  stage.querySelectorAll(".word[data-anchor='1']").forEach((item) => {{
    if ((item.dataset.side === "left" && item.dataset.text === pair.left) || (item.dataset.side === "right" && item.dataset.text === pair.right)) item.classList.add("open");
  }});
  const leftThing = findThing("left", pair.left);
  const rightThing = findThing("right", pair.right);
  evidence.hidden = false;
  evidence.replaceChildren();
  const head = document.createElement("div");
  head.textContent = pair.left === pair.right ? pair.left : pair.left + "  —  " + pair.right;
  evidence.appendChild(head);
  const meta = document.createElement("div");
  meta.className = "meta";
  const earlier = pair.left_at <= pair.right_at ? report.left.title : report.right.title;
  meta.textContent = report.left.title + "在" + percentLabel(pair.left_at) + "，" + report.right.title + "在" + percentLabel(pair.right_at) + "。" + (pair.shifted ? "位置错开，光从" + earlier + "走过去。" : "落在同一处。");
  evidence.appendChild(meta);
  if (leftThing) {{
    const name = document.createElement("div");
    name.className = "sidehead";
    name.textContent = report.left.title;
    evidence.appendChild(name);
    evidence.appendChild(fillList(leftThing));
  }}
  if (rightThing) {{
    const name = document.createElement("div");
    name.className = "sidehead";
    name.textContent = report.right.title;
    evidence.appendChild(name);
    evidence.appendChild(fillList(rightThing));
  }}
  draw(performance.now());
}}
function anchorButton(side, text) {{
  return stage.querySelector(".word[data-anchor='1'][data-side='" + side + "'][data-text='" + CSS.escape(text) + "']");
}}
function curveOf(pair, stageRect) {{
  const upper = anchorButton("left", pair.left);
  const lower = anchorButton("right", pair.right);
  const upperWrap = stage.querySelectorAll(".strip-wrap")[0];
  const lowerWrap = stage.querySelectorAll(".strip-wrap")[1];
  if (!upper || !lower || !upperWrap || !lowerWrap) return null;
  const a = upper.getBoundingClientRect();
  const b = lower.getBoundingClientRect();
  const topBox = upperWrap.getBoundingClientRect();
  const bottomBox = lowerWrap.getBoundingClientRect();
  const x1 = a.left + a.width / 2 - stageRect.left;
  const x2 = b.left + b.width / 2 - stageRect.left;
  const wordTop = {{ x: x1, y: a.top + a.height / 2 - stageRect.top }};
  const rimTop = {{ x: x1, y: topBox.bottom - stageRect.top }};
  const rimBottom = {{ x: x2, y: bottomBox.top - stageRect.top }};
  const wordBottom = {{ x: x2, y: b.top + b.height / 2 - stageRect.top }};
  const span = rimBottom.y - rimTop.y;
  const p0 = rimTop;
  const p3 = rimBottom;
  const p1 = {{ x: x1, y: rimTop.y + span * 0.62 }};
  const p2 = {{ x: x2, y: rimTop.y + span * 0.38 }};
  return {{ wordTop, rimTop, wordBottom, rimBottom, p0, p1, p2, p3 }};
}}
function cubic(curve, t) {{
  const u = 1 - t;
  return {{
    x: u * u * u * curve.p0.x + 3 * u * u * t * curve.p1.x + 3 * u * t * t * curve.p2.x + t * t * t * curve.p3.x,
    y: u * u * u * curve.p0.y + 3 * u * u * t * curve.p1.y + 3 * u * t * t * curve.p2.y + t * t * t * curve.p3.y,
  }};
}}
function cubicAngle(curve, t) {{
  const u = 1 - t;
  const dx = 3 * u * u * (curve.p1.x - curve.p0.x) + 6 * u * t * (curve.p2.x - curve.p1.x) + 3 * t * t * (curve.p3.x - curve.p2.x);
  const dy = 3 * u * u * (curve.p1.y - curve.p0.y) + 6 * u * t * (curve.p2.y - curve.p1.y) + 3 * t * t * (curve.p3.y - curve.p2.y);
  return Math.atan2(dy, dx);
}}
function paintCurve(ctx, curve, color, width, alpha) {{
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.beginPath();
  ctx.moveTo(curve.p0.x, curve.p0.y);
  ctx.bezierCurveTo(curve.p1.x, curve.p1.y, curve.p2.x, curve.p2.y, curve.p3.x, curve.p3.y);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.shadowColor = color;
  ctx.shadowBlur = 16;
  ctx.stroke();
  ctx.restore();
}}
function paintBead(ctx, curve, t, color) {{
  const point = cubic(curve, t);
  ctx.save();
  ctx.fillStyle = "#fff8ec";
  ctx.shadowColor = color;
  ctx.shadowBlur = 16;
  ctx.beginPath();
  ctx.arc(point.x, point.y, 3.2, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}}
function paintArrow(ctx, curve, t, color) {{
  const point = cubic(curve, t);
  const angle = cubicAngle(curve, t);
  ctx.save();
  ctx.translate(point.x, point.y);
  ctx.rotate(angle);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(7, 0);
  ctx.lineTo(-6, 4);
  ctx.lineTo(-6, -4);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}}
function draw(now) {{
  const stageRect = stage.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(1, Math.round(stageRect.width * dpr));
  const height = Math.max(1, Math.round(stageRect.height * dpr));
  if (canvas.width !== width || canvas.height !== height) {{
    canvas.width = width;
    canvas.height = height;
  }}
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, stageRect.width, stageRect.height);
  report.match.pairs.forEach((pair, index) => {{
    const curve = curveOf(pair, stageRect);
    if (!curve) return;
    const selected = hot === index;
    const alpha = hot >= 0 && !selected ? 0.22 : 1;
    const color = pair.shifted ? "rgba(240, 186, 112, 0.95)" : "rgba(255, 246, 230, 0.98)";
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.lineCap = "round";
    ctx.shadowColor = color;
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.moveTo(curve.wordTop.x, curve.wordTop.y);
    ctx.lineTo(curve.rimTop.x, curve.rimTop.y);
    ctx.moveTo(curve.rimBottom.x, curve.rimBottom.y);
    ctx.lineTo(curve.wordBottom.x, curve.wordBottom.y);
    ctx.stroke();
    ctx.restore();
    paintCurve(ctx, curve, color, selected ? 2.8 : 1.7, alpha);
    const forward = Number(pair.left_at) <= Number(pair.right_at);
    const travel = reduceMotion ? 0.72 : ((now / 3400) + index * 0.31) % 1;
    const along = forward ? travel : 1 - travel;
    if (!reduceMotion) {{
      for (let step = 3; step >= 1; step -= 1) {{
        const behind = forward ? along - step * 0.035 : along + step * 0.035;
        if (behind <= 0 || behind >= 1) continue;
        const ghost = cubic(curve, behind);
        ctx.save();
        ctx.globalAlpha = alpha * (0.18 * (4 - step));
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(ghost.x, ghost.y, 2.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }}
    }}
    paintBead(ctx, curve, along, color);
    paintArrow(ctx, curve, forward ? 0.97 : 0.03, color);
    const node = stage.querySelector(".node[data-index='" + index + "']");
    if (!node) return;
    const jewel = cubic(curve, 0.5);
    node.style.left = jewel.x + "px";
    node.style.top = jewel.y + "px";
  }});
  const placed = [];
  stage.querySelectorAll(".node").forEach((node) => {{
    const x = parseFloat(node.style.left);
    const y = parseFloat(node.style.top);
    let nextY = y;
    placed.forEach((other) => {{
      if (Math.abs(other.x - x) < 22 && Math.abs(other.y - nextY) < 20) nextY = other.y + 22;
    }});
    node.style.top = nextY + "px";
    placed.push({{ x, y: nextY }});
  }});
}}
const upper = mount(report.left, "left");
const lower = mount(report.right, "right");
stage.append(upper, gap, lower);
report.match.pairs.forEach((pair, index) => {{
  const node = document.createElement("button");
  node.type = "button";
  node.className = "node" + (pair.shifted ? " shifted" : " aligned");
  node.dataset.index = String(index);
  node.setAttribute("aria-label", pair.left + " 连到 " + pair.right);
  node.addEventListener("click", () => focusPair(index));
  stage.appendChild(node);
}});
function settle() {{
  stage.querySelectorAll(".film, .chorus-line").forEach(layout);
  draw(performance.now());
}}
settle();
if (!reduceMotion && report.match.pairs.length) {{
  const loop = (now) => {{
    draw(now);
    requestAnimationFrame(loop);
  }};
  requestAnimationFrame(loop);
}}
window.addEventListener("resize", settle);
</script>
</body>
</html>
"""
