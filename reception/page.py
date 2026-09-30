"""把两件事铺到片长带子上，点开是原话。"""

from __future__ import annotations

import json

from reception.analyze import (
    CROWD_RATIO,
    DENSITY_BINS,
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
    gathered = [thing for thing in built["shown"] if thing["mode"] == "topic"]
    if gathered:
        thing = max(gathered, key=lambda item: (item["n_videos"], item["n_rows"], item["text"]))
        lines.append(f"人多的地方围着「{thing['text']}」。")
    dialogues = [thing for thing in built["shown"] if thing["mode"] == "dialogue"]
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
        lines.append(f"这一类里还有{built['hidden']}件事。带子上每一段只放出现在最多条视频里的那一件。")
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
        f"带子上每一段只放一件，也就是这一段里出现在最多条视频上的那句原话。"
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
            "hidden": built["hidden"],
            "solo_count": built["solo_count"],
        }

    return {
        "left": side(report["left"]),
        "right": side(report["right"]),
        "match": report["match"],
        "readings": report["readings"],
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
body {{ margin: 0; font: 16px/1.5 "WenQuanYi Micro Hei", "Noto Sans CJK SC", "Source Han Sans SC", sans-serif; background: #f6f1e7; color: #241c16; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 28px; margin: 0 0 8px; }}
.note, .method, .legend, .read {{ margin: 8px 0; }}
.method, .legend {{ color: #6d6256; }}
.strip-wrap {{ margin: 28px 0; }}
.strip-title {{ font-weight: 700; margin-bottom: 8px; }}
.strip {{ background: #efe6d6; border-radius: 12px; padding: 12px 0 8px; }}
.film {{ position: relative; min-height: 72px; margin: 0 80px; }}
.crowd {{ position: absolute; top: 0; bottom: 0; background: rgba(196, 92, 46, 0.28); }}
.word {{ position: absolute; transform: translateX(-50%); max-width: 8em; padding: 4px 8px; border: 0; border-radius: 999px; background: #fffdf8; cursor: pointer; font: inherit; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.word.topic {{ box-shadow: inset 0 0 0 2px #8c3a2f; }}
.word.dialogue {{ box-shadow: inset 0 0 0 2px #2f5d50; }}
.word.shared {{ background: #f3e1b5; }}
.word.shifted {{ outline: 2px dashed #8a6a1f; }}
.word.open {{ background: #241c16; color: #fffdf8; }}
.axis {{ display: flex; justify-content: space-between; color: #6d6256; font-size: 13px; margin: 4px 80px 0; }}
.evidence {{ margin-top: 12px; background: #fffdf8; border-radius: 12px; padding: 12px 16px; }}
.evidence li {{ margin: 6px 0; }}
.meta {{ color: #6d6256; font-size: 13px; }}
@media (max-width: 700px) {{
  h1 {{ font-size: 22px; }}
  .film, .axis {{ margin-left: 36px; margin-right: 36px; }}
  .word {{ max-width: 6.2em; }}
}}
</style>
</head>
<body>
<main>
<h1>一类视频的观众接收</h1>
<p class="note" id="note"></p>
<p class="method" id="method"></p>
<p class="legend">色带是人多的位置。红边是围着一件事，绿边是接话。浅底是两边都有，虚线是位置错开。点一下看原话。</p>
<div id="readings"></div>
<div id="strips"></div>
</main>
<script>
const report = {payload};
document.getElementById("note").textContent = report.note;
document.getElementById("method").textContent = report.method;
const readings = document.getElementById("readings");
report.readings.forEach((line) => {{
  const p = document.createElement("p");
  p.className = "read";
  p.textContent = line;
  readings.appendChild(p);
}});
const shared = new Set();
const shifted = new Set();
report.match.pairs.forEach((pair) => {{
  shared.add(pair.left);
  shared.add(pair.right);
  if (pair.shifted) {{
    shifted.add(pair.left);
    shifted.add(pair.right);
  }}
}});
function layout(film) {{
  const buttons = [...film.querySelectorAll(".word")];
  buttons.forEach((button) => {{
    const median = Number(button.dataset.median);
    button.style.transform = "translateX(-50%)";
    button.style.left = (median * 100) + "%";
    button.style.top = "8px";
  }});
  const filmRect = film.getBoundingClientRect();
  buttons.forEach((button) => {{
    const rect = button.getBoundingClientRect();
    if (rect.width === 0) return;
    if (rect.left < filmRect.left) {{
      button.style.transform = "translateX(0)";
      button.style.left = "0%";
    }} else if (rect.right > filmRect.right) {{
      button.style.transform = "translateX(-100%)";
      button.style.left = "100%";
    }}
  }});
  const lanes = [];
  buttons.forEach((button) => {{
    const rect = button.getBoundingClientRect();
    let lane = 0;
    while (lanes[lane] && lanes[lane].some((other) => rect.left < other.right - 2 && rect.right > other.left + 2)) lane += 1;
    if (!lanes[lane]) lanes[lane] = [];
    lanes[lane].push(rect);
    button.style.top = (8 + lane * 42) + "px";
  }});
  film.style.height = (24 + Math.max(1, buttons.length ? lanes.length : 1, 1) * 42) + "px";
}}
function mount(built) {{
  const wrap = document.createElement("section");
  wrap.className = "strip-wrap";
  const title = document.createElement("div");
  title.className = "strip-title";
  let caption = built.title + " · " + built.n_videos + " 条视频 · 能定位 " + built.n_placed + " 条";
  if (built.n_skipped) caption += " · " + built.n_skipped + " 条对不上片长";
  title.textContent = caption;
  wrap.appendChild(title);
  const strip = document.createElement("div");
  strip.className = "strip";
  const film = document.createElement("div");
  film.className = "film";
  built.crowded.forEach((span) => {{
    const band = document.createElement("div");
    band.className = "crowd";
    band.style.left = (span.start * 100) + "%";
    band.style.width = ((span.end - span.start) * 100) + "%";
    film.appendChild(band);
  }});
  built.shown.forEach((thing) => {{
    const button = document.createElement("button");
    button.type = "button";
    button.className = "word " + thing.mode + (shared.has(thing.text) ? " shared" : "") + (shifted.has(thing.text) ? " shifted" : "");
    button.style.left = (thing.median * 100) + "%";
    button.dataset.median = String(thing.median);
    button.textContent = thing.text;
    button.addEventListener("click", () => {{
      film.querySelectorAll(".word").forEach((item) => item.classList.remove("open"));
      button.classList.add("open");
      show(thing);
    }});
    film.appendChild(button);
  }});
  layout(film);
  strip.appendChild(film);
  wrap.appendChild(strip);
  const axis = document.createElement("div");
  axis.className = "axis";
  const head = document.createElement("span");
  head.textContent = "片头";
  const tail = document.createElement("span");
  tail.textContent = "片尾";
  axis.append(head, tail);
  wrap.appendChild(axis);
  const box = document.createElement("div");
  box.className = "evidence";
  box.hidden = true;
  wrap.appendChild(box);
  function show(thing) {{
    box.hidden = false;
    box.replaceChildren();
    const head = document.createElement("div");
    head.textContent = thing.text;
    box.appendChild(head);
    const meta = document.createElement("div");
    meta.className = "meta";
    const kind = thing.mode === "topic" ? "人多的地方围着这件事" : "人少的地方在接话";
    meta.textContent = kind + " · 出现在 " + thing.n_videos + " 条视频里";
    box.appendChild(meta);
    const list = document.createElement("ul");
    thing.evidence.forEach((row) => {{
      const li = document.createElement("li");
      const at = Math.round(row.percent * 100);
      li.textContent = row.content + " · 片长的" + at + "% · " + row.bvid;
      list.appendChild(li);
    }});
    box.appendChild(list);
  }}
  return wrap;
}}
const strips = document.getElementById("strips");
strips.appendChild(mount(report.left));
strips.appendChild(mount(report.right));
layout(strips.children[0].querySelector(".film"));
layout(strips.children[1].querySelector(".film"));
window.addEventListener("resize", () => {{
  strips.querySelectorAll(".film").forEach(layout);
}});
</script>
</body>
</html>
"""
