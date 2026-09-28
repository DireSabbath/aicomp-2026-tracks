#!/usr/bin/env python3
"""统计公开池的时间结构。只打印计数和分位数，不打印弹幕正文。"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import zipfile
from pathlib import Path

WEEK = 7 * 86400
BIN_MS = 60_000


def percentile(values: list[float], p: float):
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((p / 100) * (len(ordered) - 1)))
    index = min(len(ordered) - 1, max(0, index))
    return ordered[index]


def densest_week(times: list[int]) -> tuple[int, int]:
    """返回最密 7 天的条数，以及该窗口起点。并列时取更早的起点。"""
    ordered = sorted(times)
    start = 0
    best_count = 1
    best_origin = ordered[0]
    for end, stamp in enumerate(ordered):
        while stamp - ordered[start] > WEEK:
            start += 1
        count = end - start + 1
        if count > best_count:
            best_count = count
            best_origin = ordered[start]
    return best_count, best_origin


def summarize_video(rows: list[dict]) -> dict:
    lengths = []
    pages = set()
    modes: dict[str, int] = {}
    usable = []
    stats = {
        "rows": len(rows),
        "empty": 0,
        "no_progress": 0,
        "no_ctime": 0,
        "dup_id": 0,
        "ctime_s": 0,
        "ctime_ms": 0,
        "ctime_other": 0,
        "ctime_min": None,
        "ctime_max": None,
    }
    seen = set()
    for row in rows:
        if row.get("id") is not None:
            if row["id"] in seen:
                stats["dup_id"] += 1
            seen.add(row["id"])
        content = row.get("content") or ""
        if content == "":
            stats["empty"] += 1
        else:
            lengths.append(len(content))
        mode = row.get("mode")
        key = str(mode)
        modes[key] = modes.get(key, 0) + 1
        if row.get("page") is not None:
            pages.add(row["page"])
        progress = row.get("progress_ms")
        ctime = row.get("ctime")
        if progress is None:
            stats["no_progress"] += 1
        if ctime is None:
            stats["no_ctime"] += 1
        elif ctime > 10**12:
            stats["ctime_ms"] += 1
        elif ctime > 10**9:
            stats["ctime_s"] += 1
        else:
            stats["ctime_other"] += 1
        if progress is not None and ctime is not None:
            seconds = ctime / 1000 if ctime > 10**12 else ctime
            usable.append((progress, seconds))
            if stats["ctime_min"] is None or seconds < stats["ctime_min"]:
                stats["ctime_min"] = seconds
            if stats["ctime_max"] is None or seconds > stats["ctime_max"]:
                stats["ctime_max"] = seconds

    video = {
        "rows": stats["rows"],
        "empty": stats["empty"],
        "no_progress": stats["no_progress"],
        "no_ctime": stats["no_ctime"],
        "dup_id": stats["dup_id"],
        "ctime_s": stats["ctime_s"],
        "ctime_ms": stats["ctime_ms"],
        "ctime_other": stats["ctime_other"],
        "ctime_min": stats["ctime_min"],
        "ctime_max": stats["ctime_max"],
        "lengths": lengths,
        "modes": modes,
        "pages": len(pages),
        "usable": len(usable),
    }
    if len(usable) < 30:
        video["skipped"] = True
        return video

    times = [stamp for _, stamp in usable]
    week_count, origin = densest_week(times)
    first = min(times)
    premiere_hi = origin + WEEK
    in_premiere = 0
    usable.sort()
    inv_all = adj_all = inv_pre = adj_pre = gap7 = 0
    previous = None
    previous_premiere = None
    bins: dict[int, list[float]] = {}
    for progress, stamp in usable:
        if previous is not None:
            adj_all += 1
            if stamp < previous:
                inv_all += 1
            if abs(stamp - previous) > WEEK:
                gap7 += 1
        previous = stamp
        inside = origin <= stamp <= premiere_hi
        if inside:
            in_premiere += 1
            if previous_premiere is not None:
                adj_pre += 1
                if stamp < previous_premiere:
                    inv_pre += 1
            previous_premiere = stamp
        else:
            previous_premiere = None
        bins.setdefault(progress // BIN_MS, []).append(stamp)

    bin_spans = []
    bin_week_shares = []
    bin_premiere_shares = []
    for stamps in bins.values():
        if len(stamps) < 15:
            continue
        bin_spans.append((max(stamps) - min(stamps)) / 86400)
        count, _ = densest_week(stamps)
        bin_week_shares.append(count / len(stamps))
        hit = sum(1 for stamp in stamps if origin <= stamp <= premiere_hi)
        bin_premiere_shares.append(hit / len(stamps))

    video.update(
        {
            "skipped": False,
            "premiere_n": in_premiere,
            "premiere_share": in_premiere / len(usable),
            "week_offset_days": (origin - first) / 86400,
            "span_days": (max(times) - first) / 86400,
            "inv_all": inv_all,
            "adj_all": adj_all,
            "inv_pre": inv_pre,
            "adj_pre": adj_pre,
            "gap7": gap7,
            "bin_spans": bin_spans,
            "bin_week_shares": bin_week_shares,
            "bin_premiere_shares": bin_premiere_shares,
        }
    )
    return video


def merge(videos: list[dict]) -> dict:
    merged = {
        "videos": len(videos),
        "rows": 0,
        "empty": 0,
        "no_progress": 0,
        "no_ctime": 0,
        "dup_id": 0,
        "ctime_s": 0,
        "ctime_ms": 0,
        "ctime_other": 0,
        "ctime_min": None,
        "ctime_max": None,
        "pages_gt1": 0,
        "analyzed_videos": 0,
    }
    lengths = []
    modes: dict[str, int] = {}
    premiere_rows = usable_rows = 0
    offsets = []
    spans = []
    inv_all = adj_all = inv_pre = adj_pre = gap7 = 0
    bin_spans = []
    bin_week = []
    bin_premiere = []
    same_majority = 0
    for video in videos:
        for key in (
            "rows",
            "empty",
            "no_progress",
            "no_ctime",
            "dup_id",
            "ctime_s",
            "ctime_ms",
            "ctime_other",
        ):
            merged[key] += video[key]
        if video["ctime_min"] is not None:
            if merged["ctime_min"] is None or video["ctime_min"] < merged["ctime_min"]:
                merged["ctime_min"] = video["ctime_min"]
            if merged["ctime_max"] is None or video["ctime_max"] > merged["ctime_max"]:
                merged["ctime_max"] = video["ctime_max"]
        if video["pages"] > 1:
            merged["pages_gt1"] += 1
        lengths.extend(video["lengths"])
        for mode, count in video["modes"].items():
            modes[mode] = modes.get(mode, 0) + count
        if video.get("skipped", True):
            continue
        merged["analyzed_videos"] += 1
        usable_rows += video["usable"]
        premiere_rows += video["premiere_n"]
        offsets.append(video["week_offset_days"])
        spans.append(video["span_days"])
        inv_all += video["inv_all"]
        adj_all += video["adj_all"]
        inv_pre += video["inv_pre"]
        adj_pre += video["adj_pre"]
        gap7 += video["gap7"]
        bin_spans.extend(video["bin_spans"])
        bin_week.extend(video["bin_week_shares"])
        bin_premiere.extend(video["bin_premiere_shares"])
        same_majority += sum(
            1
            for left, right in zip(video["bin_week_shares"], video["bin_premiere_shares"])
            if abs(left - right) < 1e-9
        )

    def rate(num, den):
        return None if den == 0 else num / den

    merged.update(
        {
            "modes": modes,
            "len_p50": percentile(lengths, 50),
            "len_p90": percentile(lengths, 90),
            "len_p99": percentile(lengths, 99),
            "usable_rows": usable_rows,
            "premiere_row_share": rate(premiere_rows, usable_rows),
            "week_offset_p50": percentile(offsets, 50),
            "offset_lt_14": rate(sum(1 for item in offsets if item < 14), len(offsets)),
            "span_days_p50": percentile(spans, 50),
            "inv_all": rate(inv_all, adj_all),
            "inv_premiere": rate(inv_pre, adj_pre),
            "adj_gap7": rate(gap7, adj_all),
            "bins": len(bin_spans),
            "bin_span_p50": percentile(bin_spans, 50),
            "bin_span_p90": percentile(bin_spans, 90),
            "bin_span_gt7": rate(sum(1 for item in bin_spans if item > 7), len(bin_spans)),
            "bin_span_gt30": rate(sum(1 for item in bin_spans if item > 30), len(bin_spans)),
            "bin_week_p50": percentile(bin_week, 50),
            "bin_premiere_p50": percentile(bin_premiere, 50),
            "bin_majority_is_premiere": rate(same_majority, len(bin_spans)),
        }
    )
    return merged


def iter_jsonl_gz(path: Path):
    opener = gzip.open
    with opener(path, "rt", encoding="utf-8") as handle:
        rows = []
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
        yield path.stem, rows


def iter_zip(path: Path):
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".jsonl.gz"):
                continue
            raw = gzip.decompress(archive.read(name))
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            yield Path(name).name.replace(".jsonl.gz", ""), rows


def collect(paths: list[Path]) -> dict:
    groups: dict[str, list[dict]] = {}
    for path in paths:
        if path.suffix == ".zip":
            key = path.stem
            groups[key] = [summarize_video(rows) for _, rows in iter_zip(path)]
        elif path.name.endswith(".jsonl.gz"):
            groups.setdefault("jsonl", [])
            for _, rows in iter_jsonl_gz(path):
                groups["jsonl"].append(summarize_video(rows))
        else:
            raise SystemExit(f"不认识的输入：{path.name}")
    return {key: merge(videos) for key, videos in groups.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="统计弹幕池的时间结构，不输出正文")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    report = collect(args.paths)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
