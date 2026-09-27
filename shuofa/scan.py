import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

from shuofa.label import collection_name, judge
from shuofa.peak import locate
from shuofa.textutil import match_families, normalize


def iter_collection_dirs(root: Path) -> list[tuple[str, Path]]:
    found = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and any(path.glob("*.meta.json")):
            found.append((path.name, path))
    return found


def video_files(collection_dir: Path) -> list[tuple[Path, Path]]:
    pairs = []
    for meta_path in sorted(collection_dir.glob("*.meta.json")):
        gz_path = meta_path.with_name(meta_path.name.replace(".meta.json", ".jsonl.gz"))
        if gz_path.exists():
            pairs.append((meta_path, gz_path))
    return pairs


def read_meta(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def duration_ms(meta: dict) -> int | None:
    total = 0.0
    seen = False
    for part in meta.get("parts") or []:
        duration = part.get("duration")
        if isinstance(duration, (int, float)):
            total += float(duration)
            seen = True
        elif isinstance(duration, str) and ":" in duration:
            pieces = duration.split(":")
            if all(piece.isdigit() for piece in pieces):
                seconds = 0
                for piece in pieces:
                    seconds = seconds * 60 + int(piece)
                total += seconds
                seen = True
    if not seen:
        return None
    return int(total * 1000)


def chosen_forms(
    counter: Counter,
    display: dict[str, str],
    variant_keys: list[str],
    limit: int = 6,
) -> list[dict]:
    """留下词表那一句本身，以及只多出几个字的写法。顺带引用它的长评论不写入。"""

    def keep(key: str, count: int) -> bool:
        if count >= 5 and len(key) <= 18:
            return True
        for variant in variant_keys:
            if not variant or variant not in key:
                continue
            if key.replace(variant, "") == "":
                return True
            if len(key) - len(variant) <= 4:
                return True
        return False

    picked = []
    for key, count in counter.most_common():
        if keep(key, count):
            picked.append({"text": display.get(key, key), "count": count})
        if len(picked) >= limit:
            break
    if picked:
        return picked
    return [
        {"text": display.get(key, key), "count": count}
        for key, count in counter.most_common(3)
    ]


def scan_circles(root: Path, families: list[dict]) -> dict:
    """五套放在一起，算每一句在多少比例的视频里出现过。"""
    name_of = {family["id"]: family["name"] for family in families}
    hits: dict[str, dict[str, int]] = {family["id"]: defaultdict(int) for family in families}
    totals: dict[str, int] = {}
    forms: dict[str, Counter] = {family["id"]: Counter() for family in families}
    display: dict[str, dict[str, str]] = {family["id"]: {} for family in families}

    for collection_id, collection_dir in iter_collection_dirs(root):
        pairs = video_files(collection_dir)
        totals[collection_id] = len(pairs)
        for _meta_path, gz_path in pairs:
            seen: set[str] = set()
            with gzip.open(gz_path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    item = json.loads(line)
                    content = item.get("content") or ""
                    matched = match_families(content, families)
                    if not matched:
                        continue
                    key = normalize(content)
                    shown = "".join(content.split())
                    for family_id in matched:
                        seen.add(family_id)
                        forms[family_id][key] += 1
                        previous = display[family_id].get(key)
                        if previous is None or len(shown) < len(previous):
                            display[family_id][key] = shown
            for family_id in seen:
                hits[family_id][collection_id] += 1

    families_out = []
    for family in families:
        family_id = family["id"]
        rates = {}
        counts = {}
        for collection_id, total in totals.items():
            hit = hits[family_id].get(collection_id, 0)
            counts[collection_id] = {"hit": hit, "total": total}
            rates[collection_id] = (hit / total) if total else 0.0
        decision = judge(rates)
        variant_keys = [variant["key"] for variant in family["variants"]]
        top_forms = chosen_forms(forms[family_id], display[family_id], variant_keys)
        families_out.append(
            {
                "id": family_id,
                "name": name_of[family_id],
                "label": decision["label"],
                "home": decision["home"],
                "home_name": collection_name(decision["home"]) if decision["home"] else None,
                "rates": {
                    collection_id: {
                        "hit": counts[collection_id]["hit"],
                        "total": counts[collection_id]["total"],
                        "rate": round(rates[collection_id], 4),
                        "name": collection_name(collection_id),
                    }
                    for collection_id in totals
                },
                "forms": top_forms,
            }
        )
    return {"collections": totals, "families": families_out}


def scan_video(gz_path: Path, families: list[dict], circle: dict | None) -> dict:
    by_id = {family["id"]: family["name"] for family in families}
    progress: dict[str, list] = defaultdict(list)
    form_counts: dict[str, Counter] = defaultdict(Counter)
    form_text: dict[str, dict[str, str]] = defaultdict(dict)
    with gzip.open(gz_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            content = item.get("content") or ""
            matched = match_families(content, families)
            if not matched:
                continue
            key = normalize(content)
            shown = "".join(content.split())
            for family_id in matched:
                progress[family_id].append(item.get("progress_ms"))
                form_counts[family_id][key] += 1
                previous = form_text[family_id].get(key)
                if previous is None or len(shown) < len(previous):
                    form_text[family_id][key] = shown

    circle_by_id = {}
    if circle:
        circle_by_id = {row["id"]: row for row in circle.get("families", [])}

    rows = []
    for family_id, points in progress.items():
        circle_row = circle_by_id.get(family_id, {})
        variant_keys = [
            variant["key"]
            for family in families
            if family["id"] == family_id
            for variant in family["variants"]
        ]
        forms = chosen_forms(form_counts[family_id], form_text[family_id], variant_keys)
        rows.append(
            {
                "id": family_id,
                "name": by_id.get(family_id, family_id),
                "count": sum(form_counts[family_id].values()),
                "peak": locate([p for p in points if isinstance(p, int)]),
                "forms": forms,
                "label": circle_row.get("label"),
                "home_name": circle_row.get("home_name"),
                "rates": circle_row.get("rates"),
            }
        )
    rows.sort(key=lambda row: row["count"], reverse=True)
    return {"rows": rows}
