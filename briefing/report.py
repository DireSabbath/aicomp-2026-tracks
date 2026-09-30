"""把两个类型收成一份可打开的演示。"""

from __future__ import annotations

import json
from pathlib import Path

from briefing.protocol import (
    DIFF_ITEMS,
    MIN_ROWS,
    MIN_VIDEOS,
    PEAK_TOLERANCE,
    PHRASE_MAX,
    PHRASE_MIN,
    SEGMENTS,
    WORD_MAX,
    WORD_MIN,
)
from briefing.structure import build_type, compare_types
from briefing.text import CLAIM_RULE, PURPOSE, SIGNOFF, briefing_from_table, decorate, table_rows
from briefing.web import render_page


def protocol_dict(segments: int, tolerance: int, min_videos: int, min_rows: int) -> dict:
    return {
        "segments": segments,
        "peak_tolerance": tolerance,
        "peak_tolerance_pct": tolerance * 100 // segments,
        "min_videos": min_videos,
        "min_rows": min_rows,
        "word_min_chars": WORD_MIN,
        "word_max_chars": WORD_MAX,
        "phrase_min_chars": PHRASE_MIN,
        "phrase_max_chars": PHRASE_MAX,
        "purpose": PURPOSE,
        "claim_rule": CLAIM_RULE,
        "signoff": SIGNOFF,
    }


def _public_type(item: dict) -> dict:
    return {
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
        "words": item["shown_claims"],
        "phrases": item["shown_phrases"],
        "solo_words": item["solo_words"],
        "solo_word_count": item["solo_word_count"],
        "solo_phrases": item["solo_phrases"],
        "solo_phrase_count": item["solo_phrase_count"],
        "phases": item.get("phases") or [],
        "crowd_readings": item.get("crowd_readings") or [],
        "arc_reading": item.get("arc_reading") or "",
    }


def _page_view(report: dict) -> dict:
    def cut(diff: dict) -> dict:
        return {
            key: {"count": bucket["count"], "items": bucket["items"][:DIFF_ITEMS]}
            for key, bucket in diff.items()
        }

    return {
        "protocol": report["protocol"],
        "types": report["types"],
        "diff": cut(report["diff"]),
        "phrase_diff": cut(report["phrase_diff"]),
        "briefing": report["briefing"],
    }


def build_report(
    types: list[tuple[str, str, list]],
    segments: int = SEGMENTS,
    tolerance: int = PEAK_TOLERANCE,
    min_videos: int = MIN_VIDEOS,
    min_rows: int = MIN_ROWS,
) -> dict:
    built = [
        build_type(
            type_id,
            title,
            videos,
            segments=segments,
            min_videos=min_videos,
            min_rows=min_rows,
            tolerance=tolerance,
        )
        for type_id, title, videos in types
    ]
    if len(built) != 2:
        raise ValueError("演示需要两个类型")
    decorate(built)
    word_diff = compare_types(
        {"claims": built[0]["claims"]},
        {"claims": built[1]["claims"]},
        tolerance,
    )
    phrase_diff = compare_types(
        {"claims": built[0]["phrases"]},
        {"claims": built[1]["phrases"]},
        tolerance,
    )
    protocol = protocol_dict(segments, tolerance, min_videos, min_rows)
    rows = table_rows(built, word_diff, phrase_diff, protocol, tolerance)
    return {
        "protocol": protocol,
        "types": [_public_type(item) for item in built],
        "diff": word_diff,
        "phrase_diff": phrase_diff,
        "table": rows,
        "briefing": briefing_from_table(rows),
    }


def write_demo(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "index.html").write_text(render_page(_page_view(report)), encoding="utf-8")
