#!/usr/bin/env python3
"""通用 B 站弹幕爬取。

按公开接口拉取播放器当前能加载的全部分段弹幕（每段 6 分钟）。
页面上的累计条数可以更大。

示例：
  python danmaku/crawl.py --bvid BV1BK411L7DJ --out danmaku_out
  python danmaku/crawl.py --collections danmaku/collections.json --out danmaku_out
  python danmaku/crawl.py --collections danmaku/collections.json --list-only
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SEGMENT_MS = 360_000
BV_ALPHABET = "fZodR9XQDSUm21yCkr6zBqiveYah8bt4xsWpHnJE7jL5VG3guMTKNPAwcF"
BV_INDEX = [11, 10, 3, 8, 4, 6]
BV_ADD = 8728348608
BV_XOR = 177451812


class HttpError(RuntimeError):
    def __init__(self, code, url, body):
        super().__init__(f"HTTP {code} {url} {body[:120]!r}")
        self.code = code


def bv_to_aid(bvid: str) -> int:
    table = {ch: i for i, ch in enumerate(BV_ALPHABET)}
    value = 0
    for i in range(6):
        value += table[bvid[BV_INDEX[i]]] * 58**i
    return (value - BV_ADD) ^ BV_XOR


def read_varint(buf: bytes, index: int) -> tuple[int, int]:
    shift = 0
    number = 0
    while True:
        if index >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[index]
        index += 1
        number |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return number, index
        shift += 7
        if shift > 70:
            raise ValueError("varint too long")


def skip_value(buf: bytes, index: int, wire_type: int) -> int:
    if wire_type == 0:
        _, index = read_varint(buf, index)
        return index
    if wire_type == 1:
        return index + 8
    if wire_type == 2:
        length, index = read_varint(buf, index)
        return index + length
    if wire_type == 5:
        return index + 4
    raise ValueError(f"unsupported wire type {wire_type}")


def iter_fields(buf: bytes):
    index = 0
    while index < len(buf):
        key, index = read_varint(buf, index)
        field, wire_type = key >> 3, key & 7
        if wire_type == 0:
            value, index = read_varint(buf, index)
            yield field, wire_type, value
        elif wire_type == 2:
            length, index = read_varint(buf, index)
            yield field, wire_type, buf[index : index + length]
            index += length
        elif wire_type == 5:
            yield field, wire_type, buf[index : index + 4]
            index += 4
        elif wire_type == 1:
            yield field, wire_type, buf[index : index + 8]
            index += 8
        else:
            index = skip_value(buf, index, wire_type)


def decode_danmaku_segment(blob: bytes) -> list[dict]:
    """Decode DmSegMobileReply. Repeated DanmakuElem is field 1."""
    rows = []
    for field, wire_type, value in iter_fields(blob):
        if field != 1 or wire_type != 2:
            continue
        row = {"id": None, "progress_ms": None, "mode": None, "content": "", "ctime": None}
        for inner_field, inner_wire, inner in iter_fields(value):
            if inner_wire != 0 and inner_field != 7:
                continue
            if inner_field == 1 and inner_wire == 0:
                row["id"] = inner
            elif inner_field == 2 and inner_wire == 0:
                row["progress_ms"] = inner
            elif inner_field == 3 and inner_wire == 0:
                row["mode"] = inner
            elif inner_field == 7 and inner_wire == 2:
                row["content"] = inner.decode("utf-8", "replace")
            elif inner_field == 8 and inner_wire == 0:
                row["ctime"] = inner
        if row["content"]:
            rows.append(row)
    return rows


def segment_count_from_view(blob: bytes) -> int | None:
    """DmWebViewReply.dmSge is field 4; its total is field 2."""
    for field, wire_type, value in iter_fields(blob):
        if field == 4 and wire_type == 2:
            for inner_field, inner_wire, inner in iter_fields(value):
                if inner_field == 2 and inner_wire == 0:
                    return int(inner)
    return None


class BilibiliClient:
    def __init__(self, delay: float):
        self.delay = delay
        self._last = 0.0
        self.cookie = self._load_buvid()

    def _load_buvid(self) -> str:
        """Anonymous buvid. Season archive pages return -352 without it."""
        request = urllib.request.Request(
            "https://api.bilibili.com/x/frontend/finger/spi",
            headers={"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.loads(response.read().decode("utf-8"))
            payload = data.get("data") or {}
            parts = []
            if payload.get("b_3"):
                parts.append(f"buvid3={payload['b_3']}")
            if payload.get("b_4"):
                parts.append(f"buvid4={payload['b_4']}")
            return "; ".join(parts)
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError):
            return ""

    def _wait(self):
        gap = self.delay - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()

    def get(self, url: str, referer: str, raw: bool = False, retries: int = 5, cookie: bool = False):
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": referer,
            "Origin": "https://www.bilibili.com",
            "Accept": "*/*",
        }
        # Search treats a buvid cookie as a risk check and returns an empty voucher.
        # Season archive pages do the opposite: without buvid they return -352.
        if cookie and self.cookie:
            headers["Cookie"] = self.cookie
        for attempt in range(retries):
            self._wait()
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=40) as response:
                    body = response.read()
            except urllib.error.HTTPError as exc:
                snippet = exc.read(180)
                if exc.code in (412, 429, 503) and attempt + 1 < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise HttpError(exc.code, url, snippet) from exc
            except (TimeoutError, urllib.error.URLError):
                if attempt + 1 < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise
            if raw:
                return body
            text = body.decode("utf-8", "replace")
            if text.lstrip().startswith("<!") and attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
            return json.loads(text)
        raise RuntimeError(f"exhausted retries for {url}")

    def pagelist(self, bvid: str) -> list[dict]:
        data = self.get_ok(
            f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}",
            f"https://www.bilibili.com/video/{bvid}",
            f"pagelist {bvid}",
        )
        return data["data"]

    def get_ok(self, url: str, referer: str, what: str, cookie: bool = False) -> dict:
        last = None
        for attempt in range(6):
            data = self.get(url, referer, cookie=cookie)
            code = data.get("code")
            if code in (0, "0"):
                return data
            last = data
            if code in (-352, -412, -799, -509, 429) and attempt + 1 < 6:
                time.sleep(2 ** attempt + 1)
                continue
            break
        raise RuntimeError(f"{what}: {last.get('message') if last else 'empty'} ({None if last is None else last.get('code')})")

    def fetch_video_danmaku(self, bvid: str, aid: int | None = None) -> tuple[list[dict], dict]:
        if aid is None:
            aid = bv_to_aid(bvid)
        pages = self.pagelist(bvid)
        rows = []
        seen = set()
        parts = []
        for page in pages:
            cid = page["cid"]
            duration = int(page.get("duration") or 0)
            view = self.get(
                f"https://api.bilibili.com/x/v2/dm/web/view?type=1&oid={cid}&pid={aid}",
                f"https://www.bilibili.com/video/{bvid}",
                raw=True,
            )
            reported = segment_count_from_view(view)
            by_duration = max(1, math.ceil(duration / 360)) if duration else 1
            total = max(reported or 0, by_duration)
            part_count = 0
            empty_run = 0
            for index in range(1, total + 1):
                blob = self.get(
                    "https://api.bilibili.com/x/v2/dm/web/seg.so?"
                    + urllib.parse.urlencode(
                        {"type": 1, "oid": cid, "pid": aid, "segment_index": index}
                    ),
                    f"https://www.bilibili.com/video/{bvid}",
                    raw=True,
                )
                if blob[:1] == b"{":
                    empty_run += 1
                    if empty_run >= 2:
                        break
                    continue
                decoded = decode_danmaku_segment(blob)
                if not decoded:
                    empty_run += 1
                    if empty_run >= 2:
                        break
                    continue
                empty_run = 0
                for row in decoded:
                    key = (cid, row["id"], row["progress_ms"], row["content"])
                    if key in seen:
                        continue
                    seen.add(key)
                    row["cid"] = cid
                    row["page"] = page.get("page")
                    rows.append(row)
                    part_count += 1
            parts.append({"cid": cid, "page": page.get("page"), "duration": duration, "segments": total, "count": part_count})
        rows.sort(key=lambda item: (item["progress_ms"] or 0, item["id"] or 0))
        return rows, {"aid": aid, "parts": parts, "count": len(rows)}

    def season_videos(self, mid: int, season_id: int) -> list[dict]:
        videos = []
        page_num = 1
        while True:
            data = self.get_ok(
                "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list?"
                + urllib.parse.urlencode(
                    {
                        "mid": mid,
                        "season_id": season_id,
                        "page_num": page_num,
                        "page_size": 20,
                        "sort_reverse": "false",
                    }
                ),
                f"https://space.bilibili.com/{mid}",
                f"season {season_id} page {page_num}",
                cookie=True,
            )
            archives = (data.get("data") or {}).get("archives") or []
            if not archives:
                break
            for item in archives:
                videos.append(
                    {
                        "bvid": item["bvid"],
                        "aid": item["aid"],
                        "title": item.get("title") or "",
                        "duration": item.get("duration"),
                    }
                )
            page = (data.get("data") or {}).get("page") or {}
            total = int(page.get("total") or 0)
            if page_num * 20 >= total:
                break
            page_num += 1
        print(f"  season {season_id} videos {len(videos)}", flush=True)
        return videos

    def series_videos(self, mid: int, series_id: int) -> list[dict]:
        videos = []
        page_num = 1
        while True:
            data = self.get_ok(
                "https://api.bilibili.com/x/series/archives?"
                + urllib.parse.urlencode(
                    {
                        "mid": mid,
                        "series_id": series_id,
                        "only_normal": "true",
                        "sort": "desc",
                        "pn": page_num,
                        "ps": 20,
                    }
                ),
                f"https://space.bilibili.com/{mid}",
                f"series {series_id} page {page_num}",
            )
            archives = (data.get("data") or {}).get("archives") or []
            if not archives:
                break
            for item in archives:
                videos.append(
                    {
                        "bvid": item["bvid"],
                        "aid": item["aid"],
                        "title": item.get("title") or "",
                        "duration": item.get("duration"),
                    }
                )
            page = (data.get("data") or {}).get("page") or {}
            total = int(page.get("total") or 0)
            if page_num * 20 >= total:
                break
            page_num += 1
        print(f"  series {series_id} videos {len(videos)}", flush=True)
        return videos

    def search_videos(
        self,
        keyword: str,
        author_mid: int,
        title_contains: str | None = None,
        orders: list[str] | None = None,
    ) -> list[dict]:
        found = {}
        for order in orders or ["dm"]:
            page = 1
            num_pages = 1
            while page <= num_pages and page <= 50:
                body = None
                for attempt in range(5):
                    data = self.get_ok(
                        "https://api.bilibili.com/x/web-interface/wbi/search/type?"
                        + urllib.parse.urlencode(
                            {
                                "search_type": "video",
                                "keyword": keyword,
                                "order": order,
                                "page": page,
                                "page_size": 20,
                            }
                        ),
                        "https://search.bilibili.com",
                        f"search {keyword} {order} page {page}",
                    )
                    candidate = data.get("data") or {}
                    if isinstance(candidate.get("result"), list):
                        body = candidate
                        break
                    time.sleep(2 ** attempt)
                if body is None:
                    print(f"  search {keyword} {order} page {page} skipped after retries", flush=True)
                    break
                num_pages = int(body.get("numPages") or 1)
                for item in body.get("result") or []:
                    if int(item.get("mid") or 0) != author_mid:
                        continue
                    title = (item.get("title") or "").replace('<em class="keyword">', "").replace("</em>", "")
                    if title_contains and title_contains not in title:
                        continue
                    found[item["bvid"]] = {
                        "bvid": item["bvid"],
                        "aid": item.get("aid"),
                        "title": title,
                        "duration": item.get("duration"),
                        "danmaku_counter": item.get("danmaku"),
                    }
                page += 1
            print(f"  search {keyword} {order} pages {page - 1} matched {len(found)}", flush=True)
        return list(found.values())

    def author_collection_videos(self, mid: int) -> list[dict]:
        """Every video inside the author's seasons and series."""
        videos: list[dict] = []
        page_num = 1
        while page_num <= 20:
            data = self.get_ok(
                "https://api.bilibili.com/x/polymer/web-space/seasons_series_list?"
                + urllib.parse.urlencode({"mid": mid, "page_num": page_num, "page_size": 20}),
                f"https://space.bilibili.com/{mid}",
                f"seasons_series_list {mid} page {page_num}",
            )
            items = (data.get("data") or {}).get("items_lists") or {}
            seasons = items.get("seasons_list") or []
            series = items.get("series_list") or []
            for season in seasons:
                meta = season.get("meta") or {}
                season_id = meta.get("season_id")
                if season_id:
                    videos.extend(self.season_videos(mid, int(season_id)))
            for item in series:
                meta = item.get("meta") or {}
                series_id = meta.get("series_id")
                if series_id:
                    videos.extend(self.series_videos(mid, int(series_id)))
            page = items.get("page") or {}
            total = int(page.get("total") or 0)
            if not seasons and not series:
                break
            if page_num * 20 >= total:
                break
            page_num += 1
        return videos

    def archive_count(self, mid: int) -> int | None:
        data = self.get(
            f"https://api.bilibili.com/x/web-interface/card?mid={mid}",
            f"https://space.bilibili.com/{mid}",
        )
        if data.get("code") != 0:
            return None
        return (data.get("data") or {}).get("archive_count")


