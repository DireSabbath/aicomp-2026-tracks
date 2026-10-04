"""短文本的词对主题模型（BTM）。

一条弹幕太短，按文档去抽主题会空。BTM 把同一条里的两个字块当成一对来抽样。
这一步是 CPU 上的吉布斯采样，不需要 GPU。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from train.corpus import read_texts


def bigrams(text: str) -> list[str]:
    chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    return ["".join(chars[index : index + 2]) for index in range(len(chars) - 1)]


def _docs(texts: list[str], min_count: int) -> tuple[list[str], list[list[int]]]:
    counts: dict[str, int] = {}
    raw = []
    for text in texts:
        grams = []
        seen: set[str] = set()
        for gram in bigrams(text):
            if gram in seen:
                continue
            seen.add(gram)
            grams.append(gram)
            counts[gram] = counts.get(gram, 0) + 1
        raw.append(grams)
    vocab = [gram for gram, count in counts.items() if count >= min_count]
    vocab.sort(key=lambda gram: (-counts[gram], gram))
    index = {gram: pos for pos, gram in enumerate(vocab)}
    docs = []
    for grams in raw:
        ids = [index[gram] for gram in grams if gram in index]
        if len(ids) >= 2:
            docs.append(ids)
    return vocab, docs


def _biterms(docs: list[list[int]], cap_tokens: int, max_biterms: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    rows = []
    owners = []
    for doc_id, ids in enumerate(docs):
        chosen = ids
        if len(chosen) > cap_tokens:
            chosen = rng.choice(chosen, size=cap_tokens, replace=False).tolist()
        for left in range(len(chosen)):
            for right in range(left + 1, len(chosen)):
                rows.append((chosen[left], chosen[right]))
                owners.append(doc_id)
    pairs = np.asarray(rows, dtype=np.int32) if rows else np.zeros((0, 2), dtype=np.int32)
    owner = np.asarray(owners, dtype=np.int32) if owners else np.zeros(0, dtype=np.int32)
    if len(pairs) > max_biterms:
        keep = rng.choice(len(pairs), size=max_biterms, replace=False)
        pairs = pairs[keep]
        owner = owner[keep]
    return pairs, owner


def fit_btm(
    docs: list[list[int]],
    *,
    n_topics: int,
    n_vocab: int,
    iters: int = 30,
    alpha: float = 0.1,
    beta: float = 0.01,
    max_biterms: int = 2_000_000,
    cap_tokens: int = 8,
    seed: int = 0,
) -> dict:
    rng = np.random.default_rng(seed)
    pairs, _owner = _biterms(docs, cap_tokens, max_biterms, rng)
    if len(pairs) == 0:
        raise SystemExit("词对不够，主题模型没有可抽样的材料。")
    assign = rng.integers(0, n_topics, size=len(pairs), dtype=np.int32)
    topic_count = np.zeros(n_topics, dtype=np.int32)
    word_count = np.zeros((n_topics, n_vocab), dtype=np.int32)
    total = np.zeros(n_topics, dtype=np.int32)
    for pair, topic in zip(pairs, assign):
        topic = int(topic)
        topic_count[topic] += 1
        word_count[topic, int(pair[0])] += 1
        word_count[topic, int(pair[1])] += 1
        total[topic] += 2
    for _step in range(iters):
        order = rng.permutation(len(pairs))
        for spot in order:
            left = int(pairs[spot, 0])
            right = int(pairs[spot, 1])
            topic = int(assign[spot])
            topic_count[topic] -= 1
            word_count[topic, left] -= 1
            word_count[topic, right] -= 1
            total[topic] -= 2
            base = total + n_vocab * beta
            weight_left = word_count[:, left] + beta
            weight_right = word_count[:, right] + beta
            if left == right:
                probs = (topic_count + alpha) * weight_left * (weight_left + 1) / (base * (base + 1))
            else:
                probs = (topic_count + alpha) * weight_left * weight_right / (base * base)
            probs = np.maximum(probs, 0)
            scale = float(probs.sum())
            if scale <= 0:
                topic = int(rng.integers(0, n_topics))
            else:
                topic = int(rng.choice(n_topics, p=probs / scale))
            assign[spot] = topic
            topic_count[topic] += 1
            word_count[topic, left] += 1
            word_count[topic, right] += 1
            total[topic] += 2
    phi = (word_count + beta) / (total[:, None] + n_vocab * beta)
    return {"phi": phi, "topic_count": topic_count}


def write_topics(comments: Path, out_dir: Path, *, n_topics: int = 12, min_count: int = 5, iters: int = 30, seed: int = 0) -> dict:
    texts = read_texts(comments)
    vocab, docs = _docs(texts, min_count)
    if len(vocab) < 2:
        raise SystemExit("重复出现的二字块不够，主题模型停在这里。")
    fitted = fit_btm(docs, n_topics=n_topics, n_vocab=len(vocab), iters=iters, seed=seed)
    topics = []
    for topic in range(n_topics):
        order = np.argsort(-fitted["phi"][topic])[:12]
        topics.append(
            {
                "id": topic,
                "n": int(fitted["topic_count"][topic]),
                "words": [{"word": vocab[int(pos)], "prob": round(float(fitted["phi"][topic, pos]), 4)} for pos in order],
            }
        )
    payload = {
        "trained": True,
        "device": "cpu",
        "model": "btm",
        "rows": len(texts),
        "docs": len(docs),
        "vocab": len(vocab),
        "topics": topics,
        "method": "同一条弹幕里的二字块组成词对，吉布斯抽样。短文本不按整篇文档估主题。",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "topics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
