"""把摘要画成一份离线 HTML。图里没有弹幕原文。"""

from __future__ import annotations

import html
import json
from pathlib import Path

DIM_COLOR = {
    "作品评价": "#9c2b1e",
    "知识认知": "#2457a6",
    "情感认同": "#a15c07",
    "审美鉴赏": "#2f6f62",
    "传播思辨": "#5c3d7a",
    "传承意向": "#8a4b2f",
}


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _num(value) -> str:
    if isinstance(value, float):
        return f"{value:,.3f}"
    return f"{int(value):,}"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _fmt(value, places: int | None = None) -> str:
    if places is not None and isinstance(value, float):
        return f"{value:.{places}f}"
    return _num(value)


def _hbar(
    rows: list[tuple[str, float, str]],
    width: int = 860,
    label_w: int = 132,
    value_w: int = 88,
    suffix: str = "",
    places: int | None = None,
    title: str = "条形图",
    bind: bool = True,
) -> str:
    if not rows:
        return "<p class='empty'>这一项还没有数。</p>"
    peak = max(value for _, value, _ in rows) or 1
    height = 8 + len(rows) * 28
    span = max(40, width - label_w - value_w)
    parts = [
        f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'>",
        f"<title>{_esc(title)}</title>",
    ]
    for index, (label, value, color) in enumerate(rows):
        y = 8 + index * 28
        bar = span * (value / peak)
        shown = _fmt(value, places) + suffix
        opener = f"<g data-code='{_esc(label)}' class='hit'>" if bind else "<g>"
        parts.append(
            opener
            + f"<text x='0' y='{y + 16}' class='lab'>{_esc(label)}</text>"
            f"<rect x='{label_w}' y='{y + 4}' width='{bar:.1f}' height='16' fill='{color}'></rect>"
            f"<text x='{label_w + bar + 8:.1f}' y='{y + 16}' class='val'>{_esc(shown)}</text>"
            f"<title>{_esc(label)} {_esc(shown)}</title></g>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _group_rows(summary: dict) -> list[tuple[str, dict]]:
    groups = summary.get("groups") or {}
    order = ["museum", "classics", "craft", "opera_art", "festival"]
    keys = [key for key in order if key in groups] + [key for key in groups if key not in order]
    return [(key, groups[key]) for key in keys]


def _swatches(items: list[tuple[str, str]]) -> str:
    return "<div class='legend-row'>" + "".join(
        f"<span class='swatch' style='--c:{color}'>{_esc(label)}</span>" for label, color in items
    ) + "</div>"


def _per_10k(summary: dict) -> str:
    danmaku = summary.get("danmaku") or 0
    dims = summary.get("dimensions") or []
    by_dim = summary.get("by_dimension") or {}
    if not danmaku or not dims:
        return "<p class='empty'>还没有弹幕来换算每万条。</p>"
    rows = [
        (dim, by_dim.get(dim, 0) * 10000 / danmaku, DIM_COLOR.get(dim, "#333"))
        for dim in dims
    ]
    return _hbar(rows, places=1, title="每万条弹幕", bind=False)


def _composition(summary: dict) -> str:
    dims = summary.get("dimensions") or []
    rows = [(key, info) for key, info in _group_rows(summary) if sum((info.get("by_dimension") or {}).values())]
    if not rows or not dims:
        return "<p class='empty'>还没有载体上的维度命中。</p>"
    width = 920
    label_w = 132
    bar_w = width - label_w - 16
    height = 12 + len(rows) * 36
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'><title>组内维度构成</title>"]
    for index, (_, info) in enumerate(rows):
        counts = [int((info.get("by_dimension") or {}).get(dim) or 0) for dim in dims]
        total = sum(counts) or 1
        y = 8 + index * 36
        parts.append(f"<text x='0' y='{y + 20}' class='lab'>{_esc(info.get('title') or '')}</text>")
        x = label_w
        for dim, count in zip(dims, counts):
            width_i = bar_w * count / total
            if width_i <= 0:
                continue
            color = DIM_COLOR.get(dim, "#333")
            share = count / total
            parts.append(
                f"<rect x='{x:.1f}' y='{y + 4}' width='{max(width_i, 0.8):.1f}' height='22' fill='{color}'>"
                f"<title>{_esc(info.get('title') or '')} · {_esc(dim)} {share:.1%}</title></rect>"
            )
            if width_i >= 46:
                parts.append(
                    f"<text x='{x + width_i / 2:.1f}' y='{y + 19}' class='onbar' text-anchor='middle'>{share:.0%}</text>"
                )
            x += width_i
    parts.append("</svg>")
    legend = _swatches([(dim, DIM_COLOR.get(dim, "#333")) for dim in dims])
    return legend + "".join(parts)


def _pools(summary: dict) -> str:
    rows = []
    for _, info in _group_rows(summary):
        videos = int(info.get("videos") or 0)
        empty = int(info.get("empty") or 0)
        if videos:
            rows.append((info.get("title") or "", empty, videos - empty))
    if not rows:
        return "<p class='empty'>还没有载体分组。</p>"
    width = 920
    label_w = 132
    value_w = 150
    bar_max = width - label_w - value_w
    height = 8 + len(rows) * 32
    peak = max(empty + live for _, empty, live in rows) or 1
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'><title>有字的池和空池</title>"]
    for index, (title, empty, live) in enumerate(rows):
        y = 8 + index * 32
        live_w = bar_max * live / peak
        empty_w = bar_max * empty / peak
        parts.append(
            f"<text x='0' y='{y + 18}' class='lab'>{_esc(title)}</text>"
            f"<rect x='{label_w}' y='{y + 6}' width='{live_w:.1f}' height='16' fill='#2f6f62'>"
            f"<title>{_esc(title)} 有字 {live}</title></rect>"
            f"<rect x='{label_w + live_w:.1f}' y='{y + 6}' width='{empty_w:.1f}' height='16' fill='#c4b8a5'>"
            f"<title>{_esc(title)} 空池 {empty}</title></rect>"
            f"<text x='{label_w + live_w + empty_w + 8:.1f}' y='{y + 18}' class='val'>{live:,} 有字 / {empty:,} 空</text>"
        )
    parts.append("</svg>")
    legend = _swatches([("有字的当前池", "#2f6f62"), ("当前池为空", "#c4b8a5")])
    return legend + "".join(parts)


def _signatures(summary: dict) -> str:
    rows = []
    for _, info in _group_rows(summary):
        title = info.get("title") or ""
        by_code = info.get("by_code") or {}
        lifts = info.get("code_lift") or {}
        for code, count in by_code.items():
            lift = float(lifts.get(code) or 0)
            if count >= 20 and lift >= 1.3:
                rows.append(
                    (f"{title} · {code}", lift, DIM_COLOR.get(_dim_of(summary, code), "#333"))
                )
    rows.sort(key=lambda item: item[1], reverse=True)
    if not rows:
        return "<p class='empty'>还没有同时达到 20 条、且不低于全库 1.3 倍的二级类。</p>"
    return _hbar(
        rows[:12],
        width=920,
        label_w=248,
        value_w=72,
        places=2,
        suffix=" 倍",
        title="二级类相对抬升",
        bind=False,
    )


def _stay(summary: dict) -> str:
    matrix = summary.get("transitions") or []
    dims = summary.get("dimensions") or []
    if not matrix or not dims or not any(any(row) for row in matrix):
        return "<p class='empty'>还没有不少于 30 条弹幕的片子来看停留。</p>"
    stays = []
    flows = []
    for index, dim in enumerate(dims):
        row = matrix[index] if index < len(matrix) else []
        total = sum(row)
        if total >= 30:
            stays.append((dim, row[index] / total, DIM_COLOR.get(dim, "#333")))
        for target_index, target in enumerate(dims):
            if target_index == index or target_index >= len(row):
                continue
            if row[target_index] >= 8:
                flows.append(
                    (f"{dim} → {target}", row[target_index], DIM_COLOR.get(dim, "#333"))
                )
    flows.sort(key=lambda item: item[1], reverse=True)
    stay_rows = [(label, value * 100, color) for label, value, color in stays]
    stay_chart = _hbar(stay_rows, places=1, suffix="%", title="停留率", bind=False)
    flow_chart = (
        _hbar(flows, width=920, label_w=220, title="换到另一维", bind=False)
        if flows
        else "<p class='empty'>相邻进度里，换到另一维的次数都少于 8。</p>"
    )
    return stay_chart + flow_chart


def _group_words(summary: dict) -> str:
    blocks = []
    for _, info in _group_rows(summary):
        words = info.get("words") or []
        if not words:
            continue
        chips = "".join(
            "<span class='chip'>{gram}<small>z {z:.1f} · {count} 次{videos}</small></span>".format(
                gram=_esc(item["gram"]),
                z=item["z"],
                count=item["count"],
                videos=f" · {item['videos']} 支" if item.get("videos") else "",
            )
            for item in words
        )
        blocks.append(f"<h3>{_esc(info.get('title') or '')}</h3><div class='chips'>{chips}</div>")
    if not blocks:
        return "<p class='empty'>各组残差里还没有明显高于其余组的二字。</p>"
    return "".join(blocks)


def _lines(summary: dict) -> str:
    timeline = summary.get("timeline") or {}
    series = timeline.get("series") or {}
    if not series or not timeline.get("videos"):
        return "<p class='empty'>还没有足够长的片子来画进度曲线。</p>"
    width, height = 860, 280
    left, right, top, bottom = 48, 16, 16, 32
    inner_w = width - left - right
    inner_h = height - top - bottom
    peak = max((max(values) if values else 0) for values in series.values()) or 0.01
    peak = max(peak, 0.05)
    parts = [
        f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'>",
        "<title>视频进度上的维度比例</title>",
    ]
    for tick in range(5):
        y = top + inner_h * (1 - tick / 4)
        parts.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{width - right}' y2='{y:.1f}' class='grid'/>"
            f"<text x='{left - 8}' y='{y + 4:.1f}' class='tick' text-anchor='end'>{peak * tick / 4:.0%}</text>"
        )
    for dim, values in series.items():
        if not values:
            continue
        points = []
        for index, value in enumerate(values):
            x = left + inner_w * (index / max(1, len(values) - 1))
            y = top + inner_h * (1 - value / peak)
            points.append(f"{x:.1f},{y:.1f}")
        color = DIM_COLOR.get(dim, "#333")
        parts.append(
            f"<polyline data-dim='{_esc(dim)}' fill='none' stroke='{color}' stroke-width='2.2' points='{' '.join(points)}'></polyline>"
        )
    for index, label in ((0, "片头"), (len(next(iter(series.values()))) - 1, "片尾")):
        x = left + inner_w * (index / max(1, len(next(iter(series.values()))) - 1))
        parts.append(
            f"<text x='{x:.1f}' y='{height - 8}' class='tick' text-anchor='middle'>{label}</text>"
        )
    parts.append("</svg>")
    legend = "".join(
        f"<button type='button' class='legend' data-dim='{_esc(dim)}' style='--c:{DIM_COLOR.get(dim, '#333')}'>{_esc(dim)}</button>"
        for dim in series
    )
    return f"<div class='legend-row'>{legend}</div>" + "".join(parts)


