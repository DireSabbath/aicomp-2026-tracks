"""把多支片子上反复接住的原话，按同一件事并到一起。

每一件事下面只引用原话和它出现的次数。服务方向就是这些原话，不另写口号。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from reception.load import Pool, load_zip
from reception.stage import render_shot
from reception.voice import _literal_choruses, answer_rows, build_voice, keys_for


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _lead_in(lower: str, higher: str) -> bool:
    width = min(len(lower), len(higher))
    for size in range(2, width):
        if lower.endswith(higher[:size]) or higher.endswith(lower[:size]):
            return True
    return False


def _overlaps_key(piece: str, keys: list[str]) -> bool:
    for key in keys:
        width = min(len(key), len(piece))
        for size in range(2, width + 1):
            for start in range(len(key) - size + 1):
                if key[start : start + size] in piece:
                    return True
    return False


def shared_pieces(rows: list, keys: list[str], minimum: int = 4) -> list[dict]:
    """同一支片子里，整句没有说到两遍，但有几个字反复出现。"""
    counts: Counter[str] = Counter()
    for row in rows:
        seen: set[str] = set()
        text = row.norm
        for size in range(4, 9):
            for start in range(0, len(text) - size + 1):
                piece = text[start : start + size]
                if piece in seen or _overlaps_key(piece, keys):
                    continue
                seen.add(piece)
                counts[piece] += 1
    kept = []
    ranked = sorted(counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    for piece, count in ranked:
        if count < minimum:
            break
        if any(piece in other and piece != other and counts[other] >= count for other in counts):
            continue
        if any(_lead_in(piece, earlier["text"]) for earlier in kept):
            continue
        kept.append({"text": piece, "n": count})
        if len(kept) >= 3:
            break
    return kept


def _affair(text: str, keys: list[str]) -> str:
    hit = [key for key in keys if key in text]
    pool = hit or keys
    return max(pool, key=len)


def _reading(films: list[dict]) -> str:
    bits = []
    for film in films[:4]:
        line = film["lines"][0]
        bits.append(f"《{film['title']}》里「{line['text']}」说了{line['n']}次")
    return f"这件事上，观众反复接住的是：{'，'.join(bits)}。以后的服务要接住这些原话。"


def build_depth(pools: list[Pool]) -> tuple[dict, dict]:
    shot, report = build_voice(pools)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for pool in pools:
        for video in pool.videos:
            keys = keys_for(video.title, pool.title)
            if not keys:
                continue
            lines = _literal_choruses(answer_rows(video, keys))
            if not lines:
                continue
            by_affair: dict[str, list[dict]] = defaultdict(list)
            for line in lines:
                by_affair[_affair(line["text"], keys)].append(line)
            for affair, own in by_affair.items():
                own.sort(key=lambda item: (-item["n"], item["text"]))
                grouped[affair].append(
                    {
                        "collection": pool.title,
                        "title": video.title,
                        "bvid": video.bvid,
                        "lines": own[:3],
                    }
                )
    directions = []
    for affair, films in grouped.items():
        films.sort(key=lambda item: (-item["lines"][0]["n"], item["bvid"]))
        directions.append(
            {
                "affair": affair,
                "films": films,
                "reading": _reading(films),
            }
        )
    directions.sort(key=lambda item: (-item["films"][0]["lines"][0]["n"], item["affair"]))
    chorus_films = {film["bvid"] for direction in directions for film in direction["films"]}
    unsettled = []
    for pool in pools:
        for video in pool.videos:
            if video.bvid in chorus_films:
                continue
            keys = keys_for(video.title, pool.title)
            if not keys:
                continue
            answers = answer_rows(video, keys)
            if len(answers) < 8:
                continue
            unsettled.append(
                {
                    "collection": pool.title,
                    "title": video.title,
                    "bvid": video.bvid,
                    "n_answers": len(answers),
                    "pieces": shared_pieces(answers, keys),
                }
            )
    unsettled.sort(key=lambda item: (-item["n_answers"], item["bvid"]))
    report["unsettled"] = unsettled[:8]
    asked = sum(item["passed"] for item in report["collections"])
    report["directions"] = directions
    report["depth_note"] = (
        f"点到公共事务的片子有 {asked} 支，其中 {len(chorus_films)} 支的回答收成了反复的原话。"
        "下面按事情把这些原话并在一起。服务要接住的是这些原话。"
    )
    return shot, report


def render_depth(shot: dict, report: dict) -> str:
    html = render_shot(shot)
    blocks = [
        "<div class=\"directions\">",
        "<h2>反复接住的原话</h2>",
        f"<p>{_esc(report.get('depth_note') or '')}</p>",
    ]
    directions = report.get("directions") or []
    if not directions:
        blocks.append("<p>这些片子问过了，回答还没有收成一句。不要从套话里概括服务方向。</p>")
    for direction in directions[:8]:
        blocks.append("<section class=\"direction\">")
        blocks.append(f"<h3>{_esc(direction['affair'])}</h3>")
        blocks.append(f"<p>{_esc(direction['reading'])}</p>")
        blocks.append("<ul>")
        for film in direction["films"][:4]:
            quotes = "、".join(f"「{_esc(line['text'])}」{_esc(str(line['n']))}次" for line in film["lines"][:2])
            blocks.append(f"<li>{_esc(film['title'])}：{quotes}</li>")
        blocks.append("</ul></section>")
    if len(directions) > 8:
        blocks.append(f"<p>另外 {len(directions) - 8} 件事也有反复出现的原话，记在报告里。</p>")
    unsettled = report.get("unsettled") or []
    if unsettled:
        blocks.append("<section class=\"direction\">")
        blocks.append("<h3>问过了，还没有收成一句</h3>")
        blocks.append("<p>下面这些片子有人把事情说下去了，但没有一句说到两遍。不要从各说各话里概括服务方向。</p>")
        blocks.append("<ul>")
        for film in unsettled:
            pieces = film.get("pieces") or []
            extra = ""
            if pieces:
                extra = "，其中" + "、".join(f"「{_esc(piece['text'])}」出现在 {piece['n']} 条里" for piece in pieces[:2])
            blocks.append(f"<li>{_esc(film['title'])}：{film['n_answers']} 条，没有整句说到两遍{extra}</li>")
        blocks.append("</ul></section>")
    blocks.append("</div>")
    style = (
        ".directions { margin: 0 0 16px; }"
        ".directions h2 { font-size: 15px; font-weight: 500; color: #b7a894; margin: 8px 0; }"
        ".direction { margin: 10px 0; padding: 12px 14px; background: #14110e; border-radius: 12px; }"
        ".direction h3 { font-size: 16px; margin: 0 0 6px; font-weight: 600; }"
        ".direction p, .direction li { color: #d9cbb8; font-size: 15px; }"
        ".direction ul { margin: 8px 0 0; padding-left: 1.2em; }"
    )
    return html.replace("</style>", style + "</style>", 1).replace(
        '<div class="frame">',
        "\n".join(blocks) + '\n<div class="frame">',
        1,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="按同一件事，把多支片子上反复接住的原话并到一起")
    parser.add_argument("zips", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    pools = [load_zip(path, skip_bad=True) for path in args.zips]
    shot, report = build_depth(pools)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "index.html").write_text(render_depth(shot, report), encoding="utf-8")
    for direction in report["directions"][:8]:
        print(direction["affair"], direction["reading"], flush=True)
    print(args.out / "index.html")


if __name__ == "__main__":
    main()
