import json
from pathlib import Path

PUNCT = "！!？?，,。．、；;：:\"'“”‘’「」『』【】（）()[]…~～·. \t"


def normalize(text: str) -> str:
    """去掉空白和标点，让「好耶！」和「好耶」能对上。"""
    raw = "".join((text or "").split())
    return raw.translate(str.maketrans("", "", PUNCT))


def load_lexicon(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    families = []
    for item in data["families"]:
        variants = []
        seen = set()
        for variant in item["variants"]:
            key = normalize(variant)
            if len(key) < 2 or key in seen:
                continue
            seen.add(key)
            variants.append({"text": variant, "key": key})
        variants.sort(key=lambda row: len(row["key"]), reverse=True)
        families.append(
            {
                "id": item["id"],
                "name": item["name"],
                "variants": variants,
            }
        )
    return families


def match_families(text: str, families: list[dict]) -> list[str]:
    """一条弹幕可以同时含有好几句。按词表里的写法做子串匹配。"""
    key = normalize(text)
    if len(key) < 2:
        return []
    found = []
    for family in families:
        for variant in family["variants"]:
            if variant["key"] in key:
                found.append(family["id"])
                break
    return found


def default_lexicon() -> Path:
    return Path(__file__).resolve().parent / "lexicons" / "families.json"
