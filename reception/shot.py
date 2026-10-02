"""把一条片子上的原话收成可点的亮处。

重复至少两次的字面才能成为一句。字面接近、时间也靠近的，收成同一句。
只出现一次的留在光点里，不单独长成大字。
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from reception.analyze import (
    EVIDENCE,
    SIMILAR,
    TIME_GAP,
    WINDOWS,
    _Union,
    _cluster_window,
    _dense_windows,
    _neighbors,
    _vectors,
)
from reception.load import Video


def _slot(text: str) -> int:
    value = 2166136261
    for char in text:
        value ^= ord(char)
        value = (value * 16777619) & 0xFFFFFFFF
    return value % 1000


def _families(video: Video, grouped: dict[str, list]) -> list[list[str]]:
    norms = sorted(norm for norm, rows in grouped.items() if len(rows) >= 2)
    if not norms:
        return []
    medians = [float(np.median([row.percent for row in grouped[norm]])) for norm in norms]
    unions = _Union(len(norms))
    if len(norms) >= 2:
        matrix = _vectors(norms)
        dense = _dense_windows(video.rows)
        by_window: dict[int, list[int]] = defaultdict(list)
        for index, median in enumerate(medians):
            by_window[min(WINDOWS - 1, int(median * WINDOWS))].append(index)
        for window, indexes in by_window.items():
            for group in _cluster_window(indexes, matrix, window in dense):
                head = group[0]
                for other in group[1:]:
                    unions.union(head, other)
        adjacent = _neighbors(matrix)
        for left, links in enumerate(adjacent):
            for right in links:
                if abs(medians[left] - medians[right]) <= TIME_GAP:
                    unions.union(left, right)
    buckets: dict[int, list[str]] = defaultdict(list)
    for index, norm in enumerate(norms):
        buckets[unions.find(index)].append(norm)
    return list(buckets.values())


def build_shot(video: Video) -> dict:
    grouped: dict[str, list] = defaultdict(list)
    for row in video.rows:
        grouped[row.norm].append(row)
    knots = []
    for family, norms in enumerate(_families(video, grouped)):
        members = []
        rows = [row for norm in norms for row in grouped[norm]]
        for norm in norms:
            own = grouped[norm]
            text = Counter(row.content for row in own).most_common(1)[0][0]
            members.append(
                {
                    "text": text,
                    "percent": float(np.median([row.percent for row in own])),
                    "n": len(own),
                }
            )
        members.sort(key=lambda item: (-item["n"], item["percent"], item["text"]))
        family_n = sum(item["n"] for item in members)
        seen: set[str] = set()
        samples = []
        for row in sorted(rows, key=lambda item: (item.content != members[0]["text"], item.percent, item.content)):
            if row.content in seen:
                continue
            seen.add(row.content)
            samples.append(row.content)
            if len(samples) >= EVIDENCE:
                break
        for index, member in enumerate(members):
            knots.append(
                {
                    "text": member["text"],
                    "percent": member["percent"],
                    "n": member["n"],
                    "family_n": family_n,
                    "family": family,
                    "hub": index == 0,
                    "samples": samples if index == 0 else [],
                }
            )
    mist = [
        {"text": rows[0].content, "percent": rows[0].percent}
        for norm, rows in grouped.items()
        if len(rows) == 1
    ]
    dots = [[round(row.percent, 4), _slot(row.norm)] for row in video.rows]
    hubs = [knot for knot in knots if knot["hub"]]
    play = max(hubs, key=lambda knot: (knot["n"], -knot["percent"], knot["text"]))["percent"] if hubs else 0.5
    return {
        "title": video.title,
        "bvid": video.bvid,
        "n_rows": len(video.rows),
        "play": play,
        "knots": knots,
        "mist": mist,
        "dots": dots,
        "similar": SIMILAR,
        "time_gap": TIME_GAP,
        "note": "这一页只看一条片子。同义不同字还没有并到一块。材料里没有发言者，页面不显示是谁发的。",
        "method": (
            f"每一条能定位的弹幕是一粒光，光堆得越高，当时人越多。"
            f"字面余弦不低于 {SIMILAR}、两句中位位置相差不超过片长的 {round(TIME_GAP * 100)}%，收成一句。"
            "至少出现两次才有资格写成字。画面上立着重复最多的几句，字越大，重复越多。"
            "光带到哪一句，下面就读哪一句。点那一句，能看到原话。"
        ),
    }
