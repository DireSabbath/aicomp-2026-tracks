"""从已定位的弹幕算出接收结构。说法是词，或去掉标点后的整句。"""

from __future__ import annotations

from collections import defaultdict

from briefing.protocol import (
    DIFF_ITEMS,
    EVIDENCE_SAMPLE,
    MIN_ROWS,
    MIN_VIDEOS,
    NEIGHBOR_ITEMS,
    PEAK_TOLERANCE,
    SEGMENTS,
    SOLO_ITEMS,
    TOP_CLAIMS,
    TOP_PHRASES,
)
from briefing.units import display_raw, split_units


def _bounds(segment: int, segments: int) -> tuple[int, int]:
    return (segment - 1) * 100 // segments, segment * 100 // segments


def _segment_of(progress_ms: int, offset_ms: int, total_ms: int, segments: int) -> int:
    pos = offset_ms + max(0, progress_ms)
    if pos >= total_ms:
        return segments - 1
    return min(segments - 1, int(pos / total_ms * segments))


def locate(video, segments: int) -> list[dict]:
    parts = sorted(video.parts, key=lambda part: part.get("page") or 0)
    offset_by_page: dict = {}
    total = 0
    for part in parts:
        offset_by_page[part.get("page")] = total
        total += int(part.get("duration") or 0) * 1000
    if total <= 0:
        return []
    located = []
    for row in video.rows:
        progress = row.get("progress_ms")
        if progress is None:
            continue
        page = row.get("page")
        if page in offset_by_page:
            offset = offset_by_page[page]
        elif len(offset_by_page) == 1:
            offset = 0
        else:
            continue
        ctime = row.get("ctime")
        located.append(
            {
                "segment": _segment_of(int(progress), offset, total, segments),
                "progress_ms": int(progress),
                "ctime": int(ctime) if isinstance(ctime, int) else None,
                "raw": display_raw(str(row.get("content") or "")),
            }
        )
    return located


def _peak(counts: list[float]) -> int:
    """第一个严格更大的位置。并列时留在先出现的段。"""
    best = 0
    for index, value in enumerate(counts):
        if value > counts[best]:
            best = index
    return best


def _median(columns: list[list[int]]) -> list[float]:
    if not columns:
        return []
    width = len(columns[0])
    out = []
    for index in range(width):
        values = sorted(column[index] for column in columns)
        mid = len(values) // 2
        if len(values) % 2:
            out.append(float(values[mid]))
        else:
            out.append((values[mid - 1] + values[mid]) / 2)
    return out


def _new_agg(segments: int) -> dict:
    return {
        "rows": defaultdict(int),
        "videos": defaultdict(set),
        "segs": defaultdict(lambda: [0] * segments),
        "samples": defaultdict(list),
        "ctime_min": {},
        "ctime_max": {},
    }


def _touch(agg: dict, key: str, item: dict, bvid: str, segments: int, seen: set[str]) -> None:
    agg["rows"][key] += 1
    agg["segs"][key][item["segment"]] += 1
    if key not in seen:
        agg["videos"][key].add(bvid)
        seen.add(key)
    if len(agg["samples"][key]) < EVIDENCE_SAMPLE:
        start_pct, end_pct = _bounds(item["segment"] + 1, segments)
        agg["samples"][key].append(
            {
                "bvid": bvid,
                "segment": item["segment"] + 1,
                "start_pct": start_pct,
                "end_pct": end_pct,
                "progress_ms": item["progress_ms"],
                "ctime": item["ctime"],
                "text": item["raw"],
            }
        )
    if item["ctime"] is not None:
        agg["ctime_min"][key] = item["ctime"] if key not in agg["ctime_min"] else min(agg["ctime_min"][key], item["ctime"])
        agg["ctime_max"][key] = item["ctime"] if key not in agg["ctime_max"] else max(agg["ctime_max"][key], item["ctime"])


