"""简报只从结构表填空。句子说的是片子的进度，不是内部段号。"""

from __future__ import annotations

from briefing.protocol import BRIEFING_CLAIMS_PER_TYPE, DIFF_ITEMS
from briefing.structure import label_buckets

PURPOSE = "给文化研究者和政策制定者看某一类视频的观众弹幕：哪些词和短句在片子的什么位置出现，哪些视频里没有。只描述弹幕，不评价，也不给建议。"
SIGNOFF = "这些视频算不算同一类，还没有人签字。"
CLAIM_RULE = "词按分词归并，完整说法按去掉标点后的整条弹幕归并。同一个字连写的不单独成说法。同义不同词没有合并。只在一条视频里出现的单独列出，不写入类型结论。"


def place(start: int, end: int) -> str:
    if start == 0 and end == 100:
        return "整条片子"
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


def _decorate_claim(claim: dict, n_videos: int) -> None:
    claim["peak_where"] = place(claim["peak_start_pct"], claim["peak_end_pct"])
    claim["span_where"] = stretch(claim["entry_start_pct"], claim["exit_end_pct"])
    name = "这个词" if claim.get("unit") == "word" else "这句"
    if claim["absent_videos"]:
        gap = f"，另外{claim['absent_videos']}条里没有"
    else:
        gap = "，这一类的每条视频里都有"
    claim["reading"] = (
        f"「{claim['text']}」在{n_videos}条视频里，有{claim['n_videos']}条出现过，一共{claim['n_rows']}次{gap}。"
        f"{claim['span_where']}都能看到{name}，最密在{claim['peak_where']}。"
    )
    claim["summary"] = (
        f"{claim['n_videos']} 条里出现过 · {claim['n_rows']} 次 · 另外 {claim['absent_videos']} 条没有 · 最密在{claim['peak_where']}"
    )
    for sample in claim["evidence"]:
        sample["where"] = place(sample["start_pct"], sample["end_pct"])
    for neighbor in claim.get("neighbors") or []:
        neighbor["peak_where"] = place(neighbor["peak_start_pct"], neighbor["peak_end_pct"])


def decorate(types: list[dict]) -> None:
    for item in types:
        for claim in item["claims"] + item["phrases"] + item["solo_words"] + item["solo_phrases"]:
            _decorate_claim(claim, item["n_videos"])
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


def _claim_row(item: dict, claim: dict, bucket: str, titles: list[str]) -> dict:
    labels = {
        "same_peak": "两边都有，最密的地方差不多",
        "shifted": "两边都有，最密的地方错开了",
        "only_a": f"只在{titles[0]}" if titles else "",
        "only_b": f"只在{titles[1]}" if len(titles) > 1 else "",
    }
    return {
        "kind": "claim",
        "layer": claim.get("unit", ""),
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
        "neighbor_count": claim.get("neighbor_count", 0),
        "diff_bucket": bucket,
        "diff_label": labels.get(bucket, ""),
        "reading": claim["reading"],
        "evidence_text": [sample["text"] for sample in claim["evidence"][:3]],
    }


def _diff_item_row(item: dict, key: str, layer: str) -> dict:
    row = {
        "kind": "diff_item",
        "layer": layer,
        "diff": key,
        "text": item["text"],
        "n_videos": item["n_videos"],
        "n_rows": item["n_rows"],
        "peak_segment": item["peak_segment"],
        "peak_start_pct": item["peak_start_pct"],
        "peak_end_pct": item["peak_end_pct"],
        "absent_videos": item["absent_videos"],
    }
    if "other_peak_segment" in item:
        row["other_peak_segment"] = item["other_peak_segment"]
        row["other_peak_start_pct"] = item["other_peak_start_pct"]
        row["other_peak_end_pct"] = item["other_peak_end_pct"]
        row["other_n_videos"] = item["other_n_videos"]
        row["other_n_rows"] = item["other_n_rows"]
    return row


