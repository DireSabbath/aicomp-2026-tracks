#!/usr/bin/env python3
"""通用 B 站弹幕爬取。

按公开接口拉取播放器当前能加载的全部分段弹幕（每段 6 分钟）。
历史弹幕要登录。加上 --history 后，从最新一天往回跳：下一天由本池最早的发送时间决定，
凑满页面累计数，或碰到不满 5000 条的那天，就停。

示例：
  python danmaku/crawl.py --bvid BV1BK411L7DJ --out danmaku_out
  python danmaku/crawl.py --collections danmaku/collections.json --out danmaku_out
  python danmaku/crawl.py --collections danmaku/collections.json --history --sessdata-file /path/SESSDATA --out danmaku_history
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
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


class LoginExpired(RuntimeError):
    pass


CN_TZ = timezone(timedelta(hours=8))
HISTORY_DAY_CAP = 5000
RATE_LIMIT_CODES = {-702, -509, -799, -412, 429}


def months_from(pubdate: int, now: datetime | None = None) -> list[str]:
    """Months from the video's publish time through now, in China time."""
    start = datetime.fromtimestamp(int(pubdate), CN_TZ)
    current = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)
    year, month = start.year, start.month
    months = []
    while (year, month) <= (current.year, current.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
        if len(months) > 360:
            break
    return months


def china_day(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), CN_TZ).strftime("%Y-%m-%d")


def shift_day(day: str, delta: int) -> str:
    parsed = datetime.strptime(day, "%Y-%m-%d")
    return (parsed + timedelta(days=delta)).strftime("%Y-%m-%d")


def shift_month(month: str, delta: int) -> str:
    year, mon = (int(part) for part in month.split("-"))
    mon += delta
    while mon < 1:
        mon += 12
        year -= 1
    while mon > 12:
        mon -= 12
        year += 1
    return f"{year:04d}-{mon:02d}"


def jump_target_day(ctimes: list[int], fetched: str, row_count: int, cap: int = HISTORY_DAY_CAP) -> str | None:
    """Next China date when walking newest to oldest, or None to stop.

    A snapshot under the pool cap still holds older danmaku, so the walk stops.
    A full snapshot jumps to the day before its oldest ctime. If every ctime
    falls on the fetched day, step exactly one day back.
    """
    if row_count < cap:
        return None
    if not ctimes:
        return shift_day(fetched, -1)
    oldest = china_day(min(ctimes))
    if oldest >= fetched:
        return shift_day(fetched, -1)
    return shift_day(oldest, -1)