def _record(text: str, agg: dict, n_type: int, segments: int, unit: str) -> dict:
    counts = agg["segs"][text]
    nvideos = len(agg["videos"][text])
    nrows = agg["rows"][text]
    peak = _peak(counts)
    entry = next(index for index, value in enumerate(counts) if value > 0)
    exit_ = max(index for index, value in enumerate(counts) if value > 0)
    if text in agg["ctime_min"]:
        span_days = int((agg["ctime_max"][text] - agg["ctime_min"][text]) // 86400)
    else:
        span_days = None
    entry_segment = entry + 1
    peak_segment = peak + 1
    exit_segment = exit_ + 1
    entry_start_pct, _entry_end = _bounds(entry_segment, segments)
    peak_start_pct, peak_end_pct = _bounds(peak_segment, segments)
    _exit_start, exit_end_pct = _bounds(exit_segment, segments)
    return {
        "text": text,
        "unit": unit,
        "n_videos": nvideos,
        "n_rows": nrows,
        "entry_segment": entry_segment,
        "peak_segment": peak_segment,
        "exit_segment": exit_segment,
        "entry_start_pct": entry_start_pct,
        "peak_start_pct": peak_start_pct,
        "peak_end_pct": peak_end_pct,
        "exit_end_pct": exit_end_pct,
        "absent_videos": n_type - nvideos,
        "span_days": span_days,
        "segment_counts": counts,
        "evidence": agg["samples"][text],
        "neighbors": [],
        "neighbor_count": 0,
    }


def _finish(agg: dict, n_type: int, segments: int, min_videos: int, min_rows: int, unit: str) -> tuple[list[dict], list[dict]]:
    claims = []
    solos = []
    for text in agg["rows"]:
        nvideos = len(agg["videos"][text])
        nrows = agg["rows"][text]
        if nvideos >= min_videos and nrows >= min_rows:
            claims.append(_record(text, agg, n_type, segments, unit))
        elif nvideos == 1 and nrows >= min_rows:
            solos.append(_record(text, agg, n_type, segments, unit))
    claims.sort(key=lambda item: (-item["n_videos"], -item["n_rows"], item["text"]))
    solos.sort(key=lambda item: (-item["n_rows"], item["text"]))
    return claims, solos


def _attach_neighbors(claims: list[dict], tolerance: int, limit: int) -> None:
    for claim in claims:
        near = [
            other
            for other in claims
            if other["text"] != claim["text"] and abs(other["peak_segment"] - claim["peak_segment"]) <= tolerance
        ]
        near.sort(key=lambda item: (-item["n_videos"], -item["n_rows"], item["text"]))
        claim["neighbor_count"] = len(near)
        claim["neighbors"] = [
            {
                "text": other["text"],
                "n_videos": other["n_videos"],
                "n_rows": other["n_rows"],
                "peak_segment": other["peak_segment"],
                "peak_start_pct": other["peak_start_pct"],
                "peak_end_pct": other["peak_end_pct"],
            }
            for other in near[:limit]
        ]


def build_type(
    type_id: str,
    title: str,
    videos,
    segments: int = SEGMENTS,
    min_videos: int = MIN_VIDEOS,
    min_rows: int = MIN_ROWS,
    top_claims: int = TOP_CLAIMS,
    top_phrases: int = TOP_PHRASES,
    solo_items: int = SOLO_ITEMS,
    tolerance: int = PEAK_TOLERANCE,
) -> dict:
    per_video_counts: list[list[int]] = []
    per_video_bvid: list[str] = []
    words = _new_agg(segments)
    phrases = _new_agg(segments)
    usable = 0
    raw_rows = 0
    videos = sorted(videos, key=lambda video: video.bvid)
    for video in videos:
        raw_rows += len(video.rows)
        counts = [0] * segments
        seen_words: set[str] = set()
        seen_phrases: set[str] = set()
        for item in locate(video, segments):
            usable += 1
            counts[item["segment"]] += 1
            phrase, tokens = split_units(item["raw"])
            if phrase is not None:
                _touch(phrases, phrase, item, video.bvid, segments, seen_phrases)
            for token in tokens:
                _touch(words, token, item, video.bvid, segments, seen_words)
        per_video_counts.append(counts)
        per_video_bvid.append(video.bvid)
    median = _median(per_video_counts)
    volume_peak = _peak(median) if median else 0
    if median:
        top = max(median)
        tied = [index + 1 for index, value in enumerate(median) if value == top]
    else:
        tied = [1]
    baseline_peak = _peak(per_video_counts[0]) if per_video_counts else 0
    volume_peak_starts = []
    volume_peak_ends = []
    for segment in tied:
        start_pct, end_pct = _bounds(segment, segments)
        volume_peak_starts.append(start_pct)
        volume_peak_ends.append(end_pct)
    baseline_start_pct, baseline_end_pct = _bounds(baseline_peak + 1, segments)
    word_claims, solo_words = _finish(words, len(videos), segments, min_videos, min_rows, "word")
    phrase_claims, solo_phrases = _finish(phrases, len(videos), segments, min_videos, min_rows, "phrase")
    _attach_neighbors(word_claims, tolerance, NEIGHBOR_ITEMS)
    _attach_neighbors(phrase_claims, tolerance, NEIGHBOR_ITEMS)
    phases = build_phases(phrase_claims, segments)
    return {
        "id": type_id,
        "title": title,
        "n_videos": len(videos),
        "n_rows": raw_rows,
        "usable_rows": usable,
        "volume_median": median,
        "volume_peak_segment": volume_peak + 1,
        "volume_tied_segments": tied,
        "volume_peak_starts": volume_peak_starts,
        "volume_peak_ends": volume_peak_ends,
        "baseline_peak_segment": baseline_peak + 1,
        "baseline_start_pct": baseline_start_pct,
        "baseline_end_pct": baseline_end_pct,
        "volume_lines": [
            {"bvid": bvid, "counts": counts}
            for bvid, counts in zip(per_video_bvid, per_video_counts)
        ],
        "claims": word_claims,
        "shown_claims": word_claims[:top_claims],
        "phrases": phrase_claims,
        "shown_phrases": phrase_claims[:top_phrases],
        "solo_words": solo_words[:solo_items],
        "solo_word_count": len(solo_words),
        "solo_phrases": solo_phrases[:solo_items],
        "solo_phrase_count": len(solo_phrases),
        "phases": phases,
    }


def _leader_at(claims: list[dict], segment: int) -> dict | None:
    index = segment - 1
    best = None
    best_key = None
    for claim in claims:
        counts = claim["segment_counts"]
        if index < 0 or index >= len(counts):
            continue
        count = counts[index]
        if count <= 0:
            continue
        key = (count, claim["n_videos"], claim["text"])
        if best_key is None or key > best_key:
            best_key = key
            best = claim
    return best


def build_phases(claims: list[dict], segments: int) -> list[dict]:
    """沿片长看哪一句完整说法在这一截里最多。相邻且是同一句的并成一截。"""
    if not claims or segments <= 0:
        return []
    leaders = [_leader_at(claims, index + 1) for index in range(segments)]
    phases: list[dict] = []
    start = None
    current = None
    for index, leader in enumerate(leaders + [None]):
        if current is None:
            if leader is not None:
                start = index
                current = leader
            continue
        if leader is current:
            continue
        end = index - 1
        start_pct, _start_end = _bounds(start + 1, segments)
        _end_start, end_pct = _bounds(end + 1, segments)
        phases.append(
            {
                "text": current["text"],
                "unit": current.get("unit", "phrase"),
                "start_segment": start + 1,
                "end_segment": end + 1,
                "start_pct": start_pct,
                "end_pct": end_pct,
                "span_rows": sum(current["segment_counts"][start : end + 1]),
                "n_videos": current["n_videos"],
                "n_rows": current["n_rows"],
                "peak_segment": current["peak_segment"],
                "peak_start_pct": current["peak_start_pct"],
                "peak_end_pct": current["peak_end_pct"],
            }
        )
        if leader is None:
            current = None
            start = None
        else:
            current = leader
            start = index
    return phases


def _item(claim: dict, other: dict | None = None) -> dict:
    payload = {
        "text": claim["text"],
        "unit": claim.get("unit", ""),
        "n_videos": claim["n_videos"],
        "n_rows": claim["n_rows"],
        "entry_segment": claim["entry_segment"],
        "peak_segment": claim["peak_segment"],
        "exit_segment": claim["exit_segment"],
        "entry_start_pct": claim["entry_start_pct"],
        "peak_start_pct": claim["peak_start_pct"],
        "peak_end_pct": claim["peak_end_pct"],
        "exit_end_pct": claim["exit_end_pct"],
        "peak_where": claim.get("peak_where", ""),
        "span_where": claim.get("span_where", ""),
        "reading": claim.get("reading", ""),
        "summary": claim.get("summary", ""),
        "absent_videos": claim["absent_videos"],
        "span_days": claim["span_days"],
        "segment_counts": claim["segment_counts"],
        "evidence": claim["evidence"],
        "neighbors": claim.get("neighbors", []),
        "neighbor_count": claim.get("neighbor_count", 0),
    }
    if other is not None:
        payload["other_peak_segment"] = other["peak_segment"]
        payload["other_peak_start_pct"] = other["peak_start_pct"]
        payload["other_peak_end_pct"] = other["peak_end_pct"]
        payload["other_peak_where"] = other.get("peak_where", "")
        payload["other_n_videos"] = other["n_videos"]
        payload["other_n_rows"] = other["n_rows"]
    return payload


def compare_types(left: dict, right: dict, tolerance: int = PEAK_TOLERANCE, limit: int = DIFF_ITEMS) -> dict:
    by_right = {claim["text"]: claim for claim in right["claims"]}
    same, shifted, only_left = [], [], []
    seen = set()
    for claim in left["claims"]:
        seen.add(claim["text"])
        other = by_right.get(claim["text"])
        if other is None:
            only_left.append(_item(claim))
            continue
        if abs(claim["peak_segment"] - other["peak_segment"]) <= tolerance:
            same.append(_item(claim, other))
        else:
            shifted.append(_item(claim, other))
    only_right = [_item(claim) for claim in right["claims"] if claim["text"] not in seen]
    buckets = {
        "same_peak": same,
        "shifted": shifted,
        "only_a": only_left,
        "only_b": only_right,
    }
    out = {}
    for key, items in buckets.items():
        items.sort(key=lambda item: (-item["n_videos"], -item["n_rows"], item["text"]))
        out[key] = {"count": len(items), "items": items[:limit]}
    return out


def label_buckets(left_claims: list[dict], right_claims: list[dict], tolerance: int) -> tuple[dict[str, str], dict[str, str]]:
    """每一条跨视频说法落入四栏中的一栏。显示时再截断，计数不截断。"""
    by_right = {claim["text"]: claim for claim in right_claims}
    left: dict[str, str] = {}
    right: dict[str, str] = {}
    seen: set[str] = set()
    for claim in left_claims:
        seen.add(claim["text"])
        other = by_right.get(claim["text"])
        if other is None:
            left[claim["text"]] = "only_a"
            continue
        key = "same_peak" if abs(claim["peak_segment"] - other["peak_segment"]) <= tolerance else "shifted"
        left[claim["text"]] = key
        right[claim["text"]] = key
    for claim in right_claims:
        if claim["text"] not in seen:
            right[claim["text"]] = "only_b"
    return left, right
