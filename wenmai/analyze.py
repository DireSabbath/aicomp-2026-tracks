"""从本地弹幕池做六维统计。摘要里不写弹幕原文。"""

from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from pathlib import Path

from wenmai.classify import classify, find_symbols
from wenmai.codebook import CODE_NAMES, CODE_TO_DIM, DESCRIPTIONS, DIMENSIONS, DIM_NAMES
from wenmai.model import (
    evaluation_report,
    fit_char_model,
    public_metrics,
    stable_hash,
)

LAUGH = set("哈啊嗯哦呵呀哟嘻嘿")
EXTRA = set("1234567890wW~.！!。?？~、，,")
BINS = 20
BURST_BINS = 10


class Reservoir:
    def __init__(self, cap: int):
        self.cap = cap
        self.items: list[str] = []
        self.seen = 0

    def add(self, text: str) -> None:
        self.seen += 1
        if len(self.items) < self.cap:
            self.items.append(text)
            return
        ticket = stable_hash(text) % self.seen
        if ticket < self.cap:
            self.items[stable_hash("slot:" + text) % self.cap] = text


def _is_laugh(text: str) -> bool:
    compact = "".join(text.split())
    if len(compact) < 2:
        return False
    return all(char in LAUGH or char in EXTRA for char in compact)


def _cjk_bigrams(text: str) -> list[str]:
    chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    return [a + b for a, b in zip(chars, chars[1:])]


def _video_rows(path: Path) -> list[dict]:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _index(corpus: Path, list_path: Path | None) -> tuple[list[dict], int]:
    listed: dict[str, dict] = {}
    if list_path and list_path.exists():
        for item in json.loads(list_path.read_text(encoding="utf-8")):
            listed[item["bvid"]] = item
    files = {path.name.split(".")[0]: path for path in sorted(corpus.glob("*.jsonl.gz"))}
    pending = 0
    rows = []
    if listed:
        for bvid, meta in listed.items():
            path = files.get(bvid)
            if path is None:
                pending += 1
                continue
            rows.append({"bvid": bvid, "path": path, "list": meta})
        return rows, pending
    for bvid, path in files.items():
        rows.append({"bvid": bvid, "path": path, "list": {}})
    return rows, 0


def _duration_ms(meta_path: Path, rows: list[dict]) -> int:
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        parts = meta.get("parts") or []
        total = sum(int(part.get("duration") or 0) for part in parts) * 1000
        if total > 0:
            return total
    peak = 0
    for row in rows:
        moment = row.get("timeline_ms")
        if moment is None:
            moment = row.get("progress_ms") or 0
        peak = max(peak, int(moment or 0))
    return peak + 1


def _moment(row: dict) -> int:
    if row.get("timeline_ms") is not None:
        return int(row["timeline_ms"] or 0)
    return int(row.get("progress_ms") or 0)


