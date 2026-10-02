"""把一条片子上的原话铺成光。

python -m reception 甲.zip 乙.zip --out demo_out/reception
页面用第一份压缩包里弹幕最多的那一条。
"""

from __future__ import annotations

import argparse
import json
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from reception.load import load_zip
from reception.page import build_report
from reception.shot import build_shot
from reception.stage import render_shot


def _public_thing(thing: dict) -> dict:
    return {
        "text": thing["text"],
        "start": thing["start"],
        "end": thing["end"],
        "median": thing["median"],
        "n_videos": thing["n_videos"],
        "n_rows": thing["n_rows"],
        "mode": thing["mode"],
        "role": thing.get("role", ""),
        "rank": thing.get("rank", 0),
        "p25": thing.get("p25", thing["median"]),
        "p75": thing.get("p75", thing["median"]),
        "marks": thing.get("marks") or [thing["median"]],
        "evidence": thing["evidence"],
    }


def _public_side(built: dict) -> dict:
    return {
        "title": built["title"],
        "n_videos": built["n_videos"],
        "n_placed": built["n_placed"],
        "n_skipped": built["n_skipped"],
        "crowded": built["crowded"],
        "shown": [_public_thing(thing) for thing in built["shown"]],
        "layers": [_public_thing(thing) for thing in built.get("layers") or built["shown"]],
        "things": [_public_thing(thing) for thing in built["things"]],
        "hidden": built["hidden"],
        "solo_count": built["solo_count"],
        "solos": built["solos"],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="页面画第一份压缩包里弹幕最多的一条片子")
    parser.add_argument("zips", nargs=2, type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit-videos", type=int)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    left = load_zip(args.zips[0], args.limit_videos)
    right = load_zip(args.zips[1], args.limit_videos)
    print(f"{left.title} {len(left.videos)} 条视频，能定位 {len(left.rows)} 条", flush=True)
    print(f"{right.title} {len(right.videos)} 条视频，能定位 {len(right.rows)} 条", flush=True)
    report = build_report(left, right)
    shot = build_shot(max(left.videos, key=lambda video: (len(video.rows), video.bvid)))
    print(f"页面是 {shot['title']} ，能定位 {shot['n_rows']} 条", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    stored = {
        "left": _public_side(report["left"]),
        "right": _public_side(report["right"]),
        "match": report["match"],
        "readings": report["readings"],
        "note": report["note"],
        "method": report["method"],
    }
    (args.out / "report.json").write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "index.html").write_text(render_shot(shot), encoding="utf-8")
    for line in report["readings"]:
        print(line)
    print(args.out / "index.html")
    if args.serve:
        handler = lambda *a, **k: SimpleHTTPRequestHandler(*a, directory=str(args.out), **k)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
        print(f"http://127.0.0.1:{args.port}/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
