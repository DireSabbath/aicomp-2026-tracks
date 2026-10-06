"""把本地银标接到开源中文编码器上。

默认要求 CUDA。没有 GPU 时加 --cpu，只适合抽查流程，不适合全量。
银标文件由 `python -m wenmai analyze` 写到输出目录的 silver.jsonl，里面是弹幕正文，不要提交。
仓库里的 wenmai/sample_silver.jsonl 只是团队自写的格式样例。

示例：
  python -m wenmai.train_gpu --data wenmai/sample_silver.jsonl --out danmaku_out/gpu-smoke --cpu --epochs 1
  python -m wenmai.train_gpu --data danmaku_out/tradition-hot/silver.jsonl --out danmaku_out/gpu-model --model hfl/chinese-macbert-base --epochs 2
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from wenmai.codebook import CODE_NAMES


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
    return parser


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        rows = _read_rows(args.data)
        print(json.dumps({"rows": len(rows), "codes": len(CODE_NAMES)}, ensure_ascii=False))
        return 0
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
    random.Random(args.seed).shuffle(rows)
    split = max(1, int(len(rows) * 0.1))
    if split >= len(rows):
        split = 1
    eval_rows, train_rows = rows[:split], rows[split:]
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model,
        num_labels=len(CODE_NAMES),
        problem_type="multi_label_classification",
        id2label={index: code for index, code in enumerate(CODE_NAMES)},
        label2id={code: index for index, code in enumerate(CODE_NAMES)},
    ).to(device)

    class TextSet(Dataset):
        def __init__(self, data):
            self.data = data

        def __len__(self):
            return len(self.data)

        def __getitem__(self, index):
            item = self.data[index]
            encoded = tokenizer(
                item["text"],
                truncation=True,
                max_length=args.max_length,
                padding="max_length",
                return_tensors="pt",
            )
            return {
                "input_ids": encoded["input_ids"].squeeze(0),
                "attention_mask": encoded["attention_mask"].squeeze(0),
                "labels": torch.tensor(item["labels"], dtype=torch.float32),
            }

    train_loader = DataLoader(TextSet(train_rows), batch_size=args.batch_size, shuffle=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    model.train()
    for epoch in range(args.epochs):
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
    tp = [0] * len(CODE_NAMES)
    fp = [0] * len(CODE_NAMES)
    fn = [0] * len(CODE_NAMES)
    with torch.no_grad():
        for batch in DataLoader(TextSet(eval_rows), batch_size=args.batch_size):
            labels = batch.pop("labels").to(device)
            batch = {key: value.to(device) for key, value in batch.items()}
            logits = model(**batch).logits
            pred = (torch.sigmoid(logits) >= 0.5).int()
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
    metrics = {
        "model": args.model,
        "device": str(device),
        "train_n": len(train_rows),
        "eval_n": len(eval_rows),
        "macro_f1": sum(supported) / len(supported) if supported else 0.0,
        "per_code_f1": {code: f1_of(index) for index, code in enumerate(CODE_NAMES)},
        "note": "验证集来自银标随机划分，银标本身是规则或自写句，不是人工金标。",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    (args.out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: metrics[key] for key in ("device", "train_n", "eval_n", "macro_f1")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
