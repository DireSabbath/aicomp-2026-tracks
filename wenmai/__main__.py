"""文脉命令行。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wenmai.analyze import analyze
from wenmai.model import evaluation_report, public_metrics
from wenmai.render import render_file
from wenmai.resample import write_resample


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wenmai", description="传统文化弹幕六维读法")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("eval", help="在团队自写句子上评估规则和字符模型")

    analyze_parser = sub.add_parser("analyze", help="读本地弹幕池，写出不含正文的摘要")
    analyze_parser.add_argument("corpus", type=Path)
    analyze_parser.add_argument("--list", type=Path, default=None)
    analyze_parser.add_argument("--out", type=Path, required=True)

    render_parser = sub.add_parser("render", help="把摘要画成离线 HTML")
    render_parser.add_argument("summary", type=Path)
    render_parser.add_argument("--out", type=Path, required=True)

    resample_parser = sub.add_parser("resample", help="按视频重抽样，给抬升和符号绑定一个区间")
    resample_parser.add_argument("corpus", type=Path)
    resample_parser.add_argument("--list", type=Path, default=None)
    resample_parser.add_argument("--out", type=Path, required=True)
    resample_parser.add_argument("--draws", type=int, default=1000)
    resample_parser.add_argument("--seed", type=int, default=0)

    args = parser.parse_args(argv)
    if args.cmd == "eval":
        report = public_metrics(evaluation_report())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "resample":
        report = write_resample(args.corpus, args.list, args.out, draws=args.draws, seed=args.seed)
        print(
            json.dumps(
                {
                    "videos": report["videos"],
                    "draws": report["draws"],
                    "code_lifts": len(report["code_lifts"]),
                    "symbol_bindings": sum(1 for row in report["symbol_bindings"] if row["bound"]),
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.cmd == "analyze":
        summary = analyze(args.corpus, args.list, args.out)
        print(
            json.dumps(
                {
                    "videos": summary["videos"],
                    "pending": summary["pending"],
                    "danmaku": summary["danmaku"],
                    "coded_rate": summary["coded_rate"],
                    "out": str(args.out),
                },
                ensure_ascii=False,
            )
        )
        return 0
    render_file(args.summary, args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