def dedupe(videos: list[dict]) -> list[dict]:
    found = {}
    for video in videos:
        found[video["bvid"]] = {**found.get(video["bvid"], {}), **video}
    return list(found.values())


def resolve_collection(client: BilibiliClient, spec: dict) -> list[dict]:
    mid = int(spec["mid"])
    mode = spec["list"]
    videos: list[dict] = []
    if mode == "season":
        videos.extend(client.season_videos(mid, int(spec["season_id"])))
    elif mode == "seasons":
        for season_id in spec["season_ids"]:
            videos.extend(client.season_videos(mid, int(season_id)))
    elif mode == "series":
        for series_id in spec["series_ids"]:
            videos.extend(client.series_videos(mid, int(series_id)))
    elif mode == "search":
        videos.extend(
            client.search_videos(
                spec["keyword"], mid, spec.get("title_contains"), spec.get("search_orders")
            )
        )
    elif mode == "seasons_and_search":
        for season_id in spec.get("season_ids") or []:
            videos.extend(client.season_videos(mid, int(season_id)))
        if spec.get("keyword"):
            videos.extend(
                client.search_videos(
                    spec["keyword"], mid, spec.get("title_contains"), spec.get("search_orders")
                )
            )
    elif mode == "author_plus_search":
        videos.extend(client.author_collection_videos(mid))
        if spec.get("keyword"):
            videos.extend(
                client.search_videos(
                    spec["keyword"], mid, spec.get("title_contains"), spec.get("search_orders")
                )
            )
    else:
        raise SystemExit(f"unknown list mode {mode}")
    return dedupe(videos)


