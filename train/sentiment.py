"""在这批弹幕上训一个三分类器：正、负、中性。

压缩包里没有情感标签。默认用一份写明的词表先标弱标签，分类器照这批标签训。
换上人工标签文件之后，用同一条命令重训。弱标签不是人核对过的答案。
这一步用字块的线性分类器，CPU 就能训完。
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import LogisticRegression

from train.corpus import read_texts

LABELS = ("正", "负", "中性")
POSITIVE = ("好看", "好帅", "爱了", "泪目", "牛逼", "太强", "绝了", "哈哈", "笑死", "感动", "好听", "顶级", "封神", "万岁")
NEGATIVE = ("难看", "失望", "垃圾", "无聊", "难听", "退钱", "恶心", "拉胯", "气死", "崩了", "差评", "无语")


def weak_label(text: str) -> str:
    positive = any(cue in text for cue in POSITIVE)
    negative = any(cue in text for cue in NEGATIVE)
    if positive and not negative:
        return "正"
    if negative and not positive:
        return "负"
    return "中性"


def _vectorizer() -> HashingVectorizer:
    return HashingVectorizer(analyzer="char", ngram_range=(2, 3), n_features=2**12, alternate_sign=False)


def fit_classifier(texts: list[str], labels: list[str], seed: int = 0):
    if len(texts) != len(labels):
        raise SystemExit("文本和标签条数不一致。")
    unknown = sorted(set(labels) - set(LABELS))
    if unknown:
        raise SystemExit(f"标签只接受 {'、'.join(LABELS)}，看到了 {unknown}。")
    if len(set(labels)) < 2:
        raise SystemExit("标签至少要有两类，分类器才训得起来。")
    vectorizer = _vectorizer()
    features = vectorizer.transform(texts)
    model = LogisticRegression(max_iter=400, random_state=seed)
    model.fit(features, labels)
    return vectorizer, model


def predict(vectorizer, model, texts: list[str]) -> list[str]:
    return model.predict(vectorizer.transform(texts)).tolist()


def load_label_file(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            text = (item.get("text") or item.get("content") or "").strip()
            label = item.get("label")
            if not text or label not in LABELS:
                continue
            rows.append({"text": text, "label": label})
    return rows


def write_sentiment(comments: Path, out_dir: Path, *, labels_path: Path | None = None, seed: int = 0) -> dict:
    if labels_path is None:
        texts = read_texts(comments)
        labels = [weak_label(text) for text in texts]
        source = "lexicon"
        human_checked = False
    else:
        rows = load_label_file(labels_path)
        texts = [row["text"] for row in rows]
        labels = [row["label"] for row in rows]
        source = "file"
        human_checked = False
    vectorizer, model = fit_classifier(texts, labels, seed=seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "model.pkl").open("wb") as handle:
        pickle.dump({"vectorizer": vectorizer, "model": model, "labels": list(LABELS)}, handle)
    counts = {label: labels.count(label) for label in LABELS}
    payload = {
        "trained": True,
        "device": "cpu",
        "rows": len(texts),
        "label_source": source,
        "human_checked": human_checked,
        "counts": counts,
        "cues": {"正": list(POSITIVE), "负": list(NEGATIVE)},
        "method": "二字和三字块的线性分类器。默认标签来自词表，不是人工逐条核对。",
    }
    (out_dir / "sentiment.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
