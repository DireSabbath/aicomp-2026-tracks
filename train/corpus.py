"""把本地弹幕压缩包收成训练用的一行一条。

不写发言者，不写弹幕 id。页面能打开，不等于这些文字可以再分发。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import zipfile
from pathlib import Path

from reception.load import normalize, percent_in_film

# 与 danmaku/lists/release-sha256.txt 同一批。对不上就拒绝开训，避免训错材料。
RELEASE_SHA256 = {
    "heishenhua.zip": "b8658d7e46fc210cccd539b105a9c7798f8d7e34a7740bc48b5eb34e895190e1",
    "luoxiang.zip": "81b64bfeff16f6125403396cb37bbfcb0540e77318f4759909367d819c3952d1",
    "new-sanguo.zip": "d63afd605b1fba5541e0fd8741c469d1ab44d55741ba96883dff9be28cdd6597",
    "xiaoyuehan.zip": "caa059d5c942a6cace4befa7e7c9778e8e35618ecbe0eb1b59aaed290f86b6ee",
    "yuanshen-preview.zip": "4cde493959d6dce472caf538fa85867c06a94633ed870e15db31997d74fd3e91",
}

_DROP_KEYS = ("id", "midHash", "mid", "user", "uname", "uid")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_known_zip(path: Path) -> str:
    digest = sha256_file(path)
    expected = RELEASE_SHA256.get(path.name)
    if expected is not None and digest != expected:
        raise SystemExit(f"{path.name} 的校验和与 2026-09-26 的发布包不一致，停止。")
    return digest


def iter_comments(path: Path):
    with zipfile.ZipFile(path) as archive:
        metas = sorted(name for name in archive.namelist() if name.endswith(".meta.json"))
        for meta_name in metas:
            meta = json.loads(archive.read(meta_name))
            data_name = meta_name[: -len(".meta.json")] + ".jsonl.gz"
            parts = meta.get("parts") or []
            raw = gzip.decompress(archive.read(data_name)).decode("utf-8")
            for line in raw.splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                for key in _DROP_KEYS:
                    item.pop(key, None)
                content = (item.get("content") or "").strip()
                if not content:
                    continue
                placed = percent_in_film(item.get("progress_ms"), int(item.get("page") or 1), parts)
                yield {
                    "bvid": meta["bvid"],
                    "content": content,
                    "norm": normalize(content),
                    "percent": None if placed is None else round(placed, 4),
                    "ctime": item.get("ctime"),
                    "page": int(item.get("page") or 1),
                }


def write_comments(zips: list[Path], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "comments.jsonl"
    counts: dict[str, int] = {}
    archives = []
    with target.open("w", encoding="utf-8") as handle:
        for path in zips:
            digest = require_known_zip(path)
            n = 0
            for row in iter_comments(path):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                n += 1
            counts[path.name] = n
            archives.append({"file": path.name, "sha256": digest, "rows": n})
    manifest = {
        "rows": sum(counts.values()),
        "archives": archives,
        "fields": ["bvid", "content", "norm", "percent", "ctime", "page"],
        "omitted": list(_DROP_KEYS),
        "redistributed": False,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def read_texts(path: Path) -> list[str]:
    texts = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            text = item.get("content") or item.get("text") or ""
            if text.strip():
                texts.append(text.strip())
    return texts
