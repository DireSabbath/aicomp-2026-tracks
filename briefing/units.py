"""把一条弹幕拆成词，和去掉标点后的整句。"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

import jieba

from briefing.protocol import PHRASE_MAX, PHRASE_MIN, STOPWORDS, WORD_MAX, WORD_MIN

jieba.setLogLevel(logging.ERROR)

_CJK = re.compile(r"[\u4e00-\u9fff]")
_DROP = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]+")
_SPACE = re.compile(r"\s+")


def _same_char(text: str) -> bool:
    return len(text) >= 2 and all(char == text[0] for char in text)


@lru_cache(maxsize=100_000)
def split_units(content: str) -> tuple[str | None, tuple[str, ...]]:
    """整句去掉标点后若长度合格，记为一个短语。词来自分词，同一条里同一个词只记一次。"""
    core = _DROP.sub("", _SPACE.sub("", content or ""))
    phrase = None
    if PHRASE_MIN <= len(core) <= PHRASE_MAX and _CJK.search(core) and not _same_char(core):
        phrase = core
    words: list[str] = []
    seen: set[str] = set()
    if core:
        for token in jieba.cut(core, cut_all=False):
            token = token.strip()
            if token in seen:
                continue
            if not (WORD_MIN <= len(token) <= WORD_MAX):
                continue
            if token in STOPWORDS or _same_char(token) or _CJK.search(token) is None:
                continue
            seen.add(token)
            words.append(token)
    return phrase, tuple(words)


def display_raw(content: str) -> str:
    return _SPACE.sub("", content or "")