def _heatmap(summary: dict) -> str:
    groups = summary.get("groups") or {}
    dims = summary.get("dimensions") or []
    rows = [(key, info) for key, info in groups.items() if info.get("danmaku")]
    if not rows or not dims:
        return "<p class='empty'>还没有载体分组。</p>"
    cell_w, cell_h = 92, 36
    label_w = 120
    width = label_w + cell_w * len(dims) + 8
    height = 36 + cell_h * len(rows) + 8
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'><title>载体与维度</title>"]
    for index, dim in enumerate(dims):
        x = label_w + index * cell_w
        parts.append(
            f"<text x='{x + cell_w / 2:.1f}' y='22' class='tick' text-anchor='middle'>{_esc(dim)}</text>"
        )
    for r, (_, info) in enumerate(rows):
        y = 32 + r * cell_h
        parts.append(f"<text x='0' y='{y + 22}' class='lab'>{_esc(info.get('title') or '')}</text>")
        rates = info.get("dimension_rate") or {}
        for c, dim in enumerate(dims):
            rate = float(rates.get(dim) or 0)
            color = DIM_COLOR.get(dim, "#333")
            opacity = 0.08 + 0.92 * min(1, rate / 0.35)
            x = label_w + c * cell_w
            parts.append(
                f"<rect x='{x + 4}' y='{y + 4}' width='{cell_w - 8}' height='{cell_h - 8}' fill='{color}' fill-opacity='{opacity:.3f}'></rect>"
                f"<text x='{x + cell_w / 2:.1f}' y='{y + 24}' class='cell' text-anchor='middle'>{rate:.0%}</text>"
            )
    parts.append("</svg>")
    return "".join(parts)


