"""从两个压缩包生成演示页，并可在本地打开。

    python -m briefing /path/heishenhua.zip /path/yuanshen-preview.zip --out demo_out --serve
"""

from __future__ import annotations

import argparse
import functools
import http.server
from pathlib import Path

from briefing.load import load_zip
from briefing.report import build_report, write_demo

_TITLES = {
    "heishenhua": ("heishenhua", "黑神话官方"),
    "yuanshen-preview": ("yuanshen-preview", "原神前瞻特别节目"),
}


def _identity(path: Path) -> tuple[str, str]:
    stem = path.stem
    if stem in _TITLES:
        return _TITLES[stem]
    return stem, stem


def build(paths: list[Path], out_dir: Path) -> dict:
    types = []
    for path in paths:
        type_id, title = _identity(path)
        types.append((type_id, title, load_zip(str(path))))
    report = build_report(types)
    write_demo(report, out_dir)
    return report


def serve(out_dir: Path, port: int) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"http://127.0.0.1:{port}/", flush=True)
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成两个类型的弹幕接收结构演示")
    parser.add_argument("zips", nargs="+", type=Path, help="两个已爬取的弹幕压缩包")
    parser.add_argument("--out", type=Path, default=Path("demo_out"))
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if len(args.zips) != 2:
        parser.error("需要两个压缩包")
    report = build(args.zips, args.out)
    for item in report["types"]:
        print(
            f"{item['title']}\t视频{item['n_videos']}\t弹幕{item['n_rows']}\t说法{len(item['claims'])}",
            flush=True,
        )
    print(f"写入 {args.out / 'index.html'}", flush=True)
    if args.serve:
        serve(args.out, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
