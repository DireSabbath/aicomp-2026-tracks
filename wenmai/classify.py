"""把一条弹幕标成零个或多个二级类。"""

from __future__ import annotations

import re

from wenmai.codebook import (
    ASPECTS,
    CODE_NAMES,
    COMPARE_LEFT,
    COMPARE_RIGHT,
    PHRASES,
    POSITIVE,
    PRODUCTION_BLOCK,
    SUBTITLE_PRAISE,
    SYMBOLS,
)

_SYMBOLS = sorted(SYMBOLS, key=lambda item: len(item[0]), reverse=True)
_COMPARE = re.compile(
    "(?:"
    + "|".join(COMPARE_LEFT)
    + ").{0,8}(?:"
    + "|".join(COMPARE_RIGHT)
    + ")|(?:"
    + "|".join(("相比", "对比", "比起", "不像", "不同于"))
    + ").{0,8}(?:"
    + "|".join(COMPARE_LEFT)
    + ")"
)
_CORRECTION = re.compile(r"不是.{1,16}而是")


def find_symbols(text: str) -> list[tuple[str, str]]:
    if not text:
        return []
    occupied = bytearray(len(text))
    found: list[tuple[str, str]] = []
    for name, category in _SYMBOLS:
        start = 0
        while True:
            index = text.find(name, start)
            if index < 0:
                break
            end = index + len(name)
            if not any(occupied[index:end]):
                found.append((name, category))
                occupied[index:end] = b"\x01" * (end - index)
            start = index + 1
    return found


def _has_phrase(text: str, code: str) -> bool:
    return any(phrase in text for phrase in PHRASES[code])


def _production_composition(text: str) -> bool:
    if any(token in text for token in PRODUCTION_BLOCK):
        return False
    return any(aspect in text for aspect in ASPECTS) and any(token in text for token in POSITIVE)


def _watching(text: str) -> bool:
    if any(token in text for token in SUBTITLE_PRAISE) and not any(
        phrase in text and phrase not in ("字幕",) for phrase in PHRASES["观看体验"]
    ):
        return False
    return _has_phrase(text, "观看体验")


def classify(text: str) -> set[str]:
    if not text or not text.strip():
        return set()
    hits: set[str] = set()
    if find_symbols(text):
        hits.add("文化符号提及")
    if _has_phrase(text, "制作认可") or _production_composition(text):
        hits.add("制作认可")
    if _has_phrase(text, "制作诟病"):
        hits.add("制作诟病")
    if _watching(text):
        hits.add("观看体验")
    if _has_phrase(text, "知识补证") or _CORRECTION.search(text):
        hits.add("知识补证")
    if _has_phrase(text, "知识疑问"):
        hits.add("知识疑问")
    for code in (
        "古今共情",
        "文化自豪",
        "文化记忆",
        "传统美学褒扬",
        "审美辨析",
        "传承困境探讨",
        "古今适配讨论",
        "学习意愿",
        "传播意愿",
        "实践印证",
    ):
        if _has_phrase(text, code):
            hits.add(code)
    if _COMPARE.search(text):
        hits.add("文化比较")
    return hits


def label_list(text: str) -> list[str]:
    hits = classify(text)
    return [code for code in CODE_NAMES if code in hits]