def _matrix(summary: dict) -> str:
    codes = summary.get("codes") or []
    co = summary.get("cooccurrence") or []
    counts = summary.get("by_code") or {}
    if not codes or not co:
        return "<p class='empty'>还没有共现。</p>"
    cell = 28
    left = 108
    width = left + cell * len(codes) + 8
    height = 108 + cell * len(codes) + 8
    parts = [
        f"<svg viewBox='0 0 {width} {height}' class='chart matrix' role='img'><title>类别共现</title>"
    ]
    for index, code in enumerate(codes):
        x = left + index * cell + cell / 2
        y = left + index * cell + 16
        parts.append(
            f"<text x='{x:.1f}' y='100' class='tiny' text-anchor='end' transform='rotate(-55 {x:.1f} 100)'>{_esc(code)}</text>"
            f"<text x='100' y='{y:.1f}' class='tiny' text-anchor='end'>{_esc(code)}</text>"
        )
    for i, left_code in enumerate(codes):
        for j, right_code in enumerate(codes):
            if i == j:
                value = 1.0 if counts.get(left_code) else 0.0
            else:
                both = co[i][j] if i < len(co) and j < len(co[i]) else 0
                union = counts.get(left_code, 0) + counts.get(right_code, 0) - both
                value = both / union if union else 0.0
            color = DIM_COLOR.get(_dim_of(summary, left_code), "#333")
            x = left + j * cell
            y = 108 + i * cell
            parts.append(
                f"<rect x='{x + 1}' y='{y + 1}' width='{cell - 2}' height='{cell - 2}' fill='{color}' fill-opacity='{0.06 + 0.94 * value:.3f}'>"
                f"<title>{_esc(left_code)} × {_esc(right_code)} {value:.2f}</title></rect>"
            )
    parts.append("</svg>")
    return "".join(parts)


def _dim_of(summary: dict, code: str) -> str:
    for dim, codes in _pairs(summary):
        if code in codes:
            return dim
    return "作品评价"


def _pairs(summary: dict) -> list[tuple[str, list[str]]]:
    if summary.get("code_groups"):
        return [(dim, summary["code_groups"][dim]) for dim in summary["dimensions"] if dim in summary["code_groups"]]
    sizes = [3, 3, 3, 2, 3, 3]
    codes = list(summary.get("codes") or [])
    dims = list(summary.get("dimensions") or [])
    pairs = []
    cursor = 0
    for dim, size in zip(dims, sizes):
        pairs.append((dim, codes[cursor : cursor + size]))
        cursor += size
    return pairs