def write_video(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def crawl_collection(
    client: BilibiliClient,
    spec: dict,
    out_dir: Path,
    limit: int | None,
    preset: list[dict] | None = None,
) -> dict:
    videos = list(preset) if preset is not None else resolve_collection(client, spec)
    if limit is not None:
        videos = videos[:limit]
    folder = out_dir / spec["id"]
    folder.mkdir(parents=True, exist_ok=True)
    done = []
    failures = []
    for index, video in enumerate(videos, 1):
        target = folder / f"{video['bvid']}.jsonl.gz"
        marker = folder / f"{video['bvid']}.meta.json"
        if target.exists() and marker.exists():
            meta = json.loads(marker.read_text(encoding="utf-8"))
            done.append(meta)
            print(f"[{spec['id']}] {index}/{len(videos)} skip {video['bvid']}", flush=True)
            continue
        print(f"[{spec['id']}] {index}/{len(videos)} {video['bvid']} {video.get('title','')[:40]}", flush=True)
        try:
            rows, info = client.fetch_video_danmaku(video["bvid"], video.get("aid"))
        except Exception as exc:
            failures.append({"bvid": video["bvid"], "title": video.get("title"), "error": str(exc)})
            print(f"  FAIL {exc}", flush=True)
            continue
        write_video(target, rows)
        meta = {
            "bvid": video["bvid"],
            "aid": info["aid"],
            "title": video.get("title"),
            "count": info["count"],
            "parts": info["parts"],
            "file": str(target.relative_to(out_dir)),
        }
        marker.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        done.append(meta)
    summary = {
        "id": spec["id"],
        "title": spec.get("title"),
        "mid": spec.get("mid"),
        "note": spec.get("note"),
        "archive_count": client.archive_count(int(spec["mid"])) if spec.get("mid") else None,
        "listed": len(videos) if limit is None else len(videos),
        "saved": len(done),
        "danmaku": sum(item["count"] for item in done),
        "failures": failures,
        "videos": [{k: item[k] for k in ("bvid", "aid", "title", "count")} for item in done],
    }
    (folder / "_collection.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="爬取 B 站视频的当前公开弹幕池")
    parser.add_argument("--bvid", action="append", default=[], help="单个 BV，可重复")
    parser.add_argument("--collections", type=Path, help="合集 JSON")
    parser.add_argument("--only", action="append", default=[], help="只跑这些合集 id")
    parser.add_argument("--out", type=Path, default=Path("danmaku_out"))
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--limit", type=int, default=None, help="每个合集最多爬多少条视频")
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--refresh-list", action="store_true", help="忽略已保存的视频清单，重新向接口要列表")
    args = parser.parse_args(argv)
    client = BilibiliClient(args.delay)
    args.out.mkdir(parents=True, exist_ok=True)

    if args.bvid:
        for bvid in args.bvid:
            rows, info = client.fetch_video_danmaku(bvid)
            path = args.out / f"{bvid}.jsonl.gz"
            write_video(path, rows)
            print(json.dumps({"bvid": bvid, "count": info["count"], "file": str(path)}, ensure_ascii=False))
        return 0

    if not args.collections:
        parser.error("需要 --bvid 或 --collections")
    all_specs = json.loads(args.collections.read_text(encoding="utf-8"))
    specs = all_specs
    if args.only:
        wanted = set(args.only)
        specs = [item for item in specs if item["id"] in wanted]
    lists_dir = args.collections.parent / "lists"
    summaries = []
    for spec in specs:
        if args.list_only:
            videos = resolve_collection(client, spec)
            folder = args.out / spec["id"]
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "_videos.json").write_text(
                json.dumps(videos, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"{spec['id']}\t{len(videos)}\t{spec.get('title')}", flush=True)
            summaries.append({"id": spec["id"], "title": spec.get("title"), "listed": len(videos)})
            continue
        preset = None
        saved = lists_dir / spec["id"] / "_videos.json"
        if saved.exists() and not args.refresh_list:
            preset = json.loads(saved.read_text(encoding="utf-8"))
            print(f"[{spec['id']}] 使用已保存清单 {len(preset)} 条", flush=True)
        summaries.append(crawl_collection(client, spec, args.out, args.limit, preset))
    if args.list_only:
        summaries = manifest_from_lists(args.out, all_specs)
    manifest = {
        "source": "https://api.bilibili.com/x/v2/dm/web/seg.so",
        "scope": "播放器当前公开弹幕池的全部分段。页面上的累计数可以更大。",
        "fields": ["id", "progress_ms", "mode", "content", "ctime", "cid", "page"],
        "omitted": ["midHash"],
        "collections": summaries,
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({item["id"]: {"saved": item.get("saved"), "danmaku": item.get("danmaku"), "listed": item.get("listed")} for item in summaries}, ensure_ascii=False))
    return 0


def manifest_from_lists(out_dir: Path, specs: list[dict]) -> list[dict]:
    by_id = {item["id"]: item for item in specs}
    found = []
    for folder in sorted(path for path in out_dir.iterdir() if path.is_dir()):
        listing = folder / "_videos.json"
        if not listing.exists():
            continue
        videos = json.loads(listing.read_text(encoding="utf-8"))
        spec = by_id.get(folder.name, {})
        found.append(
            {
                "id": folder.name,
                "title": spec.get("title"),
                "mid": spec.get("mid"),
                "note": spec.get("note"),
                "listed": len(videos),
            }
        )
    return found


if __name__ == "__main__":
    sys.exit(main())
