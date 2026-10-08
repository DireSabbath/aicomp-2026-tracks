"""按视频放回重抽样，给抬升和符号绑定一个区间。

抽样单位是当前池里有字的视频。空池不进入抽样框。
摘要里仍然是点估计；这里只追加区间，不改六维计数。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from wenmai.analyze import _index, _video_rows
from wenmai.classify import classify, find_symbols
from wenmai.codebook import CODE_NAMES, CODE_TO_DIM, DIM_NAMES


def scan_videos(corpus: Path, list_path: Path | None) -> list[dict]:
    """每支有字的视频留下计数。不保留弹幕原文。"""
    videos, _pending = _index(Path(corpus), list_path)
    code_index = {code: index for index, code in enumerate(CODE_NAMES)}
    dim_index = {dim: index for index, dim in enumerate(DIM_NAMES)}
    records = []
    for seen, video in enumerate(videos, start=1):
        rows = _video_rows(video["path"])
        if not rows:
            continue
        info = video["list"]
        group = info.get("group") or "other"
        codes = np.zeros(len(CODE_NAMES), dtype=np.int32)
        dims = np.zeros(len(DIM_NAMES), dtype=np.int32)
        sym_dims = np.zeros(len(DIM_NAMES), dtype=np.int32)
        sym_n = 0
        sym_count: dict[str, int] = {}
        sym_by: dict[str, np.ndarray] = {}
        for row in rows:
            text = row.get("content") or ""
            hits = classify(text)
            symbols = find_symbols(text)
            hit_dims = {CODE_TO_DIM[code] for code in hits} if hits else set()
            if hits:
                for code in hits:
                    codes[code_index[code]] += 1
                for dim in hit_dims:
                    dims[dim_index[dim]] += 1
            if symbols:
                sym_n += 1
                for dim in hit_dims:
                    sym_dims[dim_index[dim]] += 1
            for name, _category in symbols:
                sym_count[name] = sym_count.get(name, 0) + 1
                if hits:
                    slot = sym_by.get(name)
                    if slot is None:
                        slot = np.zeros(len(DIM_NAMES), dtype=np.int32)
                        sym_by[name] = slot
                    for dim in hit_dims:
                        slot[dim_index[dim]] += 1
        records.append(
            {
                "group": group,
                "group_title": info.get("group_title") or group,
                "n": len(rows),
                "codes": codes,
                "dims": dims,
                "sym_n": sym_n,
                "sym_dims": sym_dims,
                "sym_count": sym_count,
                "sym_by": sym_by,
            }
        )
        if seen % 100 == 0:
            print(f"已扫 {seen} 支视频", flush=True)
    return records


def _percentile(samples: list[float]) -> tuple[float, float]:
    if not samples:
        return 0.0, 0.0
    low, high = np.percentile(np.asarray(samples, dtype=np.float64), [2.5, 97.5])
    return float(low), float(high)


def bootstrap_lifts(records: list[dict], *, draws: int = 1000, seed: int = 0) -> dict:
    """点估计与按视频放回的 95% 区间。区间用 2.5% 和 97.5% 分位。"""
    if not records:
        return {
            "draws": draws,
            "seed": seed,
            "videos": 0,
            "code_lifts": [],
            "dimension_lifts": [],
            "symbol_bindings": [],
            "note": "没有有字的视频。",
        }
    rng = np.random.default_rng(seed)
    width = len(records)
    groups = sorted({item["group"] for item in records})
    titles = {item["group"]: item["group_title"] for item in records}
    code_samples = {(group, code): [] for group in groups for code in CODE_NAMES}
    dim_samples = {(group, dim): [] for group in groups for dim in DIM_NAMES}
    point_codes = _code_lifts(records)
    point_dims = _dim_lifts(records)
    names = sorted({name for item in records for name in item["sym_count"]})
    # 只跟踪全量里至少出现 20 次的符号，避免区间文件被偶发名字撑大。
    kept_names = [name for name in names if sum(item["sym_count"].get(name, 0) for item in records) >= 20]
    point_symbols = _symbol_lifts(records, kept_names)
    locked = {name: point["dimension"] for name, point in point_symbols.items()}
    sym_lifts = {name: [] for name in kept_names}
    sym_hold = {name: 0 for name in kept_names}

    for _ in range(draws):
        pick = rng.integers(0, width, size=width)
        chosen = [records[int(index)] for index in pick]
        for key, value in _code_lifts(chosen).items():
            code_samples[key].append(value[0])
        for key, value in _dim_lifts(chosen).items():
            dim_samples[key].append(value[0])
        for name, value in _symbol_lifts(chosen, kept_names, locked=locked).items():
            sym_lifts[name].append(value["lift"])
            if value["lift"] >= 1.3 and value["both"] >= 8:
                sym_hold[name] += 1

    code_rows = []
    for (group, code), (lift, count) in point_codes.items():
        if count < 20 or lift < 1.3:
            continue
        low, high = _percentile(code_samples[(group, code)])
        code_rows.append(
            {
                "group": group,
                "group_title": titles[group],
                "code": code,
                "count": int(count),
                "lift": lift,
                "low": low,
                "high": high,
                "above_one": low >= 1.0,
            }
        )
    code_rows.sort(key=lambda row: row["lift"], reverse=True)

    dim_rows = []
    for (group, dim), (lift, count) in point_dims.items():
        low, high = _percentile(dim_samples[(group, dim)])
        dim_rows.append(
            {
                "group": group,
                "group_title": titles[group],
                "dimension": dim,
                "count": int(count),
                "lift": lift,
                "low": low,
                "high": high,
                "above_one": low >= 1.0,
            }
        )

    sym_rows = []
    for name, point in point_symbols.items():
        low, high = _percentile(sym_lifts[name])
        sym_rows.append(
            {
                "name": name,
                "dimension": point["dimension"],
                "count": point["count"],
                "both": point["both"],
                "lift": point["lift"],
                "low": low,
                "high": high,
                "share_bound": sym_hold[name] / draws if draws else 0.0,
                "bound": bool(point["lift"] >= 1.3 and point["both"] >= 8),
            }
        )
    sym_rows.sort(key=lambda row: (row["bound"], row["lift"]), reverse=True)

    return {
        "draws": draws,
        "seed": seed,
        "videos": len(records),
        "code_lifts": code_rows,
        "dimension_lifts": dim_rows,
        "symbol_bindings": sym_rows,
        "note": (
            "按有字的视频放回重抽样。区间是 2.5% 到 97.5% 分位。"
            "点估计与全量抬升用同一套计数。空池不在抽样框里。"
            "above_one 表示区间下端仍不低于 1。符号的 share_bound 是重抽样里仍绑在同一维、"
            "且倍数不低于 1.3、条数不少于 8 的比例。"
        ),
    }


def _group_sums(records: list[dict]) -> tuple[dict[str, int], dict[str, np.ndarray], dict[str, np.ndarray], int, np.ndarray, np.ndarray]:
    group_n: dict[str, int] = {}
    group_codes: dict[str, np.ndarray] = {}
    group_dims: dict[str, np.ndarray] = {}
    total_n = 0
    total_codes = np.zeros(len(CODE_NAMES), dtype=np.int64)
    total_dims = np.zeros(len(DIM_NAMES), dtype=np.int64)
    for item in records:
        group = item["group"]
        group_n[group] = group_n.get(group, 0) + int(item["n"])
        if group not in group_codes:
            group_codes[group] = np.zeros(len(CODE_NAMES), dtype=np.int64)
            group_dims[group] = np.zeros(len(DIM_NAMES), dtype=np.int64)
        group_codes[group] += item["codes"]
        group_dims[group] += item["dims"]
        total_n += int(item["n"])
        total_codes += item["codes"]
        total_dims += item["dims"]
    return group_n, group_codes, group_dims, total_n, total_codes, total_dims


def _code_lifts(records: list[dict]) -> dict[tuple[str, str], tuple[float, int]]:
    group_n, group_codes, _dims, total_n, total_codes, _total_dims = _group_sums(records)
    found = {}
    for group, codes in group_codes.items():
        base = group_n.get(group) or 1
        for index, code in enumerate(CODE_NAMES):
            count = int(codes[index])
            corpus = (total_codes[index] / total_n) if total_n else 0.0
            rate = count / base
            lift = (rate / corpus) if corpus else 0.0
            found[(group, code)] = (float(lift), count)
    return found


def _dim_lifts(records: list[dict]) -> dict[tuple[str, str], tuple[float, int]]:
    group_n, _codes, group_dims, total_n, _total_codes, total_dims = _group_sums(records)
    found = {}
    for group, dims in group_dims.items():
        base = group_n.get(group) or 1
        for index, dim in enumerate(DIM_NAMES):
            count = int(dims[index])
            corpus = (total_dims[index] / total_n) if total_n else 0.0
            rate = count / base
            lift = (rate / corpus) if corpus else 0.0
            found[(group, dim)] = (float(lift), count)
    return found


def _symbol_lifts(
    records: list[dict],
    names: list[str],
    locked: dict[str, str] | None = None,
) -> dict[str, dict]:
    sym_n = 0
    sym_dims = np.zeros(len(DIM_NAMES), dtype=np.int64)
    counts = {name: 0 for name in names}
    both = {name: np.zeros(len(DIM_NAMES), dtype=np.int64) for name in names}
    for item in records:
        sym_n += int(item["sym_n"])
        sym_dims += item["sym_dims"]
        for name in names:
            counts[name] += int(item["sym_count"].get(name, 0))
            slot = item["sym_by"].get(name)
            if slot is not None:
                both[name] += slot
    found = {}
    for name in names:
        count = counts[name]
        if not count:
            found[name] = {"dimension": "", "count": 0, "both": 0, "lift": 0.0}
            continue
        chosen = locked.get(name) if locked else ""
        lifts = []
        for index, dim in enumerate(DIM_NAMES):
            if dim == "知识认知":
                continue
            if chosen and dim != chosen:
                continue
            rate = both[name][index] / count
            base = (sym_dims[index] / sym_n) if sym_n else 0.0
            lift = (rate / base) if base else 0.0
            lifts.append((float(lift), int(both[name][index]), dim))
        best = max(lifts, key=lambda item: (item[0], item[1])) if lifts else (0.0, 0, "")
        found[name] = {
            "dimension": best[2],
            "count": count,
            "both": best[1],
            "lift": best[0],
        }
    return found


def write_resample(corpus: Path, list_path: Path | None, out: Path, *, draws: int = 1000, seed: int = 0) -> dict:
    records = scan_videos(corpus, list_path)
    report = bootstrap_lifts(records, draws=draws, seed=seed)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
