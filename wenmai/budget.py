"""把 3090 24GB 上的一段墙钟排成可复核的编码器对照。

这里不加载模型，也不写弹幕原文。训练脚本按这里的下一项决定继续跑哪一次。
"""

from __future__ import annotations

import heapq

from wenmai.codebook import CODE_NAMES

PRIMARY_MODEL = "hfl/chinese-macbert-base"
SCALE_MODEL = "hfl/chinese-macbert-large"
ARCH_MODEL = "hfl/chinese-roberta-wwm-ext"

# 按 fp32、序列 64 的保守占用。3090 报出来的显存常是 23.7GB 左右，大卡门槛用 22。
VRAM_SCALE = 20.0
VRAM_ARCH = 8.0
LARGE_CARD_GB = 22.0

TRAIN_FACTOR = {
    PRIMARY_MODEL: 1.0,
    SCALE_MODEL: 4.0,
    ARCH_MODEL: 1.0,
}
PASS_FACTOR = {
    PRIMARY_MODEL: 1.0,
    SCALE_MODEL: 3.0,
    ARCH_MODEL: 1.0,
}

BUDGET_NOTE = (
    "种子 0 的主模型是报告采用的那一次。"
    "大模型和另一种开源编码器各跑一轮全量对照，用来看次数是否跟着参数规模或编码器变。"
    "其余时间重复主模型的种子，只保留分数范围。"
    "这些分数都对照码表，不是人工金标，也不替换页面上的规则计数。"
    "重复种子的权重不保存。"
)


def inference_batch_for(vram_gb: float, model: str) -> int:
    """全量前向的 batch。训练 batch 不在这里改。"""
    if model == SCALE_MODEL:
        if vram_gb >= LARGE_CARD_GB:
            return 64
        if vram_gb >= 18:
            return 32
        return 8
    if vram_gb >= LARGE_CARD_GB:
        return 256
    if vram_gb >= 16:
        return 128
    if vram_gb >= 8:
        return 64
    return 16


def train_batch_for(vram_gb: float, model: str, requested: int) -> int:
    """大模型在 24GB 上用较小的训练 batch，避免把种子 0 的主模型优化过程改掉。"""
    if model == SCALE_MODEL:
        cap = 8 if vram_gb >= LARGE_CARD_GB else 4
        return max(1, min(requested, cap))
    return max(1, requested)


def job_cost(model: str, kind: str, train_s: float, pass_s: float) -> float:
    cost = train_s * TRAIN_FACTOR.get(model, 1.0)
    if kind == "pass":
        cost += pass_s * PASS_FACTOR.get(model, 1.0)
    return cost


def fits_wall(elapsed_s: float, cost_s: float, budget_s: float, reserve_s: float) -> bool:
    return elapsed_s + cost_s + reserve_s <= budget_s


def reserve_for(train_s: float) -> float:
    return max(60.0, train_s)


def next_follow_up(
    *,
    elapsed_s: float,
    budget_s: float,
    train_s: float,
    pass_s: float,
    vram_gb: float,
    primary_model: str,
    finished: set[tuple],
    next_seed: int,
    reserve_s: float | None = None,
    requested_batch: int = 16,
) -> dict | None:
    """主模型种子 0 已经跑完之后的下一项。装得下大模型时先跑它，再跑另一种编码器，然后用重复种子填满剩余时间。"""
    reserve = reserve_for(train_s) if reserve_s is None else reserve_s
    catalog: list[tuple[str, int, str]] = []
    if primary_model != SCALE_MODEL and vram_gb >= VRAM_SCALE and (SCALE_MODEL, 0, "pass") not in finished:
        catalog.append((SCALE_MODEL, 0, "pass"))
    if primary_model != ARCH_MODEL and vram_gb >= VRAM_ARCH and (ARCH_MODEL, 0, "pass") not in finished:
        catalog.append((ARCH_MODEL, 0, "pass"))
    catalog.append((primary_model, next_seed, "train"))
    for model, seed, kind in catalog:
        cost = job_cost(model, kind, train_s, pass_s)
        if cost <= 0 or not fits_wall(elapsed_s, cost, budget_s, reserve):
            continue
        return {
            "model": model,
            "seed": seed,
            "kind": kind,
            "cost_s": cost,
            "infer_batch": inference_batch_for(vram_gb, model),
            "train_batch": train_batch_for(vram_gb, model, requested_batch),
        }
    return None


