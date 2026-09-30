"""简报只从结构表填空。句子说的是片子的进度，不是内部段号。"""

from __future__ import annotations

from briefing.protocol import BRIEFING_CLAIMS_PER_TYPE

PURPOSE = "给研究某一类视频的人看：观众在片子的什么位置说话，哪些句子被原样重复。只描述弹幕，不评价，也不给建议。"
SIGNOFF = "这些视频算不算同一类，还没有人签字。句子按原文逐字相同来数，意思相近但写法不同的，还没有合并。"


def place(start: int, end: int) -> str:
    if start == 0 and end == 100:
        return "整段片子"
    if start == 0:
        return f"开头的{end}%"
    if end == 100:
        return f"片长的{start}%到片尾"
    return f"片长的{start}%到{end}%"


def stretch(entry_start: int, exit_end: int) -> str:
    if entry_start == 0 and exit_end == 100:
        return "从开头一直到片尾"
    if entry_start == 0:
        return f"从开头到片长的{exit_end}%"
    if exit_end == 100:
        return f"从片长的{entry_start}%一直到片尾"
    return f"从片长的{entry_start}%到{exit_end}%"


def decorate(types: list[dict]) -> None:
    for item in types:
        for claim in item["claims"]:
            claim["peak_where"] = place(claim["peak_start_pct"], claim["peak_end_pct"])
            claim["span_where"] = stretch(claim["entry_start_pct"], claim["exit_end_pct"])
            claim["reading"] = (
                f"「{claim['text']}」在{item['n_videos']}条视频里，有{claim['n_videos']}条出现过，一共{claim['n_rows']}次。"
                f"{claim['span_where']}都能看到这句，最密在{claim['peak_where']}。"
            )
            claim["summary"] = (
                f"{claim['n_videos']} 条里出现过 · {claim['n_rows']} 次 · 最密在{claim['peak_where']}"
            )
            for sample in claim["evidence"]:
                sample["where"] = place(sample["start_pct"], sample["end_pct"])
        places = "，以及".join(
            place(start, end)
            for start, end in zip(item["volume_peak_starts"], item["volume_peak_ends"])
        )
        item["volume_reading"] = (
            f"{item['title']}共有{item['n_videos']}条视频、{item['n_rows']}条弹幕。弹幕最密的地方在{places}。"
        )
        where = place(item["baseline_start_pct"], item["baseline_end_pct"])
        if item["baseline_peak_segment"] in item["volume_tied_segments"]:
            item["baseline_reading"] = f"只看清单里按视频号排在最前的一条，最密的地方也在{where}。"
        else:
            item["baseline_reading"] = (
                f"只看清单里按视频号排在最前的一条，最密的地方在{where}，和这一类不是同一个位置。"
            )


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
                "volume_peak_starts": item["volume_peak_starts"],
                "volume_peak_ends": item["volume_peak_ends"],
                "baseline_peak_segment": item["baseline_peak_segment"],
                "baseline_start_pct": item["baseline_start_pct"],
                "baseline_end_pct": item["baseline_end_pct"],
                "volume_reading": item["volume_reading"],
                "baseline_reading": item["baseline_reading"],
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
                    "entry_start_pct": claim["entry_start_pct"],
                    "peak_start_pct": claim["peak_start_pct"],
                    "peak_end_pct": claim["peak_end_pct"],
                    "exit_end_pct": claim["exit_end_pct"],
                    "absent_videos": claim["absent_videos"],
                    "span_days": claim["span_days"] if claim["span_days"] is not None else -1,
                    "reading": claim["reading"],
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
                "peak_start_pct": item["peak_start_pct"],
                "peak_end_pct": item["peak_end_pct"],
            }
            if "other_peak_segment" in item:
                row["other_peak_segment"] = item["other_peak_segment"]
                row["other_peak_start_pct"] = item["other_peak_start_pct"]
                row["other_peak_end_pct"] = item["other_peak_end_pct"]
                row["other_n_videos"] = item["other_n_videos"]
                row["other_n_rows"] = item["other_n_rows"]
            rows.append(row)
    return rows


def briefing_from_table(rows: list[dict]) -> list[str]:
    sentences = [PURPOSE, SIGNOFF]
    types = [row for row in rows if row["kind"] == "type"]
    titles = [item["title"] for item in types]
    for item in types:
        sentences.append(item["volume_reading"])
        sentences.append(item["baseline_reading"])
        claims = [row for row in rows if row["kind"] == "claim" and row["type_id"] == item["type_id"]]
        for claim in claims[:BRIEFING_CLAIMS_PER_TYPE]:
            sentences.append(claim["reading"])
    if len(titles) >= 2:
        sentences.append(f"对照的是{titles[0]}和{titles[1]}。")
        labels = {
            "same_peak": "两边都有，而且最密的地方差不多",
            "shifted": "两边都有，但最密的地方错开了",
            "only_a": f"只在{titles[0]}里反复出现",
            "only_b": f"只在{titles[1]}里反复出现",
        }
    else:
        labels = {}
    for key, label in labels.items():
        bucket = next(row for row in rows if row["kind"] == "diff" and row["diff"] == key)
        examples = [row for row in rows if row["kind"] == "diff_item" and row["diff"] == key]
        if examples:
            sentences.append(f"{label}的句子有{bucket['count']}句，例如「{examples[0]['text']}」。")
        else:
            sentences.append(f"{label}的句子有{bucket['count']}句。")
    return sentences
