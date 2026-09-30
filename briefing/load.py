"""从爬取压缩包读视频。不在日志里打印正文。"""

from __future__ import annotations

import gzip
import io
import json
import zipfile
from dataclasses import dataclass, field


@dataclass
class Video:
    bvid: str
    title: str
    parts: list[dict]
    rows: list[dict] = field(default_factory=list)


def load_zip(path: str) -> list[Video]:
    videos: list[Video] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        metas = sorted(name for name in names if name.endswith(".meta.json"))
        for meta_name in metas:
            meta = json.loads(archive.read(meta_name))
            rel = meta.get("file") or meta_name.replace(".meta.json", ".jsonl.gz")
            if rel not in names:
                continue
            rows = []
            with gzip.GzipFile(fileobj=io.BytesIO(archive.read(rel))) as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    rows.append(json.loads(line))
            videos.append(
                Video(
                    bvid=str(meta.get("bvid") or ""),
                    title=str(meta.get("title") or ""),
                    parts=list(meta.get("parts") or []),
                    rows=rows,
                )
            )
    videos.sort(key=lambda item: item.bvid)
    return videos