def _lift(summary: dict) -> str:
    groups = summary.get("groups") or {}
    dims = summary.get("dimensions") or []
    rows = [(key, info) for key, info in groups.items() if info.get("danmaku") and info.get("lift")]
    if not rows or not dims:
        return "<p class='empty'>还没有足够的载体来算相对抬升。</p>"
    cell_w, cell_h = 92, 36
    label_w = 120
    width = label_w + cell_w * len(dims) + 8
    height = 36 + cell_h * len(rows) + 8
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'><title>相对抬升</title>"]
    for index, dim in enumerate(dims):
        x = label_w + index * cell_w
        parts.append(
            f"<text x='{x + cell_w / 2:.1f}' y='22' class='tick' text-anchor='middle'>{_esc(dim)}</text>"
        )
    for r, (_, info) in enumerate(rows):
        y = 32 + r * cell_h
        parts.append(f"<text x='0' y='{y + 22}' class='lab'>{_esc(info.get('title') or '')}</text>")
        lifts = info.get("lift") or {}
        for c, dim in enumerate(dims):
            lift = float(lifts.get(dim) or 0)
            color = "#9c2b1e" if lift >= 1 else "#2457a6"
            opacity = 0.08 + 0.92 * min(1, abs(lift - 1) / 1.2) if lift else 0.05
            x = label_w + c * cell_w
            parts.append(
                f"<rect x='{x + 4}' y='{y + 4}' width='{cell_w - 8}' height='{cell_h - 8}' fill='{color}' fill-opacity='{opacity:.3f}'>"
                f"<title>{_esc(info.get('title') or '')} · {_esc(dim)} {lift:.2f} 倍</title></rect>"
                f"<text x='{x + cell_w / 2:.1f}' y='{y + 24}' class='cell' text-anchor='middle'>{lift:.2f}</text>"
            )
    parts.append("</svg>")
    return "".join(parts)


def _share_bars(rows: list[tuple[str, float, str]]) -> str:
    if not rows:
        return "<p class='empty'>还没有跨视频的集中度。</p>"
    width = 860
    label_w = 132
    height = 8 + len(rows) * 28
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'><title>头部视频占比</title>"]
    for index, (label, value, color) in enumerate(rows):
        y = 8 + index * 28
        bar = (width - label_w - 88) * min(1, value)
        parts.append(
            f"<text x='0' y='{y + 16}' class='lab'>{_esc(label)}</text>"
            f"<rect x='{label_w}' y='{y + 4}' width='{bar:.1f}' height='16' fill='{color}'></rect>"
            f"<text x='{label_w + bar + 8:.1f}' y='{y + 16}' class='val'>{value:.0%}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


MODE_NAME = {
    "1": "滚动",
    "4": "底部",
    "5": "顶部",
    "6": "逆向",
    "7": "高级",
    "8": "代码",
    "9": "BAS",
}


def _modes(summary: dict) -> str:
    modes = (summary.get("modes") or {}).get("all") or {}
    if not modes:
        return "<p class='empty'>这些弹幕没有模式字段。</p>"
    rows = []
    for key, count in sorted(modes.items(), key=lambda item: -item[1]):
        rows.append((MODE_NAME.get(key, f"模式 {key}"), count, "#8a4b2f"))
    return _hbar(rows)


def _hours(summary: dict) -> str:
    hours = summary.get("hours") or {}
    coded = hours.get("coded") or []
    other = hours.get("other") or []
    if len(coded) != 24 or not (any(coded) or any(other)):
        return "<p class='empty'>这些弹幕没有发送时间。</p>"

    def norm(values: list[int]) -> list[float]:
        total = sum(values) or 1
        return [value / total for value in values]

    series = (("已编码", norm(coded), "#9c2b1e"), ("未编码", norm(other), "#2457a6"))
    width, height = 860, 240
    left, right, top, bottom = 48, 16, 16, 28
    inner_w = width - left - right
    inner_h = height - top - bottom
    peak = max(max(values) for _, values, _ in series) or 0.01
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'><title>发送时刻</title>"]
    for tick in range(4):
        y = top + inner_h * (1 - tick / 3)
        parts.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{width - right}' y2='{y:.1f}' class='grid'/>"
        )
    for _label, values, color in series:
        points = []
        for index, value in enumerate(values):
            x = left + inner_w * (index / 23)
            y = top + inner_h * (1 - value / peak)
            points.append(f"{x:.1f},{y:.1f}")
        parts.append(
            f"<polyline fill='none' stroke='{color}' stroke-width='2.2' points='{' '.join(points)}'></polyline>"
        )
    for hour in (0, 6, 12, 18, 23):
        x = left + inner_w * (hour / 23)
        parts.append(
            f"<text x='{x:.1f}' y='{height - 8}' class='tick' text-anchor='middle'>{hour}时</text>"
        )
    parts.append("</svg>")
    legend = (
        "<div class='legend-row'>"
        "<span class='legend' style='--c:#9c2b1e'>已编码</span>"
        "<span class='legend' style='--c:#2457a6'>未编码</span>"
        "</div>"
    )
    return legend + "".join(parts)