def read_sessdata(path: Path | None) -> str:
    if path is not None:
        text = path.read_text(encoding="utf-8").strip()
    else:
        text = os.environ.get("SESSDATA", "").strip()
    if "%2C" in text or "%2c" in text:
        text = urllib.parse.unquote(text)
    return text.strip()


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
    def __init__(self, delay: float, sessdata: str = ""):
        self.delay = delay
        self._last = 0.0
        self.cookie = self._load_buvid()
        self.sessdata = sessdata.strip()
        self.login_with_buvid = False

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

    def get(self, url: str, referer: str, raw: bool = False, retries: int = 5, cookie: bool = False, login: bool = False):
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": referer,
            "Origin": "https://www.bilibili.com",
            "Accept": "*/*",
        }
        # Search treats a buvid cookie as a risk check and returns an empty voucher.
        # Season archive pages do the opposite: without buvid they return -352.
        # SESSDATA is only sent when login=True. It is never printed.
        parts = []
        if cookie and self.cookie:
            parts.append(self.cookie)
        if login:
            if not self.sessdata:
                raise LoginExpired("缺少 SESSDATA")
            if self.login_with_buvid and self.cookie:
                parts.append(self.cookie)
            parts.append(f"SESSDATA={self.sessdata}")
        if parts:
            headers["Cookie"] = "; ".join(parts)
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

    def get_ok(self, url: str, referer: str, what: str, cookie: bool = False, login: bool = False, tries: int = 6) -> dict:
        last = None
        for attempt in range(tries):
            data = self.get(url, referer, cookie=cookie, login=login)
            code = data.get("code")
            if code == -101 and login:
                raise LoginExpired(f"{what}: 账号未登录")
            if code in (0, "0"):
                return data
            last = data
            if (code in RATE_LIMIT_CODES or code == -352) and attempt + 1 < tries:
                time.sleep(2 ** attempt + 1)
                continue
            break
        raise RuntimeError(f"{what}: {last.get('message') if last else 'empty'} ({None if last is None else last.get('code')})")

    def whoami(self) -> dict:
        data = self.get_ok(
            "https://api.bilibili.com/x/web-interface/nav",
            "https://www.bilibili.com",
            "nav",
            login=True,
        )
        info = data.get("data") or {}
        if not info.get("isLogin"):
            raise LoginExpired("账号未登录")
        return {"uname": info.get("uname"), "mid": info.get("mid")}

    def video_detail(self, bvid: str) -> dict:
        data = self.get_ok(
            f"https://api.bilibili.com/x/web-interface/wbi/view?bvid={bvid}",
            f"https://www.bilibili.com/video/{bvid}",
            f"view {bvid}",
            login=True,
        )
        info = data["data"]
        pages = [
            {"cid": page["cid"], "page": page.get("page"), "duration": page.get("duration")}
            for page in info.get("pages") or []
        ]
        return {
            "aid": info.get("aid"),
            "title": info.get("title") or "",
            "pubdate": int(info.get("pubdate") or 0),
            "page_danmaku": (info.get("stat") or {}).get("danmaku"),
            "pages": pages,
        }

    def history_dates(self, cid: int, month: str, bvid: str) -> list[str]:
        data = self.get_ok(
            "https://api.bilibili.com/x/v2/dm/history/index?"
            + urllib.parse.urlencode({"type": 1, "oid": cid, "month": month}),
            f"https://www.bilibili.com/video/{bvid}",
            f"history index {bvid} {month}",
            login=True,
            tries=3,
        )
        return list(data.get("data") or [])

    def history_day(self, cid: int, date: str, bvid: str) -> list[dict]:
        last_message = "rate limit"
        url = (
            "https://api.bilibili.com/x/v2/dm/web/history/seg.so?"
            + urllib.parse.urlencode({"type": 1, "oid": cid, "date": date})
        )
        for attempt in range(2):
            blob = self.get(
                url,
                f"https://www.bilibili.com/video/{bvid}",
                raw=True,
                retries=2,
                login=True,
            )
            if blob[:1] != b"{":
                return decode_danmaku_segment(blob)
            try:
                payload = json.loads(blob.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                return []
            code = payload.get("code")
            if code == -101:
                raise LoginExpired(f"history {bvid} {date}: 账号未登录")
            message = str(payload.get("message") or code)
            if code in RATE_LIMIT_CODES:
                last_message = message
                if attempt == 0:
                    time.sleep(2)
                    continue
                break
            if code in (0, "0", None):
                return []
            raise RuntimeError(f"history {bvid} {date}: {message} ({code})")
        raise RuntimeError(f"history {bvid} {date}: {last_message}")

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


def load_seen_ids(path: Path) -> set[int]:
    seen: set[int] = set()
    if not path.exists():
        return seen
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            seen.add(json.loads(line)["id"])
    return seen


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def gzip_text_file(src: Path, dest: Path) -> None:
    with src.open("rb") as raw, gzip.open(dest, "wb") as packed:
        shutil.copyfileobj(raw, packed)


def crawl_history_video(client: BilibiliClient, video: dict, folder: Path) -> dict:
    """Union of history pools, newest first. Same danmaku id is kept once."""
    bvid = video["bvid"]
    done_path = folder / f"{bvid}.done.json"
    if done_path.exists():
        return json.loads(done_path.read_text(encoding="utf-8"))
    folder.mkdir(parents=True, exist_ok=True)
    raw_path = folder / f"{bvid}.jsonl"
    plan_path = folder / f"{bvid}.plan.json"
    plan = None
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan.get("mode") != "jump":
            plan_path.unlink()
            plan = None
    if plan is None:
        detail = client.video_detail(bvid)
        plan = {
            "mode": "jump",
            "bvid": bvid,
            "aid": detail["aid"],
            "title": detail["title"] or video.get("title") or "",
            "pubdate": detail["pubdate"],
            "page_danmaku": detail["page_danmaku"],
            "pages": detail["pages"],
            "page_index": 0,
            "cursor": None,
            "capped_days": 0,
            "fetched_days": 0,
            "count": 0,
        }
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        print(
            f"  {bvid} 按发送时间从新往旧跳，页面累计 {plan['page_danmaku']}，分P {len(plan['pages'])}",
            flush=True,
        )
    seen = load_seen_ids(raw_path)
    pubdate = int(plan.get("pubdate") or 0)
    pub_day = china_day(pubdate) if pubdate else "2009-01-01"
    pub_month = pub_day[:7]
    page_danmaku = plan.get("page_danmaku")
    try:
        page_danmaku = int(page_danmaku) if page_danmaku is not None else None
    except (TypeError, ValueError):
        page_danmaku = None
    index_cache: dict[tuple[int, str], list[str]] = {}

    def dates_in(cid: int, month: str) -> list[str]:
        key = (cid, month)
        if key not in index_cache:
            index_cache[key] = client.history_dates(cid, month, bvid)
        return index_cache[key]

    def snap(cid: int, target: str) -> str | None:
        month = target[:7]
        for _ in range(240):
            if month < pub_month:
                return None
            found = [day for day in dates_in(cid, month) if pub_day <= day <= target]
            if found:
                return max(found)
            month = shift_month(month, -1)
        return None

    def newest(cid: int) -> str | None:
        month = datetime.now(CN_TZ).strftime("%Y-%m")
        for _ in range(240):
            if month < pub_month:
                return None
            found = [day for day in dates_in(cid, month) if day >= pub_day]
            if found:
                return max(found)
            month = shift_month(month, -1)
        return None

    def save() -> None:
        plan["count"] = len(seen)
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    pages = plan.get("pages") or []
    start = int(plan.get("page_index") or 0)
    filled = False
    for page_index in range(start, len(pages)):
        page = pages[page_index]
        cid = page["cid"]
        plan["page_index"] = page_index
        target = plan.get("cursor") if page_index == start else None
        visited: set[str] = set()
        while True:
            if page_danmaku is not None and page_danmaku > 0 and len(seen) >= page_danmaku:
                filled = True
                print(f"  {bvid} 已凑满页面累计 {page_danmaku}", flush=True)
                break
            if target is None:
                day = newest(cid)
            elif target < pub_day:
                break
            else:
                day = snap(cid, target)
            if not day or day < pub_day:
                break
            if day in visited:
                earlier = shift_day(day, -1)
                if earlier < pub_day:
                    break
                target = earlier
                continue
            visited.add(day)
            plan["cursor"] = day
            save()
            decoded = client.history_day(cid, day, bvid)
            fresh = []
            for row in decoded:
                if row["id"] is None or row["id"] in seen:
                    continue
                seen.add(row["id"])
                row["cid"] = cid
                row["page"] = page.get("page")
                row["history_date"] = day
                fresh.append(row)
            if len(decoded) >= HISTORY_DAY_CAP:
                plan["capped_days"] = int(plan.get("capped_days") or 0) + 1
            plan["fetched_days"] = int(plan.get("fetched_days") or 0) + 1
            append_jsonl(raw_path, fresh)
            nxt = jump_target_day(
                [int(row["ctime"]) for row in decoded if row.get("ctime")],
                day,
                len(decoded),
            )
            print(f"  {bvid} {day} 本池 {len(decoded)} 新增后共 {len(seen)}", flush=True)
            if nxt is None or nxt < pub_day:
                break
            target = nxt
        plan["page_index"] = page_index + 1
        plan["cursor"] = None
        save()
        if filled:
            break
    gz_path = folder / f"{bvid}.jsonl.gz"
    if raw_path.exists():
        gzip_text_file(raw_path, gz_path)
        raw_path.unlink()
    else:
        write_video(gz_path, [])
    meta = {
        "bvid": bvid,
        "aid": plan.get("aid"),
        "title": plan.get("title"),
        "page_danmaku": plan.get("page_danmaku"),
        "count": len(seen),
        "dates": int(plan.get("fetched_days") or 0),
        "capped_days": int(plan.get("capped_days") or 0),
        "file": str(gz_path),
    }
    done_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    plan_path.unlink(missing_ok=True)
    return meta


def crawl_history_collection(client: BilibiliClient, spec: dict, out_dir: Path, videos: list[dict], limit: int | None) -> dict:
    if limit is not None:
        videos = videos[:limit]
    folder = out_dir / spec["id"]
    folder.mkdir(parents=True, exist_ok=True)
    done = []
    failures = []
    for index, video in enumerate(videos, 1):
        print(f"[{spec['id']}] {index}/{len(videos)} {video['bvid']} {(video.get('title') or '')[:40]}", flush=True)
        meta = None
        for _rate_try in range(2):
            try:
                meta = crawl_history_video(client, video, folder)
                break
            except LoginExpired:
                raise
            except Exception as exc:
                limited = "频率" in str(exc) or "rate limit" in str(exc)
                if limited and not client.login_with_buvid:
                    client.login_with_buvid = True
                    print("  正文接口被限流，带上匿名标识再请求一次", flush=True)
                    continue
                if limited:
                    print("  历史弹幕正文仍返回频率过高，先停下。进度已留下，同一条命令可以续跑。", flush=True)
                    raise SystemExit(2) from exc
                failures.append({"bvid": video["bvid"], "title": video.get("title"), "error": str(exc)})
                print(f"  FAIL {exc}", flush=True)
                break
        if meta is None:
            continue
        done.append(meta)
        print(f"  完成 {meta['count']} 条，页面累计 {meta['page_danmaku']}，日期 {meta['dates']}", flush=True)
    summary = {
        "id": spec["id"],
        "title": spec.get("title"),
        "saved": len(done),
        "listed": len(videos),
        "danmaku": sum(item["count"] for item in done),
        "page_danmaku": sum(item.get("page_danmaku") or 0 for item in done),
        "capped_days": sum(item.get("capped_days") or 0 for item in done),
        "failures": failures,
        "videos": [
            {key: item.get(key) for key in ("bvid", "aid", "title", "count", "page_danmaku", "dates", "capped_days")}
            for item in done
        ],
    }
    (folder / "_collection.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
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
    parser.add_argument("--history", action="store_true", help="用登录态按日期拉历史弹幕")
    parser.add_argument("--sessdata-file", type=Path, help="SESSDATA 文件，内容不要提交到仓库")
    args = parser.parse_args(argv)
    sessdata = read_sessdata(args.sessdata_file) if args.history else ""
    if args.history and not sessdata:
        parser.error("历史弹幕需要 SESSDATA 环境变量或 --sessdata-file")
    client = BilibiliClient(args.delay, sessdata)
    args.out.mkdir(parents=True, exist_ok=True)

    if args.history:
        who = client.whoami()
        print(f"已登录 {who.get('uname')}", flush=True)

    if args.bvid:
        for bvid in args.bvid:
            if args.history:
                meta = crawl_history_video(client, {"bvid": bvid, "title": ""}, args.out)
                print(json.dumps({key: meta[key] for key in ("bvid", "count", "page_danmaku", "dates", "capped_days")}, ensure_ascii=False))
                continue
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
        if args.history:
            if preset is None:
                preset = resolve_collection(client, spec)
            summaries.append(crawl_history_collection(client, spec, args.out, preset, args.limit))
            continue
        summaries.append(crawl_collection(client, spec, args.out, args.limit, preset))
    if args.list_only:
        summaries = manifest_from_lists(args.out, all_specs)
    if args.history:
        manifest = {
            "source": "https://api.bilibili.com/x/v2/dm/web/history/seg.so",
            "scope": "登录后从最新一天往回跳着拉历史弹幕。下一天由本池最早的发送时间决定。凑满页面累计数，或碰到不满 5000 条的那天，就停。同一 id 只保留一次。满 5000 条的那天，超出的部分不在文件里。",
            "fields": ["id", "progress_ms", "mode", "content", "ctime", "cid", "page", "history_date"],
            "omitted": ["midHash"],
            "collections": summaries,
        }
    else:
        manifest = {
            "source": "https://api.bilibili.com/x/v2/dm/web/seg.so",
            "scope": "播放器当前公开弹幕池的全部分段。历史弹幕按日期另存，需要登录。",
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