def findings(summary: dict) -> list[str]:
    if not summary["danmaku"]:
        return ["当前目录里还没有弹幕。"]
    lines = [
        (
            f"已读 {summary['videos']} 个视频、{summary['danmaku']:,} 条弹幕，"
            f"其中 {summary['coded']:,} 条至少落入一类（{summary['coded_rate']:.1%}）。"
        ),
        "一条弹幕可以同时落入多类，各类数量相加可以超过已编码条数。",
    ]
    if summary["coded"]:
        dims = summary["by_dimension"]
        top = max(dims, key=dims.get)
        codes = summary["by_code"]
        top_code = max(codes, key=codes.get)
        lines.append(f"按这套码表，出现最多的一级维度是{top}（{dims[top]:,} 条）。")
        lines.append(f"二级里出现最多的是{top_code}（{codes[top_code]:,} 条）。")
        lines.append(
            f"已编码弹幕里，同时命中两类及以上的占 {summary['multi_rate']:.1%}。"
        )
    if summary.get("unlabeled"):
        lines.append(
            f"未编码弹幕里，纯气氛或笑声约占 {summary['laugh_rate']:.1%}。"
            "码表故意不把「哈哈」「好看」收进六维。"
        )
    rates = []
    for group, info in summary.get("groups", {}).items():
        if info["danmaku"] < 100:
            continue
        rate = info["dimension_rate"].get("传承意向", 0)
        rates.append((rate, info["title"]))
    if rates:
        rate, title = max(rates)
        if rate > 0:
            lines.append(
                f"在弹幕不少于 100 条的载体里，{title}更常出现传承意向"
                f"（占该组弹幕的 {rate:.1%}）。"
            )
    arc = summary.get("arc") or {}
    if arc:
        rising = max(arc, key=lambda dim: arc[dim]["delta"])
        falling = min(arc, key=lambda dim: arc[dim]["delta"])
        if arc[rising]["delta"] > 0.005:
            lines.append(
                f"片尾四分之一比片头四分之一，{rising}的视频等权比例高 {arc[rising]['delta']:.1%}。"
            )
        if falling != rising and arc[falling]["delta"] < -0.005:
            lines.append(
                f"同一对照下，{falling}在片尾更少，相差 {arc[falling]['delta']:.1%}。"
            )
    lifts = []
    for info in summary.get("groups", {}).values():
        if info["danmaku"] < 100:
            continue
        lift = (info.get("lift") or {}).get("传承意向", 0)
        lifts.append((lift, info["title"]))
    if lifts:
        lift, title = max(lifts)
        if lift >= 1.15:
            lines.append(f"{title}的传承意向是全库的 {lift:.2f} 倍。")
    peaked = []
    for code, info in (summary.get("concentration") or {}).items():
        if info.get("videos", 0) >= 3 and info.get("top_share", 0) >= 0.5 and info.get("top"):
            peaked.append((info["top_share"], code, info["top"][0].get("title") or ""))
    if peaked:
        share, code, title = max(peaked)
        short = title if len(title) <= 28 else title[:28] + "…"
        lines.append(
            f"{code}里 {share:.0%} 来自同一支视频（{short}）。读这一类时要和其余片子分开。"
        )
    if summary.get("qa_questions"):
        lines.append(
            f"{summary['qa_questions']:,} 条知识疑问，和 5 秒内的知识补证落在同一时间窗。"
        )
    bursts = sum(summary.get("bursts", {}).values())
    if bursts:
        lines.append(
            f"按每个视频 10 段进度，密度不低于该视频均值 3 倍且至少 3 条，共记下 {bursts} 次类别突发。"
        )
    rules = summary.get("rules_core") or {}
    if rules:
        lines.append(
            f"团队自写核心句上，规则精确匹配 {rules['exact_match']:.1%}，"
            f"宏平均 F1 {rules['macro_f1']:.3f}。这不是真实弹幕的人工一致率。"
        )
    agree = summary.get("model_agreement")
    if agree:
        lines.append(
            f"字符模型对照规则银标的宏平均 F1 为 {agree['macro_f1']:.3f}。"
            "银标来自规则，不是人工金标。"
        )
    if summary.get("empty_pools"):
        lines.append(
            f"{summary['empty_pools']} 支视频的当前公开池是空的。页面弹幕计数是热门线，播放器里现在能拉到的可以少很多，也可以是零。"
        )
    if summary.get("pending"):
        lines.append(f"清单里还有 {summary['pending']} 个视频尚未落盘，以上只覆盖已经拉到的部分。")
    return lines


def _agreement(pos: dict[str, Reservoir], neg: Reservoir) -> dict | None:
    merged: dict[str, set[str]] = {}
    for code, bucket in pos.items():
        for text in bucket.items:
            merged.setdefault(text, set()).update(classify(text))
    for text in neg.items:
        merged.setdefault(text, set())
    if len(merged) < 40:
        return None
    train = []
    eval_items = []
    for text, labels in merged.items():
        item = (text, labels)
        if stable_hash("split:" + text) % 5 == 0:
            eval_items.append(item)
        else:
            train.append(item)
    if len(train) < 30 or len(eval_items) < 8:
        return None
    model = fit_char_model(train, epochs=6)
    gold = [labels for _, labels in eval_items]
    pred = [model.predict(text) for text, _ in eval_items]
    from wenmai.model import score_sets

    report = score_sets(gold, pred)
    report.pop("per_code", None)
    model_only = Counter()
    rule_only = Counter()
    for gold_set, pred_set in zip(gold, pred):
        model_only.update(pred_set - gold_set)
        rule_only.update(gold_set - pred_set)
    return {
        "exact_match": report["exact_match"],
        "micro_f1": report["micro_f1"],
        "macro_f1": report["macro_f1"],
        "n": report["n"],
        "train_n": len(train),
        "model_only": {code: model_only[code] for code in CODE_NAMES},
        "rule_only": {code: rule_only[code] for code in CODE_NAMES},
    }