def _transitions(summary: dict) -> str:
    matrix = summary.get("transitions") or []
    dims = summary.get("dimensions") or []
    if not matrix or not any(any(row) for row in matrix):
        return "<p class='empty'>还没有不少于 30 条弹幕的片子来看维度怎么接上。</p>"
    cell_w, cell_h = 108, 36
    label_w = 108
    width = label_w + cell_w * len(dims) + 8
    height = 36 + cell_h * len(dims) + 8
    peak = max(max(row) for row in matrix) or 1
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'><title>维度承接</title>"]
    for index, dim in enumerate(dims):
        x = label_w + index * cell_w
        parts.append(
            f"<text x='{x + cell_w / 2:.1f}' y='22' class='tick' text-anchor='middle'>{_esc(dim)}</text>"
        )
    for r, dim in enumerate(dims):
        y = 32 + r * cell_h
        parts.append(f"<text x='0' y='{y + 22}' class='lab'>{_esc(dim)}</text>")
        for c, _target in enumerate(dims):
            value = matrix[r][c] if r < len(matrix) and c < len(matrix[r]) else 0
            color = DIM_COLOR.get(dim, "#333")
            opacity = 0.06 + 0.94 * (value / peak)
            x = label_w + c * cell_w
            parts.append(
                f"<rect x='{x + 4}' y='{y + 4}' width='{cell_w - 8}' height='{cell_h - 8}' fill='{color}' fill-opacity='{opacity:.3f}'></rect>"
                f"<text x='{x + cell_w / 2:.1f}' y='{y + 24}' class='cell' text-anchor='middle'>{value}</text>"
            )
    parts.append("</svg>")
    return "".join(parts)


def _pmi(summary: dict) -> str:
    codes = summary.get("codes") or []
    matrix = summary.get("pmi") or []
    if not codes or not matrix or not any(any(row) for row in matrix):
        return "<p class='empty'>还没有足够的共现来算点互信息。</p>"
    cell = 28
    left = 108
    width = left + cell * len(codes) + 8
    height = 108 + cell * len(codes) + 8
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart matrix' role='img'><title>点互信息</title>"]
    for index, code in enumerate(codes):
        x = left + index * cell + cell / 2
        y = left + index * cell + 16
        parts.append(
            f"<text x='{x:.1f}' y='100' class='tiny' text-anchor='end' transform='rotate(-55 {x:.1f} 100)'>{_esc(code)}</text>"
            f"<text x='100' y='{y:.1f}' class='tiny' text-anchor='end'>{_esc(code)}</text>"
        )
    for i, left_code in enumerate(codes):
        for j, right_code in enumerate(codes):
            value = matrix[i][j] if i < len(matrix) and j < len(matrix[i]) else 0.0
            color = "#9c2b1e" if value >= 0 else "#2457a6"
            opacity = 0.05 + 0.95 * min(1, abs(value) / 1.5)
            x = left + j * cell
            y = 108 + i * cell
            parts.append(
                f"<rect x='{x + 1}' y='{y + 1}' width='{cell - 2}' height='{cell - 2}' fill='{color}' fill-opacity='{opacity:.3f}'>"
                f"<title>{_esc(left_code)} × {_esc(right_code)} PMI {value:.2f}</title></rect>"
            )
    parts.append("</svg>")
    return "".join(parts)


def _symbol_dims(summary: dict) -> str:
    table = summary.get("symbol_dimension") or {}
    dims = summary.get("dimensions") or []
    if not table or not dims:
        return ""
    rows = sorted(table.items(), key=lambda item: -sum(item[1].values()))
    cell_w, cell_h = 92, 36
    label_w = 108
    width = label_w + cell_w * len(dims) + 8
    height = 36 + cell_h * len(rows) + 8
    peak = max((max(counts.values()) if counts else 0) for _, counts in rows) or 1
    parts = [f"<svg viewBox='0 0 {width} {height}' class='chart' role='img'><title>符号与维度</title>"]
    for index, dim in enumerate(dims):
        x = label_w + index * cell_w
        parts.append(
            f"<text x='{x + cell_w / 2:.1f}' y='22' class='tick' text-anchor='middle'>{_esc(dim)}</text>"
        )
    for r, (category, counts) in enumerate(rows):
        y = 32 + r * cell_h
        parts.append(f"<text x='0' y='{y + 22}' class='lab'>{_esc(category)}</text>")
        for c, dim in enumerate(dims):
            value = int(counts.get(dim) or 0)
            color = DIM_COLOR.get(dim, "#333")
            opacity = 0.06 + 0.94 * (value / peak)
            x = label_w + c * cell_w
            parts.append(
                f"<rect x='{x + 4}' y='{y + 4}' width='{cell_w - 8}' height='{cell_h - 8}' fill='{color}' fill-opacity='{opacity:.3f}'></rect>"
                f"<text x='{x + cell_w / 2:.1f}' y='{y + 24}' class='cell' text-anchor='middle'>{value}</text>"
            )
    parts.append("</svg>")
    return "".join(parts)


