import jieba

from shuofa.textutil import normalize


def cuts(text: str) -> list[str]:
    return [token for token in jieba.lcut(text) if token.strip()]


def split_report(forms: list[str]) -> dict:
    """常规词频按字面把写法拆开。这里给出拆开之后的词。"""
    rows = []
    for form in forms:
        rows.append({"form": form, "tokens": cuts(form)})
    token_sets = {tuple(row["tokens"]) for row in rows}
    return {
        "forms": len(rows),
        "different_cuts": len(token_sets) > 1,
        "rows": rows,
    }


def same_sentence_key(text: str) -> str:
    return normalize(text)
