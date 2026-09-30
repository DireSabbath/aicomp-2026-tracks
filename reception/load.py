"""从压缩包读取当前公开池弹幕，并换成片长上的位置。"""

from __future__ import annotations

import gzip
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Row:
    bvid: str
    content: str
    norm: str
    percent: float
    ctime: int | None


@dataclass
class Video:
    bvid: str
    title: str
    rows: list[Row] = field(default_factory=list)
    skipped: int = 0


@dataclass
class Pool:
    title: str
    videos: list[Video]

    @property
    def rows(self) -> list[Row]:
        found = []
        for video in self.videos:
            found.extend(video.rows)
        return found

    @property
    def skipped(self) -> int:
        return sum(video.skipped for video in self.videos)


def normalize(content: str) -> str:
    """去掉空白和标点，只为判断字面是不是同一句。页面仍显示原话。"""
    kept = []
    for char in content:
        if char.isspace():
            continue
        if char.isalnum() or "\u4e00" <= char <= "\u9fff":
            kept.append(char)
    return "".join(kept)


def percent_in_film(progress_ms: int | None, page: int, parts: list[dict]) -> float | None:
    if progress_ms is None or not parts:
        return None
    ordered = sorted(parts, key=lambda item: item.get("page") or 0)
    total = sum(int(item.get("duration") or 0) for item in ordered) * 1000
    if total <= 0:
        return None
    prior = sum(int(item.get("duration") or 0) for item in ordered if (item.get("page") or 0) < page) * 1000
    position = prior + int(progress_ms)
    if position >= total:
        position = total - 1
    if position < 0:
        return None
    return position / total


def _load_video(archive: zipfile.ZipFile, meta_name: str) -> Video:
    meta = json.loads(archive.read(meta_name))
    data_name = meta_name[: -len(".meta.json")] + ".jsonl.gz"
    video = Video(bvid=meta["bvid"], title=meta.get("title") or meta["bvid"])
    parts = meta.get("parts") or []
    raw = gzip.decompress(archive.read(data_name)).decode("utf-8")
    for line in raw.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        content = item.get("content") or ""
        norm = normalize(content)
        placed = percent_in_film(item.get("progress_ms"), int(item.get("page") or 1), parts)
        if not norm or placed is None:
            video.skipped += 1
            continue
        video.rows.append(
            Row(
                bvid=video.bvid,
                content=content.strip(),
                norm=norm,
                percent=placed,
                ctime=item.get("ctime"),
            )
        )
    return video


def load_zip(path: Path, limit_videos: int | None = None) -> Pool:
    with zipfile.ZipFile(path) as archive:
        metas = sorted(name for name in archive.namelist() if name.endswith(".meta.json"))
        if limit_videos is not None:
            metas = metas[:limit_videos]
        videos = [_load_video(archive, name) for name in metas]
    folder = Path(metas[0]).parent.name if metas else path.stem
    return Pool(title=folder, videos=videos)