def table_rows(types: list[dict], word_diff: dict, phrase_diff: dict, protocol: dict, tolerance: int) -> list[dict]:
    rows: list[dict] = [
        {
            "kind": "protocol",
            "segments": protocol["segments"],
            "peak_tolerance": protocol["peak_tolerance"],
            "peak_tolerance_pct": protocol["peak_tolerance_pct"],
            "min_videos": protocol["min_videos"],
            "min_rows": protocol["min_rows"],
            "word_min_chars": protocol["word_min_chars"],
            "word_max_chars": protocol["word_max_chars"],
            "phrase_min_chars": protocol["phrase_min_chars"],
            "phrase_max_chars": protocol["phrase_max_chars"],
        }
    ]
    titles = [item["title"] for item in types]
    word_left, word_right = label_buckets(types[0]["claims"], types[1]["claims"], tolerance) if len(types) == 2 else ({}, {})
    phrase_left, phrase_right = (
        label_buckets(types[0]["phrases"], types[1]["phrases"], tolerance) if len(types) == 2 else ({}, {})
    )
    for index, item in enumerate(types):
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
        word_map = word_left if index == 0 else word_right
        phrase_map = phrase_left if index == 0 else phrase_right
        for claim in item["claims"]:
            rows.append(_claim_row(item, claim, word_map.get(claim["text"], ""), titles))
        for claim in item["phrases"]:
            rows.append(_claim_row(item, claim, phrase_map.get(claim["text"], ""), titles))
        rows.append({"kind": "solo", "type_id": item["id"], "layer": "word", "count": item["solo_word_count"]})
        rows.append({"kind": "solo", "type_id": item["id"], "layer": "phrase", "count": item["solo_phrase_count"]})
        for claim in item["solo_words"]:
            rows.append(
                {
                    "kind": "solo_item",
                    "layer": "word",
                    "type_id": item["id"],
                    "text": claim["text"],
                    "n_rows": claim["n_rows"],
                    "n_videos": claim["n_videos"],
                }
            )
        for claim in item["solo_phrases"]:
            rows.append(
                {
                    "kind": "solo_item",
                    "layer": "phrase",
                    "type_id": item["id"],
                    "text": claim["text"],
                    "n_rows": claim["n_rows"],
                    "n_videos": claim["n_videos"],
                }
            )
    for layer, diff in (("word", word_diff), ("phrase", phrase_diff)):
        for key in ("same_peak", "shifted", "only_a", "only_b"):
            bucket = diff[key]
            rows.append({"kind": "diff", "layer": layer, "diff": key, "count": bucket["count"]})
            for item in bucket["items"][:DIFF_ITEMS]:
                rows.append(_diff_item_row(item, key, layer))
    return rows


def briefing_from_table(rows: list[dict]) -> list[str]:
    sentences = [PURPOSE, SIGNOFF]
    types = [row for row in rows if row["kind"] == "type"]
    titles = [item["title"] for item in types]
    for item in types:
        sentences.append(item["volume_reading"])
        sentences.append(item["baseline_reading"])
        for layer in ("word", "phrase"):
            claims = [
                row
                for row in rows
                if row["kind"] == "claim" and row["type_id"] == item["type_id"] and row["layer"] == layer
            ]
            for claim in claims[:BRIEFING_CLAIMS_PER_TYPE]:
                sentences.append(claim["reading"])
        solos = {
            row["layer"]: row["count"]
            for row in rows
            if row["kind"] == "solo" and row["type_id"] == item["type_id"]
        }
        sentences.append(
            f"只在一条视频里出现、因此不写入这一类结论的词有{solos.get('word', 0)}个，完整说法有{solos.get('phrase', 0)}句。"
        )
    if len(titles) >= 2:
        sentences.append(f"对照的是{titles[0]}和{titles[1]}。")
    unit_name = {"word": "词", "phrase": "完整说法"}
    unit_measure = {"word": "个", "phrase": "句"}
    for layer in ("phrase", "word"):
        labels = {
            "same_peak": f"两边都有，而且最密的地方差不多的{unit_name[layer]}",
            "shifted": f"两边都有，但最密的地方错开了的{unit_name[layer]}",
            "only_a": f"只在{titles[0]}里反复出现的{unit_name[layer]}" if titles else "",
            "only_b": f"只在{titles[1]}里反复出现的{unit_name[layer]}" if len(titles) > 1 else "",
        }
        for key, label in labels.items():
            bucket = next(row for row in rows if row["kind"] == "diff" and row["layer"] == layer and row["diff"] == key)
            examples = [row for row in rows if row["kind"] == "diff_item" and row["layer"] == layer and row["diff"] == key]
            if examples:
                sentences.append(f"{label}有{bucket['count']}{unit_measure[layer]}，例如「{examples[0]['text']}」。")
            else:
                sentences.append(f"{label}有{bucket['count']}{unit_measure[layer]}。")
    return sentences
