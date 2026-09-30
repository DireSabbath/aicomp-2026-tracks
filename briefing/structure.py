"""从已定位的弹幕算出接收结构。说法按原文完全相同计数。"""

from __future__ import annotations

import re
from collections import defaultdict

from briefing.ethics import blocked
from briefing.protocol import (
    DIFF_ITEMS,
    EVIDENCE_SAMPLE,
    MAX_CHARS,
    MIN_CHARS,
    MIN_ROWS,
    MIN_VIDEOS,
    PEAK_TOLERANCE,
    SEGMENTS,
    TOP_CLAIMS,
)

_KEEP = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


def normalize(content: str) -> str | None:
    text = re.sub(r"\s+", "", content or "")
    if not (MIN_CHARS <= len(text) <= MAX_CHARS):
        return None
    if _KEEP.search(text) is None:
        return None
    if blocked(text):
        return None
    return text


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
                "text": normalize(str(row.get("content") or "")),
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


def build_type(
    type_id: str,
    title: str,
    videos,
    segments: int = SEGMENTS,
    min_videos: int = MIN_VIDEOS,
    min_rows: int = MIN_ROWS,
    top_claims: int = TOP_CLAIMS,
) -> dict:
    per_video_counts: list[list[int]] = []
    per_video_bvid: list[str] = []
    row_counts: dict[str, int] = defaultdict(int)
    video_hits: dict[str, set[str]] = defaultdict(set)
    segment_counts: dict[str, list[int]] = defaultdict(lambda: [0] * segments)
    samples: dict[str, list[dict]] = defaultdict(list)
    ctime_min: dict[str, int] = {}
    ctime_max: dict[str, int] = {}
    usable = 0
    raw_rows = 0
    videos = sorted(videos, key=lambda video: video.bvid)
    for video in videos:
        raw_rows += len(video.rows)
        counts = [0] * segments
        seen: set[str] = set()
        for item in locate(video, segments):
            usable += 1
            counts[item["segment"]] += 1
            text = item["text"]
            if text is None:
                continue
            row_counts[text] += 1
            segment_counts[text][item["segment"]] += 1
            if text not in seen:
                video_hits[text].add(video.bvid)
                seen.add(text)
            if len(samples[text]) < EVIDENCE_SAMPLE:
                samples[text].append(
                    {
                        "bvid": video.bvid,
                        "segment": item["segment"] + 1,
                        "progress_ms": item["progress_ms"],
                        "ctime": item["ctime"],
                        "text": text,
                    }
                )
            if item["ctime"] is not None:
                ctime_min[text] = item["ctime"] if text not in ctime_min else min(ctime_min[text], item["ctime"])
                ctime_max[text] = item["ctime"] if text not in ctime_max else max(ctime_max[text], item["ctime"])
        per_video_counts.append(counts)
        per_video_bvid.append(video.bvid)
    median = _median(per_video_counts)
    volume_peak = _peak(median) if median else 0
    if median:
        top = max(median)
        tied = [index + 1 for index, value in enumerate(median) if value == top]
    else:
        tied = [1]
    baseline_index = 0
    baseline_peak = _peak(per_video_counts[0]) if per_video_counts else 0
    claims = []
    for text, nrows in row_counts.items():
        nvideos = len(video_hits[text])
        if nvideos < min_videos or nrows < min_rows:
            continue
        counts = segment_counts[text]
        peak = _peak(counts)
        entry = next(index for index, value in enumerate(counts) if value > 0)
        exit_ = max(index for index, value in enumerate(counts) if value > 0)
        if text in ctime_min:
            span_days = int((ctime_max[text] - ctime_min[text]) // 86400)
        else:
            span_days = None
        claims.append(
            {
                "text": text,
                "n_videos": nvideos,
                "n_rows": nrows,
                "entry_segment": entry + 1,
                "peak_segment": peak + 1,
                "exit_segment": exit_ + 1,
                "absent_videos": len(videos) - nvideos,
                "span_days": span_days,
                "segment_counts": counts,
                "evidence": samples[text],
            }
        )
    claims.sort(key=lambda item: (-item["n_rows"], -item["n_videos"], item["text"]))
    return {
        "id": type_id,
        "title": title,
        "n_videos": len(videos),
        "n_rows": raw_rows,
        "usable_rows": usable,
        "volume_median": median,
        "volume_peak_segment": volume_peak + 1,
        "volume_tied_segments": tied,
        "baseline_peak_segment": baseline_peak + 1,
        "volume_lines": [
            {"bvid": bvid, "counts": counts}
            for bvid, counts in zip(per_video_bvid, per_video_counts)
        ],
        "claims": claims,
        "shown_claims": claims[:top_claims],
    }


def _item(claim: dict, other: dict | None = None) -> dict:
    payload = {
        "text": claim["text"],
        "n_videos": claim["n_videos"],
        "n_rows": claim["n_rows"],
        "entry_segment": claim["entry_segment"],
        "peak_segment": claim["peak_segment"],
        "exit_segment": claim["exit_segment"],
        "absent_videos": claim["absent_videos"],
        "span_days": claim["span_days"],
        "segment_counts": claim["segment_counts"],
        "evidence": claim["evidence"],
    }
    if other is not None:
        payload["other_peak_segment"] = other["peak_segment"]
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
        items.sort(key=lambda item: (-item["n_rows"], item["text"]))
        out[key] = {"count": len(items), "items": items[:limit]}
    return out