def analyze(corpus: Path, list_path: Path | None, out: Path) -> dict:
    corpus = Path(corpus)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    videos, pending = _index(corpus, list_path)
    by_code = Counter()
    by_dim = Counter()
    symbol_count = Counter()
    symbol_cat = Counter()
    symbol_of = {}
    co = [[0 for _ in CODE_NAMES] for _ in CODE_NAMES]
    code_index = {code: index for index, code in enumerate(CODE_NAMES)}
    bursts = Counter()
    share_sum = {dim: [0.0] * BINS for dim in DIM_NAMES}
    share_weight = [0] * BINS
    timeline_videos = 0
    qa_questions = 0
    laugh_n = 0
    unlabeled = 0
    residue = Counter()
    length = {"le4": [0, 0], "gt4": [0, 0]}
    groups: dict[str, dict] = {}
    pos = {code: Reservoir(250) for code in CODE_NAMES}
    neg = Reservoir(1200)
    exemplars: dict[str, list[str]] = {code: [] for code in CODE_NAMES}
    video_hits = {code: Counter() for code in CODE_NAMES}
    titles: dict[str, str] = {}
    mode_all: Counter = Counter()
    mode_coded: Counter = Counter()
    mode_dim = {dim: Counter() for dim in DIM_NAMES}
    hours = {"coded": [0] * 24, "other": [0] * 24}
    symbol_dim: dict[str, Counter] = {}
    dim_index = {dim: index for index, dim in enumerate(DIM_NAMES)}
    transitions = [[0 for _ in DIM_NAMES] for _ in DIM_NAMES]
    danmaku = 0
    coded = 0
    multi = 0
    empty_pools = 0

    for video in videos:
        rows = _video_rows(video["path"])
        meta_path = video["path"].with_name(video["bvid"] + ".meta.json")
        duration = _duration_ms(meta_path, rows)
        info = video["list"]
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            info = {**info, **{k: meta[k] for k in meta if k not in info or info.get(k) in (None, "")}}
        group = info.get("group") or "other"
        title = info.get("group_title") or ("未分组" if group == "other" else group)
        bucket = groups.setdefault(
            group,
            {
                "title": title,
                "videos": 0,
                "danmaku": 0,
                "coded": 0,
                "by_dimension": {dim: 0 for dim in DIM_NAMES},
            },
        )
        bucket["videos"] += 1
        titles[video["bvid"]] = str(info.get("title") or video["bvid"])[:80]
        local_dim = {dim: [0] * BINS for dim in DIM_NAMES}
        local_n = [0] * BINS
        local_code = {code: [0] * BURST_BINS for code in CODE_NAMES}
        q_at: dict[int, int] = {}
        s_at: dict[int, int] = {}
        if not rows:
            empty_pools += 1
        for row in rows:
            text = row.get("content") or ""
            danmaku += 1
            bucket["danmaku"] += 1
            hits = classify(text)
            symbols = find_symbols(text)
            mode = row.get("mode")
            if mode is not None:
                mode_all[str(int(mode))] += 1
            ctime = row.get("ctime")
            if ctime:
                hour = (int(ctime) + 8 * 3600) // 3600 % 24
                hours["coded" if hits else "other"][hour] += 1
            moment = _moment(row)
            bin_index = min(BINS - 1, int(moment / duration * BINS)) if duration else 0
            burst_index = min(BURST_BINS - 1, int(moment / duration * BURST_BINS)) if duration else 0
            local_n[bin_index] += 1
            short = len(text.strip()) <= 4
            slot = length["le4" if short else "gt4"]
            slot[0] += 1
            if hits:
                coded += 1
                bucket["coded"] += 1
                slot[1] += 1
                if len(hits) > 1:
                    multi += 1
                dims = {CODE_TO_DIM[code] for code in hits}
                for dim in dims:
                    by_dim[dim] += 1
                    bucket["by_dimension"][dim] += 1
                    local_dim[dim][bin_index] += 1
                    if mode is not None:
                        mode_dim[dim][str(int(mode))] += 1
                if mode is not None:
                    mode_coded[str(int(mode))] += 1
                for code in hits:
                    by_code[code] += 1
                    local_code[code][burst_index] += 1
                    video_hits[code][video["bvid"]] += 1
                    pos[code].add(text)
                    if len(exemplars[code]) < 8:
                        exemplars[code].append(text)
                ordered = [code for code in CODE_NAMES if code in hits]
                for left in range(len(ordered)):
                    for right in range(left + 1, len(ordered)):
                        a = code_index[ordered[left]]
                        b = code_index[ordered[right]]
                        co[a][b] += 1
                        co[b][a] += 1
                if "知识疑问" in hits:
                    q_at[moment // 1000] = q_at.get(moment // 1000, 0) + 1
                if "知识补证" in hits:
                    s_at[moment // 1000] = s_at.get(moment // 1000, 0) + 1
            else:
                unlabeled += 1
                if _is_laugh(text):
                    laugh_n += 1
                elif 4 <= len(text) <= 40 and stable_hash(text) % 3 == 0:
                    for gram in _cjk_bigrams(text):
                        residue[gram] += 1
                if len(text.strip()) >= 2:
                    neg.add(text)
            for name, category in symbols:
                symbol_count[name] += 1
                symbol_of[name] = category
            for category in {category for _, category in symbols}:
                symbol_cat[category] += 1
            if hits:
                for category in {category for _, category in symbols}:
                    slot = symbol_dim.setdefault(category, Counter())
                    for dim in dims:
                        slot[dim] += 1
        if len(rows) >= 30:
            timeline_videos += 1
            dominant = []
            for index, count in enumerate(local_n):
                best_dim = None
                best_n = 0
                for dim in DIM_NAMES:
                    value = local_dim[dim][index]
                    if value > best_n:
                        best_n = value
                        best_dim = dim
                dominant.append(best_dim)
                if not count:
                    continue
                share_weight[index] += 1
                for dim in DIM_NAMES:
                    share_sum[dim][index] += local_dim[dim][index] / count
            for left, right in zip(dominant, dominant[1:]):
                if left and right:
                    transitions[dim_index[left]][dim_index[right]] += 1
        for code, bins in local_code.items():
            total = sum(bins)
            if total < 6:
                continue
            mean = total / BURST_BINS
            for value in bins:
                if value >= 3 and value >= 3 * mean:
                    bursts[code] += 1
        for sec, questions in q_at.items():
            near = sum(s_at.get(sec + offset, 0) for offset in range(0, 6))
            if near:
                qa_questions += questions

    corpus_rate = {dim: (by_dim[dim] / danmaku if danmaku else 0.0) for dim in DIM_NAMES}
    for bucket in groups.values():
        base = bucket["danmaku"] or 1
        bucket["dimension_rate"] = {
            dim: bucket["by_dimension"][dim] / base for dim in DIM_NAMES
        }
        bucket["lift"] = {
            dim: (bucket["dimension_rate"][dim] / corpus_rate[dim]) if corpus_rate[dim] else 0.0
            for dim in DIM_NAMES
        }
    timeline = {
        "bins": BINS,
        "videos": timeline_videos,
        "series": {
            dim: [
                (share_sum[dim][index] / share_weight[index]) if share_weight[index] else 0.0
                for index in range(BINS)
            ]
            for dim in DIM_NAMES
        },
    }
    quarter = max(1, BINS // 4)
    arc = {}
    for dim, series in timeline["series"].items():
        early = sum(series[:quarter]) / quarter
        late = sum(series[-quarter:]) / quarter
        arc[dim] = {"early": early, "late": late, "delta": late - early}
    concentration = {}
    for code in CODE_NAMES:
        counts = video_hits[code]
        total = sum(counts.values())
        if not total:
            concentration[code] = {"videos": 0, "top_share": 0.0, "hhi": 0.0, "top": []}
            continue
        ranked = counts.most_common(3)
        concentration[code] = {
            "videos": len(counts),
            "top_share": ranked[0][1] / total,
            "hhi": sum((count / total) ** 2 for count in counts.values()),
            "top": [
                {"bvid": bvid, "title": titles.get(bvid, bvid), "count": count}
                for bvid, count in ranked
            ],
        }
    pmi = [[0.0 for _ in CODE_NAMES] for _ in CODE_NAMES]
    if danmaku:
        for left, code_left in enumerate(CODE_NAMES):
            for right, code_right in enumerate(CODE_NAMES):
                if left == right:
                    continue
                pa = by_code[code_left] / danmaku
                pb = by_code[code_right] / danmaku
                pab = co[left][right] / danmaku
                if pa > 0 and pb > 0 and pab > 0:
                    pmi[left][right] = math.log(pab / (pa * pb))
    informative = [
        {"gram": gram, "count": count}
        for gram, count in residue.most_common(80)
        if any(char not in LAUGH and char not in "的了是我你这不也都就和" for char in gram)
    ][:20]
    summary = {
        "videos": len(videos),
        "pending": pending,
        "empty_pools": empty_pools,
        "danmaku": danmaku,
        "coded": coded,
        "coded_rate": coded / danmaku if danmaku else 0.0,
        "multi_rate": multi / coded if coded else 0.0,
        "unlabeled": unlabeled,
        "laugh_rate": laugh_n / unlabeled if unlabeled else 0.0,
        "by_code": {code: by_code[code] for code in CODE_NAMES},
        "by_dimension": {dim: by_dim[dim] for dim in DIM_NAMES},
        "groups": groups,
        "timeline": timeline,
        "symbols": {
            "by_category": dict(symbol_cat),
            "top": [
                {"name": name, "category": symbol_of[name], "count": count}
                for name, count in symbol_count.most_common(24)
            ],
        },
        "cooccurrence": co,
        "pmi": pmi,
        "arc": arc,
        "transitions": transitions,
        "concentration": concentration,
        "hours": hours,
        "modes": {
            "all": dict(mode_all),
            "coded": dict(mode_coded),
            "by_dimension": {dim: dict(mode_dim[dim]) for dim in DIM_NAMES},
        },
        "symbol_dimension": {
            category: {dim: int(counter.get(dim, 0)) for dim in DIM_NAMES}
            for category, counter in sorted(symbol_dim.items())
        },
        "codes": CODE_NAMES,
        "dimensions": DIM_NAMES,
        "code_groups": {dim: codes for dim, codes in DIMENSIONS},
        "descriptions": DESCRIPTIONS,
        "qa_questions": qa_questions,
        "bursts": {code: bursts[code] for code in CODE_NAMES},
        "residue_bigrams": informative,
        "length_coverage": {
            key: {"n": value[0], "coded": value[1]} for key, value in length.items()
        },
        "rights": "摘要只有计数。弹幕正文在 exemplars.jsonl 和 silver.jsonl，这两份不进 git。页面能打开不等于可以再分发。",
    }
    report = public_metrics(evaluation_report())
    summary.update(report)
    agreement = _agreement(pos, neg)
    if agreement:
        summary["model_agreement"] = agreement
    summary["findings"] = findings(summary)
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (out / "exemplars.jsonl").open("w", encoding="utf-8") as handle:
        for code, texts in exemplars.items():
            for text in texts:
                handle.write(
                    json.dumps({"code": code, "text": text}, ensure_ascii=False) + "\n"
                )
    with (out / "silver.jsonl").open("w", encoding="utf-8") as handle:
        seen = set()
        for code, bucket in pos.items():
            for text in bucket.items:
                if text in seen:
                    continue
                seen.add(text)
                handle.write(
                    json.dumps(
                        {"text": text, "labels": sorted(classify(text), key=CODE_NAMES.index)},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        for text in neg.items:
            if text in seen:
                continue
            seen.add(text)
            handle.write(json.dumps({"text": text, "labels": []}, ensure_ascii=False) + "\n")
    return summary
