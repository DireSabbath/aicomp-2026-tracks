"""字符 n-gram 多标签模型。只依赖 numpy，CPU 上就能训。

训练句是团队自写的说法，不使用平台弹幕。真实弹幕上的银标只在本地分析时临时采样，不写进这个文件。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from wenmai.codebook import CODE_NAMES
from wenmai.classify import label_list

N_FEATURES = 1 << 15


def stable_hash(token: str) -> int:
    value = 2166136261
    for char in token:
        value ^= ord(char)
        value = (value * 16777619) & 0xFFFFFFFF
    return value


def token_features(text: str, n_features: int = N_FEATURES) -> dict[int, float]:
    compact = "".join(text.split())
    if not compact:
        return {}
    grams = list(compact)
    grams.extend(compact[i : i + 2] for i in range(len(compact) - 1))
    grams.extend(compact[i : i + 3] for i in range(len(compact) - 2))
    found: dict[int, float] = {}
    for gram in grams:
        found[stable_hash(gram) % n_features] = 1.0
    return found


def _f1(tp: int, fp: int, fn: int) -> float:
    if tp == 0:
        return 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def score_sets(gold: list[set[str]], pred: list[set[str]]) -> dict:
    per = {}
    tp = fp = fn = 0
    exact = 0
    for code in CODE_NAMES:
        tpi = fpi = fni = 0
        for truth, guess in zip(gold, pred):
            in_truth = code in truth
            in_guess = code in guess
            if in_truth and in_guess:
                tpi += 1
            elif in_guess:
                fpi += 1
            elif in_truth:
                fni += 1
        precision = tpi / (tpi + fpi) if tpi + fpi else 0.0
        recall = tpi / (tpi + fni) if tpi + fni else 0.0
        per[code] = {
            "precision": precision,
            "recall": recall,
            "f1": _f1(tpi, fpi, fni),
            "support": tpi + fni,
        }
        tp += tpi
        fp += fpi
        fn += fni
    for truth, guess in zip(gold, pred):
        if truth == guess:
            exact += 1
    supported = [item["f1"] for item in per.values() if item["support"]]
    return {
        "exact_match": exact / len(gold) if gold else 0.0,
        "micro_f1": _f1(tp, fp, fn),
        "macro_f1": sum(supported) / len(supported) if supported else 0.0,
        "per_code": per,
        "n": len(gold),
    }


class CharModel:
    def __init__(self, weights, bias, thresholds, n_features: int = N_FEATURES):
        self.weights = weights
        self.bias = bias
        self.thresholds = thresholds
        self.n_features = n_features

    def scores(self, text: str) -> np.ndarray:
        feats = token_features(text, self.n_features)
        if not feats:
            return self.bias.copy()
        idx = np.fromiter(feats.keys(), dtype=np.int32)
        values = np.ones(len(idx), dtype=np.float32)
        logits = self.bias + self.weights[:, idx] @ values
        logits = np.clip(logits, -20, 20)
        return 1 / (1 + np.exp(-logits))

    def predict(self, text: str) -> set[str]:
        scores = self.scores(text)
        return {
            code
            for code, score, threshold in zip(CODE_NAMES, scores, self.thresholds)
            if score >= threshold
        }


def fit_char_model(
    examples: list[tuple[str, set[str]]],
    *,
    epochs: int = 10,
    lr: float = 0.15,
    l2: float = 1e-5,
    n_features: int = N_FEATURES,
    seed: int = 0,
) -> CharModel:
    width = len(CODE_NAMES)
    weights = np.zeros((width, n_features), dtype=np.float32)
    bias = np.zeros(width, dtype=np.float32)
    positive = np.zeros(width, dtype=np.float32)
    for _, labels in examples:
        for index, code in enumerate(CODE_NAMES):
            if code in labels:
                positive[index] += 1
    total = float(len(examples) or 1)
    pos_weight = np.ones(width, dtype=np.float32)
    for index, count in enumerate(positive):
        if count:
            pos_weight[index] = float(np.clip((total - count) / count, 1, 6))
    rng = np.random.default_rng(seed)
    order = np.arange(len(examples))
    for _ in range(epochs):
        rng.shuffle(order)
        weights *= np.float32(1 - lr * l2)
        for row in order:
            text, labels = examples[int(row)]
            feats = token_features(text, n_features)
            if not feats:
                continue
            idx = np.fromiter(feats.keys(), dtype=np.int32)
            values = np.ones(len(idx), dtype=np.float32)
            logits = np.clip(bias + weights[:, idx] @ values, -20, 20)
            probability = 1 / (1 + np.exp(-logits))
            target = np.array(
                [1.0 if code in labels else 0.0 for code in CODE_NAMES],
                dtype=np.float32,
            )
            gradient = (probability - target) * np.where(target > 0, pos_weight, 1.0)
            weights[:, idx] -= np.float32(lr) * (gradient[:, None] * values[None, :])
            bias -= np.float32(lr) * gradient
    thresholds = _tune_thresholds(examples, weights, bias, n_features)
    return CharModel(weights, bias, thresholds, n_features)


def thresholds_from_scores(matrix: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """按类在给定分数上搜索阈值。没有正例的类抬到 0.99，避免空类被误标。"""
    width = int(matrix.shape[1]) if matrix.ndim == 2 else 0
    thresholds = np.full(width, 0.5, dtype=np.float32)
    grid = [step / 20 for step in range(2, 19)]
    for index in range(width):
        if targets.size == 0 or int(targets[:, index].sum()) == 0:
            thresholds[index] = 0.99
            continue
        best_f = -1.0
        best_t = 0.5
        for threshold in grid:
            guess = matrix[:, index] >= threshold
            tp = int(np.sum(guess & (targets[:, index] == 1)))
            fp = int(np.sum(guess & (targets[:, index] == 0)))
            fn = int(np.sum(~guess & (targets[:, index] == 1)))
            value = _f1(tp, fp, fn)
            if value > best_f:
                best_f = value
                best_t = threshold
        thresholds[index] = best_t
    return thresholds


def _tune_thresholds(examples, weights, bias, n_features: int) -> np.ndarray:
    model = CharModel(weights, bias, np.full(len(CODE_NAMES), 0.5), n_features)
    matrix = np.vstack([model.scores(text) for text, _ in examples]) if examples else np.zeros((0, len(CODE_NAMES)))
    targets = np.array(
        [[1 if code in labels else 0 for code in CODE_NAMES] for _, labels in examples],
        dtype=np.int8,
    )
    return thresholds_from_scores(matrix, targets)


def rule_gap_counts(predict, texts: list[str]) -> dict:
    """规则没编码的句子上，模型还标出了哪些类。只留计数。"""
    from collections import Counter

    counts: Counter = Counter()
    fired = 0
    for text in texts:
        pred = set(predict(text))
        if pred:
            fired += 1
            counts.update(pred)
    return {
        "sample_n": len(texts),
        "fired_n": fired,
        "by_code": {code: int(counts[code]) for code in CODE_NAMES},
        "note": "这些弹幕规则没有编码，也没有拿去训练。数字是字符模型多标出的类，不是人工金标。原文不写入摘要。",
    }


def template_examples() -> list[tuple[str, set[str]]]:
    """自写训练句。不得与 gold.json 的句子相同。"""
    rows = [
        ("画面质感拉满啊", {"制作认可"}),
        ("这期考据扎实，文案也好", {"制作认可"}),
        ("配乐加分，还原度高", {"制作认可"}),
        ("解说专业，细节到位", {"制作认可"}),
        ("讲得真好，听完还想再听一遍", {"制作认可"}),
        ("剪辑流畅，拍得真好", {"制作认可"}),
        ("服化道好，美术绝了", {"制作认可"}),
        ("运镜好，打光好", {"制作认可"}),
        ("制作太用心了", {"制作认可"}),
        ("剪辑烂而且念稿", {"制作诟病"}),
        ("太拖沓，内容注水", {"制作诟病"}),
        ("讲解混乱，硬伤很多", {"制作诟病"}),
        ("制作粗糙，特效五毛", {"制作诟病"}),
        ("音画不同步，不专业", {"制作诟病"}),
        ("穿帮了，考据不严", {"制作诟病"}),
        ("字幕太小还卡顿", {"观看体验"}),
        ("没有字幕，加载失败", {"观看体验"}),
        ("字幕不错，台词终于跟得上", {"观看体验"}),
        ("这么卡，一直转圈", {"观看体验"}),
        ("时长太长了，片头太长", {"观看体验"}),
        ("清晰度不行，画面糊", {"观看体验"}),
        ("倍速才能看完，缓冲不停", {"观看体验"}),
        ("补充一下出处在史书", {"知识补证"}),
        ("这里搞反了，实为另一个名字", {"知识补证"}),
        ("我查过，更准确的记载是这样", {"知识补证"}),
        ("视频里这个不对，应为铭文那一说", {"知识补证"}),
        ("冷知识，正名和俗名不一样", {"知识补证"}),
        ("这纹样是什么意思，求科普", {"知识疑问"}),
        ("哪个朝代的，求解释", {"知识疑问"}),
        ("谁写的，有没有出处", {"知识疑问"}),
        ("请问这是什么，没看懂", {"知识疑问"}),
        ("是不是真的，求证一下", {"知识疑问"}),
        ("隔着千年也能共情", {"古今共情"}),
        ("跨越时空的共鸣", {"古今共情"}),
        ("身临其境，他们也曾这样生活", {"古今共情"}),
        ("古代人也把日子过成了仪式", {"古今共情"}),
        ("千年以后仍然心有戚戚", {"古今共情"}),
        ("文化自信从这儿来，吾辈记得", {"文化自豪"}),
        ("老祖宗的底蕴，华夏的浪漫", {"文化自豪"}),
        ("这是国粹，值得骄傲", {"文化自豪"}),
        ("血脉里的文明之光", {"文化自豪"}),
        ("小时候奶奶在老家讲过", {"文化记忆"}),
        ("小学课本里的集体记忆", {"文化记忆"}),
        ("想起童年和故乡的年节", {"文化记忆"}),
        ("爷爷当年在家乡见过", {"文化记忆"}),
        ("意境和留白都在，东方美学", {"传统美学褒扬"}),
        ("气韵生动，配色好", {"传统美学褒扬"}),
        ("唱腔有余韵，古典美", {"传统美学褒扬"}),
        ("水墨的诗意，线条美", {"传统美学褒扬"}),
        ("古人的审美和现代审美不同", {"审美辨析"}),
        ("审美差异要单独说，美在于含蓄", {"审美辨析"}),
        ("为什么美，审美观并不一样", {"审美辨析"}),
        ("这门手艺快失传，后继无人", {"传承困境探讨"}),
        ("学的人少，青黄不接", {"传承困境探讨"}),
        ("小众到快绝迹，没人愿意学", {"传承困境探讨"}),
        ("非遗濒危，传承难", {"传承困境探讨"}),
        ("国潮让老手艺年轻化", {"古今适配讨论"}),
        ("怎么传承，才能走进现代", {"古今适配讨论"}),
        ("传统与现代的活化，不要只是跨界融合的空话", {"古今适配讨论"}),
        ("当代表达可以把旧曲新唱", {"古今适配讨论"}),
        ("和西方相比，礼制不同", {"文化比较"}),
        ("比起日本的祭，这边更重亲族", {"文化比较"}),
        ("中西差异不该只说谁高级", {"文化比较"}),
        ("外国没有这种节气节奏", {"文化比较"}),
        ("想学，求教程，想入门", {"学习意愿"}),
        ("哪里能学，求师傅", {"学习意愿"}),
        ("我也要学，有教程吗", {"学习意愿"}),
        ("想练，求资源", {"学习意愿"}),
        ("安利给我妈，让更多人看到", {"传播意愿"}),
        ("转发给家人，推荐给朋友", {"传播意愿"}),
        ("叫朋友看，分享到家族群", {"传播意愿"}),
        ("我们村还有，我亲眼见过", {"实践印证"}),
        ("我学过，家里有一整套", {"实践印证"}),
        ("我是传承人，我做过", {"实践印证"}),
        ("家乡有这个，我参加过", {"实践印证"}),
        ("哈哈哈哈哈哈", set()),
        ("前方高能预警", set()),
        ("真好看", set()),
        ("来了来了来了", set()),
        ("空降成功了", set()),
        ("2333333", set()),
        ("打卡成功", set()),
        ("前排就位", set()),
        ("完结撒花了", set()),
        ("awsl啊", set()),
        ("再看一遍", set()),
        ("进度条警告", set()),
        ("名场面", set()),
        ("弹幕护体", set()),
        ("下次一定", set()),
    ]
    return rows


def load_gold(path: Path | None = None) -> tuple[list[dict], list[dict]]:
    target = path or Path(__file__).with_name("gold.json")
    data = json.loads(target.read_text(encoding="utf-8"))
    return data["core"], data["hard"]


def _predict_rules(text: str) -> set[str]:
    return set(label_list(text))


def evaluate_split(items: list[dict], predict) -> dict:
    gold = [set(item["labels"]) for item in items]
    pred = [set(predict(item["text"])) for item in items]
    report = score_sets(gold, pred)
    misses = []
    for item, guess in zip(items, pred):
        truth = set(item["labels"])
        if truth - guess or guess - truth:
            misses.append(
                {
                    "text": item["text"],
                    "missing": sorted(truth - guess),
                    "extra": sorted(guess - truth),
                }
            )
    report["misses"] = misses
    return report


def evaluation_report(gold_path: Path | None = None) -> dict:
    core, hard = load_gold(gold_path)
    forbidden = {item["text"] for item in core + hard}
    examples = template_examples()
    leaked = [text for text, _ in examples if text in forbidden]
    if leaked:
        raise RuntimeError(f"训练句和金标句子重复: {leaked}")
    model = fit_char_model(examples)
    return {
        "rules_core": evaluate_split(core, _predict_rules),
        "rules_hard": evaluate_split(hard, _predict_rules),
        "model_core": evaluate_split(core, model.predict),
        "model_hard": evaluate_split(hard, model.predict),
        "train_size": len(examples),
    }


def public_metrics(report: dict) -> dict:
    """去掉逐句对照，避免摘要被句子列表撑大。保留 misses 只用于自写金标。"""
    keep = {}
    for key, value in report.items():
        if key == "train_size":
            keep[key] = value
            continue
        if not isinstance(value, dict):
            keep[key] = value
            continue
        keep[key] = {
            "exact_match": value.get("exact_match"),
            "micro_f1": value.get("micro_f1"),
            "macro_f1": value.get("macro_f1"),
            "n": value.get("n"),
            "per_code": value.get("per_code", {}),
            "misses": value.get("misses", []),
        }
    return keep
