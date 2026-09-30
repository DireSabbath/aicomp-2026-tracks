"""把一个类型里重复、字面接近的原话收成一件事。

人多的位置用全部能定位的弹幕。至少出现两次的字面才能成为一件事，字面接近的再并到一起。
密集的一段里，围着连接最多的那句收成一件事。稀疏的一段里，互相接得上的原话收成一件事。
只出现在一条视频里的，不写进这一类。
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.neighbors import NearestNeighbors

from reception.load import Pool, Row

WINDOWS = 10
DENSITY_BINS = 50
CROWD_RATIO = 0.7
SIMILAR = 0.72
TIME_GAP = 0.10
# 余弦 0.72、片长一成、十段、五十格、峰值七成、至多八件，在跑试点片子之前定下。
# 看到归并结果之后不改这些数。近邻个数含查询自己那一格，多出来的相似句靠对称边补上。
NEARBY = 8
EVIDENCE = 8
SHOW = 8


def _dense_windows(rows: list[Row]) -> set[int]:
    counts = [0] * WINDOWS
    for row in rows:
        counts[min(WINDOWS - 1, int(row.percent * WINDOWS))] += 1
    midpoint = sorted(counts)[len(counts) // 2]
    return {index for index, count in enumerate(counts) if count > midpoint}


def crowded_spans(rows: list[Row]) -> list[dict]:
    if not rows:
        return []
    counts = np.zeros(DENSITY_BINS)
    for row in rows:
        counts[min(DENSITY_BINS - 1, int(row.percent * DENSITY_BINS))] += 1
    smooth = np.convolve(counts, [1, 1, 1], mode="same") / 3
    peak = float(smooth.max())
    if peak <= 0:
        return []
    hot = smooth >= peak * CROWD_RATIO
    spans = []
    start = None
    for index, flag in enumerate(hot):
        if flag and start is None:
            start = index
        if not flag and start is not None:
            spans.append(_span(start, index))
            start = None
    if start is not None:
        spans.append(_span(start, DENSITY_BINS))
    return spans


def _span(start: int, end: int) -> dict:
    return {"start": start / DENSITY_BINS, "end": end / DENSITY_BINS}


def _vectors(norms: list[str]):
    vectorizer = HashingVectorizer(
        analyzer="char",
        ngram_range=(2, 3),
        n_features=2**12,
        alternate_sign=False,
        norm="l2",
    )
    return vectorizer.transform(norms)


def _neighbors(matrix) -> list[list[int]]:
    count = matrix.shape[0]
    adjacent = [set() for _ in range(count)]
    if count < 2:
        return [[] for _ in range(count)]
    neighbors = min(NEARBY, count)
    finder = NearestNeighbors(n_neighbors=neighbors, metric="cosine", algorithm="brute")
    finder.fit(matrix)
    distances, indices = finder.kneighbors(matrix)
    for left, row_distances, row_indices in zip(range(count), distances, indices):
        for distance, right in zip(row_distances, row_indices):
            right = int(right)
            if left == right:
                continue
            if 1 - float(distance) >= SIMILAR:
                adjacent[left].add(right)
                adjacent[right].add(left)
    return [sorted(links) for links in adjacent]


def _cluster_window(indexes: list[int], matrix, dense: bool) -> list[list[int]]:
    if not indexes:
        return []
    local = matrix[indexes]
    adjacent = _neighbors(local)
    if not dense:
        return _components(indexes, adjacent)
    degree = [len(links) for links in adjacent]
    assigned: set[int] = set()
    groups = []
    for local_index in sorted(range(len(indexes)), key=lambda item: (-degree[item], indexes[item])):
        if local_index in assigned:
            continue
        group = [indexes[local_index]]
        assigned.add(local_index)
        for other in adjacent[local_index]:
            if other not in assigned:
                assigned.add(other)
                group.append(indexes[other])
        groups.append(group)
    return groups


def _components(indexes: list[int], adjacent: list[list[int]]) -> list[list[int]]:
    seen: set[int] = set()
    groups = []
    for start in range(len(indexes)):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        group = []
        while stack:
            current = stack.pop()
            group.append(indexes[current])
            for other in adjacent[current]:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        groups.append(group)
    return groups


class _Union:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left, right = self.find(left), self.find(right)
        if left != right:
            self.parent[right] = left


def _inside(percent: float, spans: list[dict]) -> bool:
    return any(span["start"] <= percent < span["end"] or (span["end"] == 1 and percent == 1) for span in spans)


def _evidence(rows: list[Row], representative: str) -> list[dict]:
    seen: set[str] = set()
    picked = []
    ordered = sorted(rows, key=lambda item: (item.content != representative, item.percent, item.content))
    for row in ordered:
        if row.content in seen:
            continue
        seen.add(row.content)
        picked.append(
            {
                "content": row.content,
                "bvid": row.bvid,
                "percent": row.percent,
                "ctime": row.ctime,
            }
        )
        if len(picked) >= EVIDENCE:
            break
    return picked


def _thing(norms: list[str], grouped: dict[str, list[Row]], crowded: list[dict], norm_index: dict[str, int]) -> dict:
    rows = [row for norm in norms for row in grouped[norm]]
    percents = [row.percent for row in rows]
    videos = sorted({row.bvid for row in rows})
    # 代表原话：离这组中位位置最近、并且字面就是成员的那句出现最多的写法
    median = float(np.median(percents))
    by_content: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        by_content[row.content].append(row)
    representative = min(
        by_content,
        key=lambda content: (
            abs(float(np.median([row.percent for row in by_content[content]])) - median),
            -len(by_content[content]),
            content,
        ),
    )
    mode = "topic" if _inside(median, crowded) else "dialogue"
    return {
        "text": representative,
        "norms": norms,
        "start": min(percents),
        "end": max(percents),
        "median": median,
        "n_videos": len(videos),
        "n_rows": len(rows),
        "videos": videos,
        "mode": mode,
        "evidence": _evidence(rows, representative),
        "anchor": norm_index[norms[0]],
    }


def build_type(pool: Pool) -> dict:
    rows = pool.rows
    grouped: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[row.norm].append(row)
    candidates = sorted(norm for norm, items in grouped.items() if len(items) >= 2)
    norm_index = {norm: index for index, norm in enumerate(candidates)}
    crowded = crowded_spans(rows)
    dense = _dense_windows(rows)
    unions = _Union(len(candidates))
    medians = [float(np.median([row.percent for row in grouped[norm]])) for norm in candidates]
    # 每个字面只参加它中位位置所在的那一段。个别跑偏的弹幕不把两头的事粘成一件。
    if len(candidates) >= 2:
        matrix = _vectors(candidates)
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
    for norm in candidates:
        buckets[unions.find(norm_index[norm])].append(norm)
    things = []
    solos = []
    for norms in buckets.values():
        videos = {row.bvid for norm in norms for row in grouped[norm]}
        record = _thing(norms, grouped, crowded, norm_index)
        if len(videos) >= 2:
            things.append(record)
        else:
            solos.append(
                {
                    "text": record["text"],
                    "n_rows": record["n_rows"],
                    "bvid": next(iter(videos)),
                }
            )
    things.sort(key=lambda item: (-(item["end"] - item["start"]), -item["n_videos"], item["text"]))
    solos.sort(key=lambda item: (-item["n_rows"], item["text"]))
    shown = things[:SHOW]
    return {
        "title": pool.title,
        "n_videos": len(pool.videos),
        "n_rows": len(rows),
        "n_placed": len(rows),
        "n_skipped": pool.skipped,
        "crowded": crowded,
        "things": things,
        "shown": shown,
        "hidden": max(0, len(things) - len(shown)),
        "solos": solos[:SHOW],
        "solo_count": len(solos),
    }


def match_types(left: dict, right: dict) -> dict:
    """两边字面接近的事配成一对。位置差超过一条带子的一成，记为错开。"""
    pairs = []
    used: set[int] = set()
    for item in left["shown"]:
        best = None
        best_score = SIMILAR
        for index, other in enumerate(right["shown"]):
            if index in used:
                continue
            score = _pair_score(item["text"], other["text"])
            if score >= best_score:
                best = index
                best_score = score
        if best is None:
            continue
        used.add(best)
        other = right["shown"][best]
        pairs.append(
            {
                "left": item["text"],
                "right": other["text"],
                "score": best_score,
                "shifted": abs(item["median"] - other["median"]) > TIME_GAP,
            }
        )
    paired_left = {pair["left"] for pair in pairs}
    paired_right = {pair["right"] for pair in pairs}
    return {
        "pairs": pairs,
        "only_left": [item["text"] for item in left["shown"] if item["text"] not in paired_left],
        "only_right": [item["text"] for item in right["shown"] if item["text"] not in paired_right],
    }


def _pair_score(left: str, right: str) -> float:
    from reception.load import normalize

    matrix = _vectors([normalize(left), normalize(right)])
    return float((matrix @ matrix.T).toarray()[0, 1])
