"""用一条评论里的字块互相当上下文，训出字块向量。

同义不同字如果老是挨着同一批字，向量会靠近。靠不靠近由训完的数决定，这里不先写结果。
CPU 上的负采样就够。这一步不需要 GPU。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from train.corpus import read_texts


def char_ngrams(text: str, lo: int = 2, hi: int = 4) -> list[str]:
    chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    grams = []
    for size in range(lo, hi + 1):
        for index in range(len(chars) - size + 1):
            grams.append("".join(chars[index : index + size]))
    return grams


def build_vocab(texts: list[str], min_count: int) -> list[str]:
    counts: dict[str, int] = {}
    for text in texts:
        seen: set[str] = set()
        for gram in char_ngrams(text):
            if gram in seen:
                continue
            seen.add(gram)
            counts[gram] = counts.get(gram, 0) + 1
    vocab = [gram for gram, count in counts.items() if count >= min_count]
    vocab.sort(key=lambda gram: (-counts[gram], gram))
    return vocab


def _pairs_in(ids: list[int], cap: int, rng: np.random.Generator) -> np.ndarray:
    chosen = ids
    if len(chosen) > cap:
        chosen = rng.choice(chosen, size=cap, replace=False).tolist()
    rows = []
    for center in chosen:
        for context in chosen:
            if center != context:
                rows.append((center, context))
    if not rows:
        return np.zeros((0, 2), dtype=np.int32)
    return np.asarray(rows, dtype=np.int32)


def train_skipgram(
    texts: list[str],
    *,
    dim: int = 64,
    min_count: int = 5,
    epochs: int = 5,
    negative: int = 5,
    lr: float = 0.05,
    cap: int = 12,
    seed: int = 0,
) -> tuple[list[str], np.ndarray]:
    vocab = build_vocab(texts, min_count)
    if len(vocab) < 2:
        raise SystemExit("能重复出现的字块不够，训不出向量。")
    index = {gram: pos for pos, gram in enumerate(vocab)}
    rng = np.random.default_rng(seed)
    scale = 0.1
    center = rng.normal(0, scale, (len(vocab), dim)).astype(np.float32)
    output = rng.normal(0, scale, (len(vocab), dim)).astype(np.float32)
    prepared = []
    for text in texts:
        ids = []
        seen: set[str] = set()
        for gram in char_ngrams(text):
            if gram in seen or gram not in index:
                continue
            seen.add(gram)
            ids.append(index[gram])
        if len(ids) >= 2:
            prepared.append(ids)
    for _epoch in range(epochs):
        order = rng.permutation(len(prepared))
        for spot in order:
            pairs = _pairs_in(prepared[int(spot)], cap, rng)
            if len(pairs) == 0:
                continue
            for start in range(0, len(pairs), 256):
                batch = pairs[start : start + 256]
                neg = rng.integers(0, len(vocab), size=(len(batch), negative))
                vector = center[batch[:, 0]]
                positive = output[batch[:, 1]]
                score = np.sum(vector * positive, axis=1)
                pred = 1 / (1 + np.exp(-np.clip(score, -20, 20)))
                grad = (pred - 1)[:, None]
                grad_vector = grad * positive
                grad_positive = grad * vector
                negative_vec = output[neg]
                score_n = np.einsum("bd,bkd->bk", vector, negative_vec)
                pred_n = 1 / (1 + np.exp(-np.clip(score_n, -20, 20)))
                grad_vector += np.einsum("bk,bkd->bd", pred_n, negative_vec)
                grad_negative = pred_n[:, :, None] * vector[:, None, :]
                np.add.at(center, batch[:, 0], -lr * grad_vector)
                np.add.at(output, batch[:, 1], -lr * grad_positive)
                np.add.at(output, neg, -lr * grad_negative)
    return vocab, center


def cosine(vectors: np.ndarray, vocab: list[str], left: str, right: str) -> float:
    table = {gram: pos for pos, gram in enumerate(vocab)}
    if left not in table or right not in table:
        raise KeyError((left, right))
    a = vectors[table[left]]
    b = vectors[table[right]]
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _bigrams(text: str) -> set[str]:
    return {text[index : index + 2] for index in range(len(text) - 1)}


def shares_span(left: str, right: str) -> bool:
    if left in right or right in left:
        return True
    return bool(_bigrams(left) & _bigrams(right))


def propose(vocab: list[str], vectors: np.ndarray, *, min_cosine: float = 0.72, query_cap: int = 3000, keep: int = 3) -> list[dict]:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    table = vectors / norms
    queries = min(query_cap, len(vocab))
    sims = table[:queries] @ table.T
    found = []
    for row in range(queries):
        order = np.argsort(-sims[row])
        kept = 0
        for col in order:
            if col == row:
                continue
            score = float(sims[row, col])
            if score < min_cosine:
                break
            left = vocab[row]
            right = vocab[int(col)]
            if len(left) != len(right) or len(left) not in (2, 3) or shares_span(left, right):
                continue
            found.append({"a": left, "b": right, "cosine": round(score, 4)})
            kept += 1
            if kept >= keep:
                break
    found.sort(key=lambda item: (-item["cosine"], item["a"], item["b"]))
    return found


def drop_glued(texts: list[str], pairs: list[dict], *, glue: float = 0.3) -> list[dict]:
    """总在同一条评论里出现的，是一句被切开的字块，不是两种说法。"""
    keys = {(pair["a"], pair["b"]) for pair in pairs}
    both = {key: 0 for key in keys}
    marginal: dict[str, int] = {}
    for text in texts:
        grams = set(char_ngrams(text))
        for gram in grams:
            marginal[gram] = marginal.get(gram, 0) + 1
        for key in keys:
            if key[0] in grams and key[1] in grams:
                both[key] += 1
    kept = []
    for pair in pairs:
        key = (pair["a"], pair["b"])
        base = min(marginal.get(key[0], 0), marginal.get(key[1], 0))
        if base and both[key] / base >= glue:
            continue
        kept.append(pair)
    return kept


def write_vectors(comments: Path, out_dir: Path, **kwargs) -> dict:
    texts = read_texts(comments)
    vocab, vectors = train_skipgram(texts, **kwargs)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "vectors.npy", vectors)
    (out_dir / "vocab.json").write_text(json.dumps(vocab, ensure_ascii=False), encoding="utf-8")
    pairs = drop_glued(texts, propose(vocab, vectors))
    payload = {
        "trained": True,
        "device": "cpu",
        "rows": len(texts),
        "vocab": len(vocab),
        "dim": int(vectors.shape[1]),
        "method": "同一条评论里的二字到四字块做跳元负采样。同义不同字要靠上下文靠近，不靠事先写好的同义词表。",
        "pairs": pairs[:200],
    }
    (out_dir / "synonyms.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