def smaller_batch(batch_size: int, message: str) -> int | None:
    if "out of memory" not in message.lower():
        return None
    if batch_size <= 1:
        return None
    return max(1, batch_size // 2)


class MarginBook:
    """只留离阈值最近的若干条。距离小的排在前面。"""

    def __init__(self, limit: int):
        self.limit = max(0, int(limit))
        self._heap: list[tuple] = []
        self._seq = 0

    def consider(self, text: str, distance: float, labels: list[str]) -> None:
        if self.limit <= 0:
            return
        self._seq += 1
        item = (-float(distance), self._seq, text, tuple(labels))
        if len(self._heap) < self.limit:
            heapq.heappush(self._heap, item)
            return
        if item[0] > self._heap[0][0]:
            heapq.heapreplace(self._heap, item)

    def ranked(self) -> list[dict]:
        rows = [
            {"distance": -item[0], "labels": list(item[3]), "text": item[2]}
            for item in self._heap
        ]
        rows.sort(key=lambda row: (row["distance"], row["text"]))
        return rows


def fold_predictions(texts: list[str], hit_sets: list[set[str]], probs, thresholds, margin: MarginBook) -> dict:
    """已编码的句子计入相对规则的多标和漏标。未编码的句子只更新边际清单。"""
    import numpy as np

    matrix = np.asarray(probs, dtype=np.float32)
    cutoff = np.asarray(thresholds, dtype=np.float32)
    false_pos = [0] * len(CODE_NAMES)
    false_neg = [0] * len(CODE_NAMES)
    coded_n = 0
    unlabeled_n = 0
    for index, (text, hits) in enumerate(zip(texts, hit_sets)):
        row = matrix[index]
        pred = {
            code
            for code_index, code in enumerate(CODE_NAMES)
            if float(row[code_index]) >= float(cutoff[code_index])
        }
        if hits:
            coded_n += 1
            for code_index, code in enumerate(CODE_NAMES):
                guessed = code in pred
                truth = code in hits
                if guessed and not truth:
                    false_pos[code_index] += 1
                elif truth and not guessed:
                    false_neg[code_index] += 1
            continue
        unlabeled_n += 1
        distance = float(np.min(np.abs(row - cutoff)))
        margin.consider(text, distance, sorted(pred))
    return {
        "coded_n": coded_n,
        "unlabeled_n": unlabeled_n,
        "fp": false_pos,
        "fn": false_neg,
    }


def public_budget_run(metrics: dict, *, keep_misses: bool) -> dict:
    """预算摘要只留计数和自写句的漏标。弹幕原文不进这里。"""
    core = dict(metrics.get("gold_core") or {})
    hard = dict(metrics.get("gold_hard") or {})
    record = {
        "model": metrics.get("model"),
        "seed": metrics.get("seed"),
        "macro_f1": metrics.get("macro_f1"),
        "gold_core_exact": core.get("exact_match"),
        "gold_hard_exact": hard.get("exact_match"),
        "per_code_f1": metrics.get("per_code_f1") or {},
    }
    if keep_misses:
        record["gold_core_misses"] = core.get("misses") or []
        record["gold_hard_misses"] = hard.get("misses") or []
    gap = metrics.get("gap") or {}
    if gap:
        record["gap_sample_n"] = gap.get("sample_n")
        record["gap_fired_n"] = gap.get("fired_n")
        record["gap_by_code"] = gap.get("by_code") or {}
    corpus = metrics.get("corpus") or {}
    if corpus:
        record["corpus_coded_n"] = corpus.get("coded_n")
        record["corpus_unlabeled_n"] = corpus.get("unlabeled_n")
        record["corpus_disagreement"] = corpus.get("disagreement") or {}
    return record


def _range(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    mid = ordered[len(ordered) // 2]
    if len(ordered) % 2 == 0:
        mid = (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
    return {"n": len(values), "min": ordered[0], "max": ordered[-1], "median": mid}


def summarize_runs(runs: list[dict], primary_model: str) -> dict:
    primary = [
        row
        for row in runs
        if row.get("model") == primary_model and row.get("macro_f1") is not None and not row.get("error")
    ]

    def pack(key: str) -> dict:
        values = [float(row[key]) for row in primary if row.get(key) is not None]
        return _range(values)

    return {
        "primary_model": primary_model,
        "primary_runs": len(primary),
        "macro_f1": pack("macro_f1"),
        "gold_core_exact": pack("gold_core_exact"),
        "gold_hard_exact": pack("gold_hard_exact"),
    }
