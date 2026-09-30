"""简报只从结构表填空。表里没有的数不会出现在句子里。"""

from __future__ import annotations

from briefing.protocol import BRIEFING_CLAIMS_PER_TYPE

_DIFF_LABELS = {
    "same_peak": "共享且高峰段相同",
    "shifted": "共享但高峰段错开",
    "only_a": "只在前一个类型达到门槛",
    "only_b": "只在后一个类型达到门槛",
}


def table_rows(types: list[dict], diff: dict, protocol: dict) -> list[dict]:
    rows: list[dict] = [
        {
            "kind": "protocol",
            "segments": protocol["segments"],
            "peak_tolerance": protocol["peak_tolerance"],
            "min_videos": protocol["min_videos"],
            "min_rows": protocol["min_rows"],
        }
    ]
    for item in types:
        rows.append(
            {
                "kind": "type",
                "type_id": item["id"],
                "title": item["title"],
                "n_videos": item["n_videos"],
                "n_rows": item["n_rows"],
                "usable_rows": item["usable_rows"],
                "volume_peak_segment": item["volume_peak_segment"],
                "volume_tied_segments": item["volume_tied_segments"],
                "baseline_peak_segment": item["baseline_peak_segment"],
            }
        )
        for claim in item["shown_claims"]:
            rows.append(
                {
                    "kind": "claim",
                    "type_id": item["id"],
                    "text": claim["text"],
                    "n_videos": claim["n_videos"],
                    "n_rows": claim["n_rows"],
                    "entry_segment": claim["entry_segment"],
                    "peak_segment": claim["peak_segment"],
                    "exit_segment": claim["exit_segment"],
                    "absent_videos": claim["absent_videos"],
                    "span_days": claim["span_days"] if claim["span_days"] is not None else -1,
                }
            )
    for key in ("same_peak", "shifted", "only_a", "only_b"):
        bucket = diff[key]
        rows.append({"kind": "diff", "diff": key, "count": bucket["count"]})
        for item in bucket["items"]:
            row = {
                "kind": "diff_item",
                "diff": key,
                "text": item["text"],
                "n_videos": item["n_videos"],
                "n_rows": item["n_rows"],
                "peak_segment": item["peak_segment"],
            }
            if "other_peak_segment" in item:
                row["other_peak_segment"] = item["other_peak_segment"]
                row["other_n_videos"] = item["other_n_videos"]
                row["other_n_rows"] = item["other_n_rows"]
            rows.append(row)
    return rows


def briefing_from_table(rows: list[dict]) -> list[str]:
    sentences = [
        "这些说法按去掉空白后的原文完全相同入选，人工抽查还没有做。",
        "类型归属尚未由人签字，下面是演示材料上的接收结构。",
    ]
    types = [row for row in rows if row["kind"] == "type"]
    for item in types:
        tied = item["volume_tied_segments"]
        if len(tied) > 1:
            listed = "、".join(f"第{number}段" for number in tied)
            sentences.append(
                f"{item['title']}有{item['n_videos']}条视频、{item['n_rows']}条弹幕，中位数最高的是{listed}，高峰记在第{item['volume_peak_segment']}段。"
            )
        else:
            sentences.append(
                f"{item['title']}有{item['n_videos']}条视频、{item['n_rows']}条弹幕，数量高峰在第{item['volume_peak_segment']}段。"
            )
        sentences.append(
            f"{item['title']}里清单第一条视频的数量高峰在第{item['baseline_peak_segment']}段。"
        )
        claims = [row for row in rows if row["kind"] == "claim" and row["type_id"] == item["type_id"]]
        for claim in claims[:BRIEFING_CLAIMS_PER_TYPE]:
            sentences.append(
                f"说法「{claim['text']}」覆盖{claim['n_videos']}条视频、{claim['n_rows']}条弹幕，"
                f"进入第{claim['entry_segment']}段，高峰在第{claim['peak_segment']}段，"
                f"退出第{claim['exit_segment']}段，缺席{claim['absent_videos']}条视频。"
            )
    titles = [item["title"] for item in types]
    if len(titles) >= 2:
        sentences.append(f"对照的两个类型是{titles[0]}和{titles[1]}。")
    for key, label in _DIFF_LABELS.items():
        bucket = next(row for row in rows if row["kind"] == "diff" and row["diff"] == key)
        examples = [row for row in rows if row["kind"] == "diff_item" and row["diff"] == key]
        if examples:
            sentences.append(f"{label}的说法有{bucket['count']}条，例如「{examples[0]['text']}」。")
        else:
            sentences.append(f"{label}的说法有{bucket['count']}条。")
    return sentences
