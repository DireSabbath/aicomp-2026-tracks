"""把两个类型收成一份可打开的演示。"""

from __future__ import annotations

import json
from pathlib import Path

from briefing.protocol import (
    MIN_ROWS,
    MIN_VIDEOS,
    PEAK_TOLERANCE,
    SEGMENTS,
)
from briefing.structure import build_type, compare_types
from briefing.text import PURPOSE, briefing_from_table, decorate, table_rows
from briefing.web import render_page


def protocol_dict(segments: int, tolerance: int, min_videos: int, min_rows: int) -> dict:
    return {
        "segments": segments,
        "peak_tolerance": tolerance,
        "min_videos": min_videos,
        "min_rows": min_rows,
        "purpose": PURPOSE,
        "claim_rule": "句子按原文逐字相同来数，意思相近但写法不同的，还没有合并。",
        "signoff": "这些视频算不算同一类，还没有人签字。",
    }


def build_report(
    types: list[tuple[str, str, list]],
    segments: int = SEGMENTS,
    tolerance: int = PEAK_TOLERANCE,
    min_videos: int = MIN_VIDEOS,
    min_rows: int = MIN_ROWS,
) -> dict:
    built = [
        build_type(type_id, title, videos, segments, min_videos, min_rows)
        for type_id, title, videos in types
    ]
    if len(built) != 2:
        raise ValueError("演示需要两个类型")
    decorate(built)
    diff = compare_types(built[0], built[1], tolerance)
    protocol = protocol_dict(segments, tolerance, min_videos, min_rows)
    rows = table_rows(built, diff, protocol)
    public_types = []
    for item in built:
        public_types.append(
            {
                "id": item["id"],
                "title": item["title"],
                "n_videos": item["n_videos"],
                "n_rows": item["n_rows"],
                "usable_rows": item["usable_rows"],
                "volume_median": item["volume_median"],
                "volume_peak_segment": item["volume_peak_segment"],
                "volume_tied_segments": item["volume_tied_segments"],
                "volume_reading": item["volume_reading"],
                "baseline_reading": item["baseline_reading"],
                "baseline_peak_segment": item["baseline_peak_segment"],
                "volume_lines": item["volume_lines"],
                "claims": item["shown_claims"],
            }
        )
    return {
        "protocol": protocol,
        "types": public_types,
        "diff": diff,
        "table": rows,
        "briefing": briefing_from_table(rows),
    }


def write_demo(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "index.html").write_text(render_page(report), encoding="utf-8")