def render(summary: dict) -> str:
    dims = summary.get("dimensions") or []
    codes = summary.get("codes") or []
    by_dim = summary.get("by_dimension") or {}
    by_code = summary.get("by_code") or {}
    descriptions = summary.get("descriptions") or {}
    dim_rows = [(dim, by_dim.get(dim, 0), DIM_COLOR.get(dim, "#333")) for dim in dims]
    code_rows = []
    for dim, members in _pairs(summary):
        for code in members:
            code_rows.append((code, by_code.get(code, 0), DIM_COLOR.get(dim, "#333")))
    symbol_rows = [
        (item["name"], item["count"], "#2457a6")
        for item in (summary.get("symbols") or {}).get("top") or []
    ]
    findings = "".join(f"<li>{_esc(line)}</li>" for line in summary.get("findings") or [])
    defs = "".join(
        f"<dt data-code='{_esc(code)}'>{_esc(code)}</dt><dd>{_esc(descriptions.get(code, ''))}</dd>"
        for code in codes
    )
    rules = summary.get("rules_core") or {}
    hard = summary.get("rules_hard") or {}
    model_core = summary.get("model_core") or {}
    agree = summary.get("model_agreement") or {}
    model_only = sum((agree.get("model_only") or {}).values()) if agree else 0
    rule_only = sum((agree.get("rule_only") or {}).values()) if agree else 0
    metric_rows = [
        ("规则 · 核心句精确匹配", _pct(rules["exact_match"]) if rules else "—"),
        ("规则 · 核心句宏平均 F1", f"{rules['macro_f1']:.3f}" if rules else "—"),
        ("规则 · 难句召回（宏平均 F1）", f"{hard['macro_f1']:.3f}" if hard else "—"),
        ("字符模型 · 核心句宏平均 F1", f"{model_core['macro_f1']:.3f}" if model_core else "—"),
        ("字符模型 · 对照银标宏平均 F1", f"{agree['macro_f1']:.3f}" if agree else "尚未采样"),
        ("银标抽样 · 模型多标次数", f"{model_only:,}" if agree else "尚未采样"),
        ("银标抽样 · 规则有而模型无", f"{rule_only:,}" if agree else "尚未采样"),
    ]
    metric_html = "".join(
        f"<div class='stat'><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>"
        for label, value in metric_rows
    )
    bursts = summary.get("bursts") or {}
    burst_rows = sorted(
        ((code, bursts.get(code, 0), DIM_COLOR.get(_dim_of(summary, code), "#333")) for code in codes),
        key=lambda item: item[1],
        reverse=True,
    )
    burst_rows = [row for row in burst_rows if row[1]]
    concentration = summary.get("concentration") or {}
    conc_rows = []
    for dim, members in _pairs(summary):
        for code in members:
            info = concentration.get(code) or {}
            if info.get("videos"):
                conc_rows.append((code, float(info.get("top_share") or 0), DIM_COLOR.get(dim, "#333")))
    conc_rows.sort(key=lambda item: item[1], reverse=True)
    residue = summary.get("residue_bigrams") or []
    chips = "".join(
        f"<span class='chip'>{_esc(item['gram'])}<small>{item['count']}</small></span>" for item in residue
    ) or "<p class='empty'>残差还没有聚出来。</p>"
    categories = (summary.get("symbols") or {}).get("by_category") or {}
    cat_rows = [(name, count, "#2f6f62") for name, count in sorted(categories.items(), key=lambda item: -item[1])]
    length = summary.get("length_coverage") or {}
    length_note = ""
    if length:
        bits = []
        for key, label in (("le4", "4 字及以内"), ("gt4", "4 字以上")):
            slot = length.get(key) or {}
            n = slot.get("n") or 0
            coded = slot.get("coded") or 0
            rate = coded / n if n else 0
            bits.append(f"{label} {coded:,}/{n:,}（{_pct(rate)}）")
        length_note = "；".join(bits)
    payload = json.dumps(
        {"descriptions": descriptions, "by_code": by_code},
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    pending = summary.get("pending") or 0
    pending_note = f"<p class='warn'>清单里还有 {pending} 支视频没落盘，这页只画已经读到的部分。</p>" if pending else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>文脉 · 传统文化弹幕六维</title>
<style>
:root {{ color-scheme: light; --ink:#1c1915; --paper:#f3efe6; --line:#d9d0c1; --muted:#5e574c; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.55 "Segoe UI","PingFang SC","Noto Sans SC",sans-serif; }}
main {{ max-width:1120px; margin:0 auto; padding:32px 20px 80px; }}
header h1 {{ font: 600 48px/1.05 "Iowan Old Style","Palatino Linotype","Songti SC","Noto Serif SC",serif; margin:0 0 8px; }}
.kicker {{ letter-spacing:.18em; font-size:12px; color:var(--muted); margin:0 0 12px; }}
.lead {{ max-width:68ch; color:var(--muted); }}
.stats, .metrics {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin:20px 0; }}
.stat {{ background:#fffdf8; border:1px solid var(--line); padding:12px 14px; }}
.stat span {{ display:block; color:var(--muted); font-size:13px; }}
.stat strong {{ font: 600 28px/1.2 "Iowan Old Style","Palatino Linotype",serif; }}
section {{ margin-top:36px; }}
h2 {{ font:600 22px/1.3 "Iowan Old Style","Palatino Linotype","Songti SC",serif; margin:0 0 8px; }}
h3 {{ font:600 16px/1.3 "Songti SC","Noto Serif SC",serif; margin:14px 0 6px; }}
.note {{ color:var(--muted); margin:0 0 12px; max-width:78ch; }}
.chart {{ width:100%; height:auto; background:#fffdf8; border:1px solid var(--line); }}
.lab {{ font-size:13px; fill:var(--ink); }}
.val, .tick, .cell, .tiny {{ font-size:12px; fill:var(--muted); }}
.tiny {{ font-size:10px; }}
.grid {{ stroke:var(--line); stroke-width:1; }}
.legend-row {{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 8px; }}
.legend {{ border:1px solid var(--line); background:#fffdf8; padding:4px 10px; cursor:pointer; font:inherit; }}
.legend::before, .swatch::before {{ content:""; display:inline-block; width:10px; height:10px; background:var(--c); margin-right:6px; }}
.swatch {{ border:1px solid var(--line); background:#fffdf8; padding:4px 10px; }}
.onbar {{ font-size:11px; fill:#fffdf8; }}
.legend.off {{ opacity:.35; }}
.findings {{ padding-left:1.2em; }}
dl {{ display:grid; grid-template-columns:8em 1fr; gap:6px 12px; margin:0; }}
dt {{ font-weight:600; cursor:pointer; }}
dd {{ margin:0; color:var(--muted); }}
#focus {{ background:#fffdf8; border-left:4px solid #9c2b1e; padding:10px 12px; min-height:3em; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
.chip {{ background:#fffdf8; border:1px solid var(--line); padding:4px 8px; }}
.chip small {{ color:var(--muted); margin-left:6px; }}
.warn {{ background:#fff4e8; border:1px solid #e2c39a; padding:8px 12px; }}
footer {{ color:var(--muted); font-size:13px; margin-top:28px; }}
.hit {{ cursor:pointer; }}
.empty {{ color:var(--muted); }}
</style>
</head>
<body>
<main>
<header>
<p class="kicker">文脉 · 传统文化弹幕六维读法</p>
<h1>观众在热门片子里怎样接收传统</h1>
<p class="lead">六维十七类来自这次的码表。规则负责可解释的编码，字符模型用来对照规则还盖不住的说法。进度曲线按视频等权，避免一条超长片子淹没其他片子。</p>
{pending_note}
</header>
<div class="stats">
<div class="stat"><span>已读视频</span><strong>{summary.get('videos', 0):,}</strong></div>
<div class="stat"><span>当前池为空</span><strong>{summary.get('empty_pools', 0):,}</strong></div>
<div class="stat"><span>弹幕</span><strong>{summary.get('danmaku', 0):,}</strong></div>
<div class="stat"><span>至少落入一类</span><strong>{_pct(summary.get('coded_rate') or 0)}</strong></div>
<div class="stat"><span>多类并中</span><strong>{_pct(summary.get('multi_rate') or 0)}</strong></div>
</div>
<section>
<h2>读下来的几句</h2>
<ol class="findings">{findings}</ol>
</section>
<section id="density">
<h2>每万条弹幕里的六维</h2>
<p class="note">绝对条数会让知识认知占满横轴，传播思辨只剩一条缝。这里把每一维换成每万条弹幕里出现多少次，稀有的维度才能和常见的维度放在同一张图里读。</p>
{_per_10k(summary)}
</section>
<section id="composition">
<h2>各组把编码用在哪里</h2>
<p class="note">每一条横条内部加总为 100%，分母是该组六个维度的命中次数，不是该组弹幕条数。一条弹幕可以同时落入多维，所以这个构成回答的是「编码落在哪些维」，不是「有多少条被编码」。</p>
{_composition(summary)}
</section>
<section id="pools">
<h2>哪些载体还拉得到弹幕</h2>
<p class="note">绿色是当前公开池里有字的视频，灰色是清单在热门线上、播放器里现在为空的视频。空池是拉到了，不是漏拉。</p>
{_pools(summary)}
</section>
<section id="signatures">
<h2>哪一类在哪一组更密</h2>
<p class="note">只画该组至少 20 条、且不低于全库 1.3 倍的二级类。倍数是该组里这一类占弹幕的比例，除以全库同一比例。读的时候和绝对条数一起看，避免小样本把倍数抬得很高。</p>
{_signatures(summary)}
</section>
<section id="stay">
<h2>停留与换维</h2>
<p class="note">停留率是相邻进度里，下一格仍然是同一维的比例，只画这一维的相邻次数不少于 30 的维度。下面只画换到另一维、且不少于 8 次的交接。知识认知停在原地时，对角线会很长；这里把「停住」和「交到别的维」拆开。</p>
{_stay(summary)}
</section>
<section id="words">
<h2>各组没被码表盖住的用词</h2>
<p class="note">从未编码、也不是纯笑声的句子里抽二字，再看某一组比其余组高多少个标准误。功能词已去掉。z 大于 2、该组至少 12 次、至少出现在 8 支视频里，并且单支视频不超过一半，才留下。一支片子反复刷的口令不会占满这一组。这是两组比例差，不是主题模型，也不把这些词补进十七类。</p>
{_group_words(summary)}
</section>
<section>
<h2>一级维度</h2>
<p class="note">一条弹幕只要命中该维下的任一二级类，这一维就记 1 次。六个数相加可以大于已编码条数。</p>
{_hbar(dim_rows)}
</section>
<section>
<h2>十七个二级类</h2>
<p class="note">点一条可以在下面看到它的定义。颜色跟所属的一级维度相同。</p>
<div id="focus">点一条类别，这里会写出它的定义和计数。</div>
{_hbar(code_rows)}
</section>
<section>
<h2>载体分组</h2>
<p class="note">格子里是该类占该组全部弹幕的比例，不是占已编码弹幕的比例。颜色越深，这种接收越常见。</p>
{_heatmap(summary)}
</section>
<section>
<h2>相对抬升</h2>
<p class="note">格子是该组比例除以全库比例。1 表示和全库一样。高于 1 用朱色，低于 1 用青色。某一组弹幕很少时，倍数会抖，所以读的时候要同时看上一张的绝对比例。</p>
{_lift(summary)}
</section>
<section>
<h2>是不是被一支片子带起来</h2>
<p class="note">条形是这一类里，贡献最多的一支视频占了多少。接近一整条，就说明这个数主要来自头部片子，不能直接当成所有热门视频的共性。HHI 写在摘要里，页面只画头部占比。</p>
{_share_bars(conc_rows[:12])}
</section>
<section>
<h2>片内维度怎么接上</h2>
<p class="note">不少于 30 条弹幕的片子，按 20 段进度看哪一维最多，再数相邻两段的承接。行是前一段，列是下一段。对角线高，表示这一维会在片子里连着出现。</p>
{_transitions(summary)}
</section>
<section>
<h2>从片头到片尾</h2>
<p class="note">每条线是：在这个进度上，弹幕落入该维度的比例，再对片子取平均。只统计不少于 30 条弹幕的片子，避免极短视频把曲线拉歪。点图例可以只留一条线。</p>
{_lines(summary)}
</section>
<section>
<h2>文化符号</h2>
<p class="note">点名器物、技艺、典籍、民俗、书画戏曲、文物遗址或人物。长名称优先，所以「清明上河图」不会被当成「清明」，「《大学》」也不会被学校名称里的「大学」带走。单独的「大学」「尚书」不收，避免把大学校名和兵部尚书算进典籍。</p>
{_hbar(cat_rows)}
{_hbar(symbol_rows[:16])}
{_symbol_dims(summary)}
</section>
<section>
<h2>类与类一起出现</h2>
<p class="note">对角是该类自己。其余格子是 Jaccard：两类同时出现的条数，除以至少出现其中一类的条数。</p>
{_matrix(summary)}
</section>
<section>
<h2>一起出现得比偶然更多</h2>
<p class="note">点互信息看的是「两类一起出现」是否高于各自单独出现的乘积。朱色是高于偶然，青色是低于偶然。它不代替 Jaccard：很稀有的两类只要经常绑在一起，这里也会很深。</p>
{_pmi(summary)}
</section>
<section>
<h2>弹幕形态和发送时刻</h2>
<p class="note">形态是播放器里的滚动、顶部或底部。时刻按东八区，两条线各自归一，比较的是形状，不是谁的条数更多。</p>
{_modes(summary)}
{_hours(summary)}
</section>
<section>
<h2>疑问旁边有没有补证，以及突发</h2>
<p class="note">知识疑问若与之后 5 秒内的知识补证落在同一时间窗，记一次邻近。突发看的是单个视频内部，不是把所有片子叠成一条。</p>
<p>时间窗内的知识疑问：<strong>{summary.get('qa_questions', 0):,}</strong> 条。未编码里的笑声或气氛：<strong>{_pct(summary.get('laugh_rate') or 0)}</strong>。长度：{_esc(length_note) or "—"}</p>
{_hbar(burst_rows[:12])}
</section>
<section>
<h2>码表没盖住的字</h2>
<p class="note">只从未编码、也不是纯笑声的句子里抽二字。用来看码表还缺什么，不是另一套主题模型。</p>
<div class="chips">{chips}</div>
</section>
<section>
<h2>规则和字符模型</h2>
<p class="note">核心句和难句都是团队自写的，用来锁操作化定义，并公开规则盖不住的说法。真实弹幕上的模型分数只是在对照规则银标。</p>
<div class="metrics">{metric_html}</div>
</section>
<section>
<h2>十七类定义</h2>
<dl>{defs}</dl>
</section>
<footer>
<p>{_esc(summary.get('rights') or '')}</p>
<p>作品评价看创作质量，观看体验看加载、字幕和时长，两者分开。知识性纠错进知识补证，不进制作诟病，除非句子同时在说制作。</p>
</footer>
</main>
<script>
const DATA = {payload};
const focus = document.getElementById("focus");
function show(code) {{
  const text = (DATA.descriptions && DATA.descriptions[code]) || "";
  const count = DATA.by_code ? DATA.by_code[code] : "";
  focus.textContent = code + "：" + text + (count === "" || count === undefined ? "" : " 计数 " + count + "。");
}}
document.querySelectorAll("[data-code]").forEach((node) => {{
  node.addEventListener("click", () => show(node.getAttribute("data-code")));
}});
document.querySelectorAll(".legend").forEach((button) => {{
  button.addEventListener("click", () => {{
    const dim = button.getAttribute("data-dim");
    const lines = [...document.querySelectorAll("polyline[data-dim]")];
    const active = lines.filter((line) => line.getAttribute("data-dim") === dim);
    const solo = active.length && active.every((line) => line.style.opacity !== "0.15") && lines.some((line) => line.style.opacity === "0.15");
    lines.forEach((line) => {{
      const on = line.getAttribute("data-dim") === dim;
      line.style.opacity = solo ? "1" : (on ? "1" : "0.15");
    }});
    document.querySelectorAll(".legend").forEach((item) => {{
      item.classList.toggle("off", !solo && item.getAttribute("data-dim") !== dim);
    }});
    if (solo) document.querySelectorAll(".legend").forEach((item) => item.classList.remove("off"));
  }});
}});
</script>
</body>
</html>
"""


def render_file(summary_path: Path, out_path: Path) -> None:
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    Path(out_path).write_text(render(summary), encoding="utf-8")
