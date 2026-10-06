"""弹幕当作民声，只看标题里在问公共事务的片子。

问号本身、法字嵌在别的词里，都不算。前瞻、预告、实机、版本不算。
回答要含着标题里那件事，并且把这件事说下去。套话丢掉。
同一句反复出现，才是以后的服务要接住的方向。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from reception.load import Pool, Row, Video, load_zip, normalize
from reception.shot import build_shot
from reception.stage import render_shot

SHOW = ("前瞻", "预告", "实机", "版本")
# 标题里点到这些，才算这支片子在问一件公共的事。
# 历史、战争、国家、政府、社会、真相在这些合集里多半是片子题材或剧情，不放进这张清单。
MATTER = (
    "正当防卫",
    "防卫",
    "文身",
    "纹身",
    "未成年",
    "父母",
    "孩子",
    "打死",
    "救命",
    "医疗",
    "医院",
    "无罪",
    "犯罪",
    "刑法",
    "法律",
    "违法",
    "公平",
    "死刑",
    "判刑",
    "刑罚",
    "警察",
    "法院",
    "婚姻",
    "教育",
    "工资",
    "养老",
    "女性",
    "权利",
    "良心",
    "道德",
    "受害者",
    "监狱",
    "虐待",
    "性侵",
    "拐卖",
    "家暴",
    "抢劫",
    "盗窃",
    "诈骗",
    "受贿",
    "霸凌",
    "催收",
    "酒驾",
    "赌博",
    "讨薪",
    "房东",
    "租客",
)
# 这些合集本身就是在讲案情。标题在发问、但没点到上面的词时，再从标题里取短词。
LEGAL_POOLS = {"guo-criminal-3", "luoxiang-live"}
ASK_MARKS = ("吗", "是否", "算不算", "该不该", "怎么办", "要不要", "怎么判")
_CONTENT_STOP = {
    "罗翔", "老师", "直播", "课堂", "如何", "为什么", "是不是", "该不该", "怎么办",
    "凭什么", "到底", "算不算", "要不要", "怎么判", "是否", "一个", "我们", "你们",
    "他们", "自己", "这个", "那个", "什么", "怎么", "还是", "就是", "可以", "不是",
    "没有", "知道", "觉得", "真的", "已经", "现在", "一个", "一下", "因为", "所以",
    "如果", "但是", "然后", "以及", "郭律", "郭庆梓", "律师", "视频", "弹幕",
}
RITUAL = {
    "老师好",
    "哈哈哈",
    "哈哈",
    "哈哈哈哈",
    "前方高能",
    "高能预警",
    "前方高能预警",
    "梦幻联动",
    "打卡",
    "弹幕护体",
    "总有一款适合你",
    "这就不奇怪了",
}
CHAIN = (
    "弹幕是观众当场说的话，当作民声。"
    "只有片子在问一件公共的事，这些话才算在回答，而不是在等预告。"
    "反复接住的原话，就是以后服务要接住的方向。"
)
# 除掉事项词之后还要留下这么多字，才算把这件事说下去，而不是把标题又念了一遍。
SAID = 4


def content_keys(title: str) -> list[str]:
    """标题在发问、又没有点到事项词时，留下标题里的短词。"""
    parts = re.split(r"(?:吗|是否|算不算|该不该|怎么办|要不要|怎么判)|[^\u4e00-\u9fff]+", title)
    found = []
    for part in parts:
        if not part or part in _CONTENT_STOP or not 2 <= len(part) <= 4:
            continue
        if part not in found:
            found.append(part)
        if len(found) >= 4:
            break
    return found


def keys_for(title: str, pool: str = "") -> list[str]:
    keys = public_keys(title)
    if keys or pool not in LEGAL_POOLS:
        return keys
    if not any(mark in title for mark in ASK_MARKS):
        return []
    return content_keys(title)


def public_keys(title: str) -> list[str]:
    if any(word in title for word in SHOW):
        return []
    found: list[str] = []
    for word in MATTER:
        if word not in title:
            continue
        if any(word != kept and word in kept for kept in found):
            continue
        found = [kept for kept in found if kept not in word]
        found.append(word)
    return found[:12]


def is_ritual(norm: str) -> bool:
    if len(norm) <= 1 or norm in RITUAL:
        return True
    return set(norm) <= set("哈呵嘿啊6")


def _remainder(norm: str, keys: list[str]) -> str:
    kept = norm
    for key in sorted(keys, key=len, reverse=True):
        kept = kept.replace(normalize(key), "")
    return kept


def answer_rows(video: Video, keys: list[str]) -> list[Row]:
    found = []
    for row in video.rows:
        if is_ritual(row.norm):
            continue
        hit = [key for key in keys if key in row.content]
        if not hit:
            continue
        kept = _remainder(row.norm, hit)
        if len(kept) < SAID or set(kept) <= set("哈呵啊嘿6"):
            continue
        found.append(row)
    return found


def _chorus(rows: list[Row]) -> int:
    if not rows:
        return 0
    peak = max(Counter(row.norm for row in rows).values())
    return peak if peak >= 2 else 0


def _literal_choruses(rows: list[Row]) -> list[dict]:
    counts: dict[str, list[Row]] = {}
    for row in rows:
        counts.setdefault(row.norm, []).append(row)
    spoken = []
    for group in counts.values():
        if len(group) < 2:
            continue
        text = Counter(row.content for row in group).most_common(1)[0][0]
        spoken.append({"text": text, "n": len(group)})
    spoken.sort(key=lambda item: (-item["n"], item["text"]))
    return spoken[:3]


def _direction(hubs: list[dict]) -> str:
    if not hubs:
        return "片子问过了，回答还没有收成一句。不要从套话里概括服务方向。"
    quoted = "、".join(f"「{item['text']}」" for item in hubs[:3])
    return f"观众反复接住的是：{quoted}。以后的服务要接住这些原话。"


def _apply_copy(shot: dict, video: Video, answers: list[Row], keys: list[str], other_choruses: int) -> dict:
    hubs = sorted(
        (knot for knot in shot["knots"] if knot["hub"]),
        key=lambda knot: (-knot["n"], knot["text"]),
    )
    direction = _direction(hubs)
    keys_text = "、".join(keys)
    shot["note"] = (
        f"{CHAIN}"
        f"这一页是《{video.title}》，标题里的事是{keys_text}。"
        f"全片能定位 {len(video.rows)} 条，含着这件事并说下去的有 {len(answers)} 条。"
        f"{direction}"
        + (
            f"另外 {other_choruses} 支片子也有说了至少两遍的原话，记在报告里。这一页立的是重复最多的那句。"
            if other_choruses
            else ""
        )
        + "材料里没有发言者，页面不显示是谁发的。"
    )
    shot["method"] = (
        "标题要落到一件公共的事上，这支片子才进入。"
        "问号本身不算，法、罪、刑、案单字嵌在别的词里也不算。"
        "前瞻、预告、实机、版本不进入。"
        "老师好、梦幻联动、总有一款适合你、这就不奇怪了这类套话丢掉。"
        + shot["method"].replace(
            "每一条能定位的弹幕是一粒光",
            "把这件事说下去的原话才是一粒光",
            1,
        )
        + "立成一句是因为同一句出现了多遍，不是另做的情感判断。"
    )
    shot["keys"] = keys
    shot["direction"] = direction
    return shot


def build_voice(pools: list[Pool]) -> tuple[dict, dict]:
    collections = []
    candidates = []
    for pool in pools:
        passed = 0
        answers_n = 0
        for video in pool.videos:
            keys = keys_for(video.title, pool.title)
            if not keys:
                continue
            passed += 1
            answers = answer_rows(video, keys)
            answers_n += len(answers)
            candidates.append((video, keys, answers, pool.title))
        collections.append(
            {
                "title": pool.title,
                "seen": len(pool.videos),
                "passed": passed,
                "answers": answers_n,
            }
        )
    report = {"chain": CHAIN, "collections": collections, "choruses": [], "shown": None}
    if not candidates:
        empty = Video("", "没有片子把公共的事放在标题上", [])
        shot = build_shot(empty)
        shot["note"] = f"{CHAIN}这几份材料里没有这样的片子。材料里没有发言者，页面不显示是谁发的。"
        shot["method"] = shot["note"]
        shot["direction"] = "没有可接住的原话。"
        shot["keys"] = []
        report["shown"] = {"title": empty.title, "bvid": "", "keys": [], "direction": shot["direction"], "hubs": []}
        return shot, report

    ranked = sorted(
        candidates,
        key=lambda item: (-_chorus(item[2]), -len(item[2]), item[0].bvid),
    )
    for video, keys, answers, pool_title in ranked:
        literal = _literal_choruses(answers)
        if not literal:
            continue
        report["choruses"].append(
            {
                "collection": pool_title,
                "title": video.title,
                "bvid": video.bvid,
                "keys": keys,
                "n_answers": len(answers),
                "lines": literal,
            }
        )
    video, keys, answers, _pool_title = ranked[0]
    others = sum(1 for item in report["choruses"] if item["bvid"] != video.bvid)
    shot = _apply_copy(build_shot(Video(video.bvid, video.title, answers)), video, answers, keys, others)
    hubs = sorted(
        ({"text": knot["text"], "n": knot["n"]} for knot in shot["knots"] if knot["hub"]),
        key=lambda item: (-item["n"], item["text"]),
    )
    report["shown"] = {
        "title": video.title,
        "bvid": video.bvid,
        "keys": keys,
        "n_rows": len(video.rows),
        "n_answers": len(answers),
        "direction": shot["direction"],
        "hubs": hubs[:3],
    }
    return shot, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="用民声这条链看标题里在问公共事务的片子")
    parser.add_argument("zips", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    pools = [load_zip(path, skip_bad=True) for path in args.zips]
    for pool in pools:
        print(f"{pool.title} {len(pool.videos)} 条视频，能定位 {len(pool.rows)} 条", flush=True)
    shot, report = build_voice(pools)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "index.html").write_text(render_shot(shot), encoding="utf-8")
    shown = report["shown"] or {}
    print(shown.get("title", ""), flush=True)
    print(shown.get("direction", ""), flush=True)
    print(args.out / "index.html")
    if args.serve:
        handler = lambda *a, **k: SimpleHTTPRequestHandler(*a, directory=str(args.out), **k)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
        print(f"http://127.0.0.1:{args.port}/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
