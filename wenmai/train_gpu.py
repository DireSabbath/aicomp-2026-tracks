"""把本地银标接到开源中文编码器上。

默认要求 CUDA。没有 GPU 时加 --cpu，只适合抽查流程，不适合全量。
银标文件由 `python -m wenmai analyze` 写到输出目录的 silver.jsonl，里面是弹幕正文，不要提交。
仓库里的 wenmai/sample_silver.jsonl 只是团队自写的格式样例。

3090 24GB、约 3 小时的用法见 --hours。主模型种子 0 写 metrics.json。
随后若显存放得下，再跑大模型和另一种编码器的全量对照，并用重复种子填满剩余时间。
重复种子的权重不保存。边际清单和权重都不要提交。

示例：
  python -m wenmai.train_gpu --data wenmai/sample_silver.jsonl --out /tmp/wenmai-gpu-smoke --cpu --epochs 1
  python -m wenmai.train_gpu \
    --data wenmai/results/silver.jsonl \
    --out danmaku_out/gpu-model \
    --model hfl/chinese-macbert-base \
    --epochs 2 \
    --hours 3 \
    --corpus danmaku_out/tradition-hot \
    --list danmaku/lists/tradition-hot/_videos.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

from wenmai.budget import (
    BUDGET_NOTE,
    MarginBook,
    budget_model_names,
    fold_predictions,
    inference_batch_for,
    next_follow_up,
    public_budget_run,
    smaller_batch,
    summarize_runs,
    write_budget,
)
from wenmai.codebook import CODE_NAMES
from wenmai.model import evaluate_split, load_gold, rule_gap_counts, thresholds_from_scores

GPU_NOTE = (
    "银标划分出来的验证集只说明编码器像不像规则。"
    "核心句和难句是团队自写句，对照的是码表，不是从弹幕里抽出来的人工金标。"
)

CORPUS_NOTE = (
    "已编码弹幕上的多标和漏标，是编码器相对规则的次数。"
    "未编码、长度 4 到 40 且不是纯笑声的句子用来留边际清单。"
    "这不是人工金标，也不替换页面上的规则计数。"
)

ENCODER_GAP_NOTE = (
    "这些弹幕规则没有编码，也没有拿去训练。"
    "数字是编码器多标出的类，不是人工金标。原文不写入摘要。"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="用银标微调开源中文编码器，十七类多标签。")
    parser.add_argument("--data", type=Path, required=True, help="jsonl，每行有 text 和 labels")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="hfl/chinese-macbert-base")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=64)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cpu", action="store_true", help="没有 GPU 时也跑，只适合样例或抽查")
    parser.add_argument("--check", action="store_true", help="只检查银标格式，不加载模型")
    parser.add_argument("--corpus", type=Path, default=None, help="本地弹幕池。给出后才数同一批缺口，并写边际清单")
    parser.add_argument("--list", type=Path, default=None, help="与分析时相同的视频清单，用来保持缺口抽样顺序")
    parser.add_argument(
        "--margin-out",
        type=Path,
        default=None,
        help="离阈值最近的未编码句子。默认写到输出目录，不要提交",
    )
    parser.add_argument("--margin-limit", type=int, default=40)
    parser.add_argument(
        "--margin-per-code",
        type=int,
        default=8,
        help="每个类另留这么多条离该类阈值最近的未编码句子",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=None,
        help="墙钟预算（小时）。仅 CUDA 上会继续跑大模型、另一种编码器和重复种子",
    )
    parser.add_argument("--vram", type=float, default=None, help="显存 GB。默认读当前 CUDA 设备")
    parser.add_argument("--infer-batch", type=int, default=None, help="全量前向的 batch。默认按显存选取")
    return parser


def disagreement_counts(false_pos: list[int], false_neg: list[int]) -> dict:
    """编码器多标和漏标的各类次数。不保留句子。"""
    return {
        "model_only": {code: int(false_pos[index]) for index, code in enumerate(CODE_NAMES)},
        "rule_only": {code: int(false_neg[index]) for index, code in enumerate(CODE_NAMES)},
        "note": "模型多标是编码器判了而银标没有。规则有而模型无是银标有而编码器没判。银标来自规则，不是人工金标。",
    }


def gold_public(report: dict) -> dict:
    """自写句可以留下逐句漏标和多标。弹幕原文不走这条。"""
    return {
        "exact_match": report.get("exact_match"),
        "micro_f1": report.get("micro_f1"),
        "macro_f1": report.get("macro_f1"),
        "n": report.get("n"),
        "misses": report.get("misses") or [],
    }


def nearest_queue(texts: list[str], probs, thresholds, limit: int = 40) -> list[dict]:
    """取概率离各类阈值最近的句子。距离小的靠前，留给团队自己看。"""
    import numpy as np

    book = MarginBook(limit)
    matrix = np.asarray(probs, dtype=np.float32)
    cutoff = np.asarray(thresholds, dtype=np.float32)
    for index, text in enumerate(texts):
        distance = float(np.min(np.abs(matrix[index] - cutoff)))
        labels = [
            code
            for code_index, code in enumerate(CODE_NAMES)
            if float(matrix[index, code_index]) >= float(cutoff[code_index])
        ]
        book.consider(text, distance, labels)
    return book.ranked()


def _read_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        labels = set(item.get("labels") or [])
        unknown = labels - set(CODE_NAMES)
        if unknown:
            raise SystemExit(f"银标里有码表之外的类：{sorted(unknown)}")
        if not str(item.get("text") or "").strip():
            raise SystemExit("银标里有空文本")
        rows.append(
            {
                "text": item["text"],
                "labels": [1.0 if code in labels else 0.0 for code in CODE_NAMES],
            }
        )
    if len(rows) < 2:
        raise SystemExit("银标至少要有 2 行")
    return rows


# 训练只用 PyTorch 权重。TensorFlow / Flax 文件不计入这 3 小时。
WEIGHT_IGNORE = ["*.h5", "*.ot", "*.msgpack", "*.onnx", "flax_model*", "tf_model*", "rust_model*"]


def warm_model_cache(names: list[str], download=None) -> None:
    """先把 PyTorch 权重量到本机缓存。失败不中断，训练时还会再试一次。"""
    if download is None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            print("没有 huggingface_hub，跳过预下载。", flush=True)
            return
        download = snapshot_download
    for name in names:
        print(f"下载编码器缓存 {name}", flush=True)
        try:
            download(repo_id=name, ignore_patterns=list(WEIGHT_IGNORE))
        except Exception as exc:
            print(f"下载 {name} 没有完成：{exc}", flush=True)


def _empty_cuda_cache() -> None:
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def fit_with_oom_retry(fit, batch_size: int):
    """显存不够就把训练 batch 减半，整轮重试。减到 1 仍失败则抛出。

    异常对象会留住失败那一轮的模型，所以先离开 except，再回收显存。
    """
    import gc

    batch = max(1, int(batch_size))
    while True:
        try:
            return fit(batch), batch
        except Exception as exc:
            message = str(exc)
            nxt = smaller_batch(batch, message)
        gc.collect()
        _empty_cuda_cache()
        if nxt is None:
            raise RuntimeError(message) from None
        print(f"显存不足，训练 batch 从 {batch} 降到 {nxt} 后重试这一轮", flush=True)
        batch = nxt


def _vram_gb(torch_mod, device) -> float:
    if getattr(device, "type", None) != "cuda":
        return 0.0
    props = torch_mod.cuda.get_device_properties(device)
    return float(props.total_memory) / (1024 ** 3)


def fit_encoder(
    *,
    rows: list[dict],
    model_name: str,
    seed: int,
    epochs: int,
    batch_size: int,
    lr: float,
    max_length: int,
    device,
    torch,
    auto_model,
    auto_tokenizer,
    data_loader,
    dataset_cls,
) -> dict:
    """微调一轮并在银标验证集、核心句、难句上打分。调用方决定是否保存权重。"""
    started = time.monotonic()
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    split = max(1, int(len(shuffled) * 0.1))
    if split >= len(shuffled):
        split = 1
    eval_rows, train_rows = shuffled[:split], shuffled[split:]
    tokenizer = auto_tokenizer.from_pretrained(model_name)
    model = auto_model.from_pretrained(
        model_name,
        num_labels=len(CODE_NAMES),
        problem_type="multi_label_classification",
        id2label={index: code for index, code in enumerate(CODE_NAMES)},
        label2id={code: index for index, code in enumerate(CODE_NAMES)},
    ).to(device)
    loop_started = time.monotonic()

    class TextSet(dataset_cls):
        def __init__(self, data):
            self.data = data

        def __len__(self):
            return len(self.data)

        def __getitem__(self, index):
            item = self.data[index]
            encoded = tokenizer(
                item["text"],
                truncation=True,
                max_length=max_length,
                padding="max_length",
                return_tensors="pt",
            )
            return {
                "input_ids": encoded["input_ids"].squeeze(0),
                "attention_mask": encoded["attention_mask"].squeeze(0),
                "labels": torch.tensor(item["labels"], dtype=torch.float32),
            }

    train_loader = data_loader(TextSet(train_rows), batch_size=batch_size, shuffle=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    model.train()
    for epoch in range(epochs):
        total = 0.0
        seen = 0
        for batch in train_loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            optimizer.zero_grad()
            loss = model(**batch).loss
            loss.backward()
            optimizer.step()
            total += float(loss.item()) * batch["labels"].shape[0]
            seen += batch["labels"].shape[0]
        print(f"epoch {epoch + 1} loss {total / max(1, seen):.4f}", flush=True)

    model.eval()
    import numpy as np

    score_rows = []
    target_rows = []
    with torch.no_grad():
        for batch in data_loader(TextSet(train_rows), batch_size=batch_size):
            labels = batch.pop("labels")
            batch = {key: value.to(device) for key, value in batch.items()}
            probs = torch.sigmoid(model(**batch).logits).cpu().numpy()
            score_rows.append(probs)
            target_rows.append(labels.numpy())
    thresholds = thresholds_from_scores(np.vstack(score_rows), np.vstack(target_rows))
    cutoff = torch.tensor(thresholds, dtype=torch.float32, device=device)
    tp = [0] * len(CODE_NAMES)
    fp = [0] * len(CODE_NAMES)
    fn = [0] * len(CODE_NAMES)
    with torch.no_grad():
        for batch in data_loader(TextSet(eval_rows), batch_size=batch_size):
            labels = batch.pop("labels").to(device)
            batch = {key: value.to(device) for key, value in batch.items()}
            logits = model(**batch).logits
            pred = (torch.sigmoid(logits) >= cutoff).int()
            truth = labels.int()
            for index in range(len(CODE_NAMES)):
                tp[index] += int(((pred[:, index] == 1) & (truth[:, index] == 1)).sum())
                fp[index] += int(((pred[:, index] == 1) & (truth[:, index] == 0)).sum())
                fn[index] += int(((pred[:, index] == 0) & (truth[:, index] == 1)).sum())

    def f1_of(index: int) -> float:
        precision = tp[index] / (tp[index] + fp[index]) if tp[index] + fp[index] else 0.0
        recall = tp[index] / (tp[index] + fn[index]) if tp[index] + fn[index] else 0.0
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    supported = [f1_of(index) for index in range(len(CODE_NAMES)) if tp[index] + fn[index]]

    def predict_gold(text: str) -> set[str]:
        encoded = tokenizer(
            text,
            truncation=True,
            max_length=max_length,
            padding="max_length",
            return_tensors="pt",
        )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.no_grad():
            probs = torch.sigmoid(model(**encoded).logits).squeeze(0).cpu().numpy()
        return {
            code
            for code, score, threshold in zip(CODE_NAMES, probs, thresholds)
            if float(score) >= float(threshold)
        }

    core, hard = load_gold()
    metrics = {
        "model": model_name,
        "device": str(device),
        "seed": seed,
        "train_n": len(train_rows),
        "eval_n": len(eval_rows),
        "macro_f1": sum(supported) / len(supported) if supported else 0.0,
        "per_code_f1": {code: f1_of(index) for index, code in enumerate(CODE_NAMES)},
        "disagreement": disagreement_counts(fp, fn),
        "thresholds": {code: float(thresholds[index]) for index, code in enumerate(CODE_NAMES)},
        "gold_core": gold_public(evaluate_split(core, predict_gold)),
        "gold_hard": gold_public(evaluate_split(hard, predict_gold)),
        "note": GPU_NOTE,
    }
    return {
        "metrics": metrics,
        "model": model,
        "tokenizer": tokenizer,
        "thresholds": thresholds,
        "train_s": time.monotonic() - loop_started,
        "load_s": loop_started - started,
    }


def attach_corpus(
    model,
    tokenizer,
    device,
    args,
    thresholds,
    infer_batch: int,
    *,
    write_margin: bool,
    score_fn=None,
) -> dict:
    """一次读完弹幕池：已编码对照规则，同一批缺口只留次数，未编码句子留边际清单。

    score_fn 只在测试里替换前向。正式运行走编码器。
    """
    from wenmai.analyze import _index, _video_rows, collect_gap_texts, is_margin_candidate
    from wenmai.classify import classify

    def score(texts: list[str]):
        if score_fn is not None:
            return score_fn(texts)
        return _batched_probs(
            texts,
            tokenizer,
            model,
            device,
            args.max_length,
            forward_batch[0],
            forward_batch,
        )

    margin = MarginBook(args.margin_limit)
    per_code = {code: MarginBook(args.margin_per_code) for code in CODE_NAMES}
    false_pos = [0] * len(CODE_NAMES)
    false_neg = [0] * len(CODE_NAMES)
    coded_n = 0
    unlabeled_n = 0
    videos, _pending = _index(Path(args.corpus), args.list)
    batch_texts: list[str] = []
    batch_hits: list[set[str]] = []
    forward_batch = [max(1, infer_batch)]

    def flush() -> None:
        nonlocal coded_n, unlabeled_n
        if not batch_texts:
            return
        probs = score(batch_texts)
        stats = fold_predictions(batch_texts, batch_hits, probs, thresholds, margin, per_code)
        coded_n += stats["coded_n"]
        unlabeled_n += stats["unlabeled_n"]
        for index in range(len(CODE_NAMES)):
            false_pos[index] += stats["fp"][index]
            false_neg[index] += stats["fn"][index]
        batch_texts.clear()
        batch_hits.clear()

    for seen, video in enumerate(videos, start=1):
        for row in _video_rows(video["path"]):
            text = row.get("content") or ""
            if not str(text).strip():
                continue
            hits = classify(text)
            if hits or is_margin_candidate(text, hits):
                batch_texts.append(text)
                batch_hits.append(hits)
                if len(batch_texts) >= forward_batch[0]:
                    flush()
        if seen % 50 == 0:
            print(f"已读 {seen} 支视频", flush=True)
    flush()

    gap_items = collect_gap_texts(args.corpus, args.list)
    gap_probs = score(gap_items)
    lookup = {}
    for text, row in zip(gap_items, gap_probs):
        lookup[text] = {
            code
            for index, code in enumerate(CODE_NAMES)
            if float(row[index]) >= float(thresholds[index])
        }
    fragment = {
        "corpus": {
            "coded_n": coded_n,
            "unlabeled_n": unlabeled_n,
            "disagreement": disagreement_counts(false_pos, false_neg),
            "note": CORPUS_NOTE,
        },
        "gap": rule_gap_counts(
            lambda text: lookup.get(text, set()),
            gap_items,
            note=ENCODER_GAP_NOTE,
        ),
    }
    if write_margin:
        margin_path = args.margin_out or (args.out / "margin-queue.json")
        margin_path.parent.mkdir(parents=True, exist_ok=True)
        margin_path.write_text(
            json.dumps(
                {
                    "note": "这些句子规则没有编码，长度在 4 到 40 之间，且不是纯笑声。rows 是离任一阈值最近的句子。per_code 是离该类阈值最近的句子，避免稀有类被挤掉。留给团队自己看。不要提交。",
                    "rows": margin.ranked(),
                    "per_code": {code: book.ranked() for code, book in per_code.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        fragment["margin_queue"] = str(margin_path)
    return fragment


def _release(torch, packed: dict | None) -> None:
    if not packed:
        return
    packed.pop("model", None)
    packed.pop("tokenizer", None)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _batched_probs(texts, tokenizer, model, device, max_length: int, batch_size: int, remembered: list[int] | None = None):
    import numpy as np
    import torch

    if not texts:
        return np.zeros((0, len(CODE_NAMES)), dtype=np.float32)
    size = max(1, batch_size)
    while True:
        chunks = []
        try:
            model.eval()
            with torch.no_grad():
                for start in range(0, len(texts), size):
                    batch = texts[start : start + size]
                    encoded = tokenizer(
                        list(batch),
                        truncation=True,
                        max_length=max_length,
                        padding="max_length",
                        return_tensors="pt",
                    )
                    encoded = {key: value.to(device) for key, value in encoded.items()}
                    chunks.append(torch.sigmoid(model(**encoded).logits).cpu().numpy())
            if remembered is not None:
                remembered[0] = size
            return np.vstack(chunks)
        except RuntimeError as exc:
            nxt = smaller_batch(size, str(exc))
            if nxt is None:
                raise
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print(f"显存不足，前向 batch 从 {size} 降到 {nxt}", flush=True)
            size = nxt
            if remembered is not None:
                remembered[0] = size


def write_metrics(path: Path, metrics: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_corpus(metrics: dict, attach) -> tuple[dict, float]:
    """跑全量前向。失败时保留训练分数，文件里只记异常类型，不记异常正文。"""
    started = time.monotonic()
    try:
        extra = attach()
    except Exception as exc:
        print(f"全量前向没有跑完：{exc}", flush=True)
        failed = dict(metrics)
        failed["corpus_error"] = type(exc).__name__
        return failed, time.monotonic() - started
    merged = dict(metrics)
    merged.update(extra or {})
    return merged, time.monotonic() - started


def commit_primary(out: Path, metrics: dict, attach, before_attach=None) -> tuple[dict, float]:
    """先把种子 0 的训练分数落盘，再做全量前向。前向中断时，这份分数还在。"""
    write_metrics(out / "metrics.json", metrics)
    if before_attach is not None:
        before_attach()
    if attach is None:
        return metrics, 0.0
    updated, spent = apply_corpus(metrics, attach)
    write_metrics(out / "metrics.json", updated)
    return updated, spent


def _print_metrics(metrics: dict) -> None:
    printed = {
        key: metrics[key]
        for key in ("device", "seed", "train_n", "eval_n", "macro_f1", "train_batch", "gold_core", "gold_hard", "disagreement")
        if key in metrics
    }
    if metrics.get("gap"):
        printed["gap"] = {key: metrics["gap"][key] for key in ("sample_n", "fired_n", "by_code")}
    if metrics.get("corpus"):
        printed["corpus_coded_n"] = metrics["corpus"]["coded_n"]
        printed["corpus_unlabeled_n"] = metrics["corpus"]["unlabeled_n"]
    if metrics.get("corpus_error"):
        printed["corpus_error"] = metrics["corpus_error"]
    print(json.dumps(printed, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        rows = _read_rows(args.data)
        print(json.dumps({"rows": len(rows), "codes": len(CODE_NAMES)}, ensure_ascii=False))
        return 0
    if args.corpus and not args.corpus.exists():
        print(f"找不到弹幕池：{args.corpus}", file=sys.stderr)
        return 2
    try:
        import torch
        from torch.utils.data import DataLoader, Dataset
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        print(
            "还没装 torch / transformers。GPU 机器上执行：pip install -r wenmai/requirements-gpu.txt",
            file=sys.stderr,
        )
        print(exc, file=sys.stderr)
        return 2
    if not torch.cuda.is_available() and not args.cpu:
        print("没有检测到 CUDA。接到 GPU 后重跑；只抽查流程就加 --cpu。", file=sys.stderr)
        return 2
    device = torch.device("cpu" if args.cpu or not torch.cuda.is_available() else "cuda")
    rows = _read_rows(args.data)
    vram = args.vram if args.vram is not None else _vram_gb(torch, device)
    infer_batch = args.infer_batch or inference_batch_for(vram, args.model)
    if device.type != "cuda":
        infer_batch = args.infer_batch or args.batch_size
    started = time.monotonic()
    if args.hours and args.hours > 0 and device.type == "cuda":
        warm_model_cache(budget_model_names(args.model, vram))
    def fit_primary(batch_size: int) -> dict:
        return fit_encoder(
            rows=rows,
            model_name=args.model,
            seed=args.seed,
            epochs=args.epochs,
            batch_size=batch_size,
            lr=args.lr,
            max_length=args.max_length,
            device=device,
            torch=torch,
            auto_model=AutoModelForSequenceClassification,
            auto_tokenizer=AutoTokenizer,
            data_loader=DataLoader,
            dataset_cls=Dataset,
        )

    packed, used_batch = fit_with_oom_retry(fit_primary, args.batch_size)
    train_s = max(1.0, packed["train_s"])
    metrics = packed["metrics"]
    metrics["train_batch"] = used_batch

    def save_weights() -> None:
        try:
            packed["model"].save_pretrained(args.out)
            packed["tokenizer"].save_pretrained(args.out)
        except Exception as exc:
            print(f"权重没有保存：{exc}", flush=True)
            metrics["weight_error"] = type(exc).__name__
            write_metrics(args.out / "metrics.json", metrics)

    attach = None
    if args.corpus:
        attach = lambda: attach_corpus(
            packed["model"],
            packed["tokenizer"],
            device,
            args,
            packed["thresholds"],
            infer_batch,
            write_margin=True,
        )
    metrics, pass_s = commit_primary(args.out, metrics, attach, before_attach=save_weights)
    _print_metrics(metrics)
    corpus_ok = args.corpus is not None and "corpus_error" not in metrics

    use_budget = bool(args.hours and args.hours > 0 and device.type == "cuda")
    if args.hours and args.hours > 0 and device.type != "cuda":
        print("小时预算只在 CUDA 上继续排后续作业。这次只完成当前这一轮。", flush=True)
    if not use_budget:
        _release(torch, packed)
        return 0

    _release(torch, packed)
    budget_s = float(args.hours) * 3600.0
    elapsed = time.monotonic() - started
    finished: set[tuple] = set()
    next_seed = args.seed + 1
    primary = public_budget_run(metrics, keep_misses=True)
    primary["kind"] = "pass" if corpus_ok else "train"
    primary["seconds"] = elapsed
    runs = [primary]

    def checkpoint() -> None:
        write_budget(
            args.out / "budget.json",
            {
                "budget_s": budget_s,
                "elapsed_s": time.monotonic() - started,
                "vram_gb": vram,
                "train_s": train_s,
                "pass_s": pass_s,
                "infer_batch_primary": infer_batch,
                "note": BUDGET_NOTE,
                "corpus_ok": corpus_ok,
                "runs": runs,
                "summary": summarize_runs(runs, args.model),
            },
        )

    checkpoint()
    while True:
        job = next_follow_up(
            elapsed_s=elapsed,
            budget_s=budget_s,
            train_s=train_s,
            pass_s=pass_s,
            vram_gb=vram,
            primary_model=args.model,
            finished=finished,
            next_seed=next_seed,
            requested_batch=args.batch_size,
            allow_pass=corpus_ok,
        )
        if job is None:
            break
        print(
            f"预算作业 {job['model']} seed {job['seed']} {job['kind']}，预计 {job['cost_s']:.0f} 秒",
            flush=True,
        )
        job_started = time.monotonic()
        follow = None
        try:
            def fit_follow(batch_size: int) -> dict:
                return fit_encoder(
                    rows=rows,
                    model_name=job["model"],
                    seed=job["seed"],
                    epochs=args.epochs,
                    batch_size=batch_size,
                    lr=args.lr,
                    max_length=args.max_length,
                    device=device,
                    torch=torch,
                    auto_model=AutoModelForSequenceClassification,
                    auto_tokenizer=AutoTokenizer,
                    data_loader=DataLoader,
                    dataset_cls=Dataset,
                )

            follow, used_batch = fit_with_oom_retry(fit_follow, job["train_batch"])
            follow_metrics = follow["metrics"]
            follow_metrics["train_batch"] = used_batch
            record = public_budget_run(follow_metrics, keep_misses=job["seed"] == 0)
            record["kind"] = "train"
            record["seconds"] = time.monotonic() - job_started
            runs.append(record)
            checkpoint()
            if job["kind"] == "pass" and corpus_ok:
                follow_metrics, _spent = apply_corpus(
                    follow_metrics,
                    lambda: attach_corpus(
                        follow["model"],
                        follow["tokenizer"],
                        device,
                        args,
                        follow["thresholds"],
                        job["infer_batch"],
                        write_margin=False,
                    ),
                )
                record = public_budget_run(follow_metrics, keep_misses=job["seed"] == 0)
                record["kind"] = "pass" if "corpus_error" not in follow_metrics else "train"
                record["seconds"] = time.monotonic() - job_started
                runs[-1] = record
            print(
                json.dumps(
                    {
                        "model": record["model"],
                        "seed": record["seed"],
                        "macro_f1": record["macro_f1"],
                        "gold_core_exact": record["gold_core_exact"],
                        "gold_hard_exact": record["gold_hard_exact"],
                        "train_batch": record.get("train_batch"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as exc:
            print(f"这一轮没有跑完：{exc}", flush=True)
            runs.append(
                {
                    "model": job["model"],
                    "seed": job["seed"],
                    "kind": job["kind"],
                    "error": type(exc).__name__,
                }
            )
        finally:
            _release(torch, follow)
        finished.add((job["model"], job["seed"], job["kind"]))
        if job["kind"] == "train":
            next_seed += 1
        elapsed = time.monotonic() - started
        checkpoint()

    elapsed = time.monotonic() - started
    checkpoint()
    print(
        json.dumps(
            {
                "elapsed_s": elapsed,
                "runs": len(runs),
                "summary": summarize_runs(runs, args.model),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
