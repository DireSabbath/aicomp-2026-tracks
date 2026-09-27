import argparse
import json
from pathlib import Path

from shuofa.baseline import split_report
from shuofa.label import ONLY_HERE, collection_name
from shuofa.scan import read_meta, scan_circles, scan_video
from shuofa.textutil import default_lexicon, load_lexicon


def _lexicon(path: str | None):
    return load_lexicon(Path(path) if path else default_lexicon())


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _print_circle(payload: dict) -> None:
    for row in payload["families"]:
        print(f"\n{row['name']}  {row['label']}")
        if row["home_name"]:
            print(f"  主要在：{row['home_name']}")
        for item in row["rates"].values():
            percent = round(item["rate"] * 100)
            print(f"  {item['name']}  {item['hit']}/{item['total']}  {percent}%")
        forms = "；".join(form["text"] for form in row["forms"][:4])
        if forms:
            print(f"  写法：{forms}")


def _print_video(title: str, payload: dict) -> None:
    print(title)
    if not payload["rows"]:
        print("词表里的句子，这条视频里没有出现。")
        return
    for row in payload["rows"]:
        print(f"\n{row['name']}")
        peak = row["peak"]
        if peak and peak.get("held"):
            start = peak["start_ms"] / 1000
            end = peak["end_ms"] / 1000
            share = round(peak["share"] * 100)
            print(f"  卡在：{start:.0f}–{end:.0f} 秒（这一句里 {share}% 落在这 5 秒）")
        elif peak:
            start = peak["start_ms"] / 1000
            end = peak["end_ms"] / 1000
            share = round(peak["share"] * 100)
            print(f"  卡在：聚不拢。最密的 5 秒是 {start:.0f}–{end:.0f} 秒，只占 {share}%")
        else:
            print("  卡在：有进度的句子太少，写不出段落")
        forms = "；".join(form["text"] for form in row["forms"])
        print(f"  写法：{forms}")
        label = row.get("label")
        if label == ONLY_HERE:
            print(f"  是不是只有这个圈子：是，主要在{row.get('home_name')}")
        elif label:
            names = []
            for item in (row.get("rates") or {}).values():
                if item["rate"] >= 0.10:
                    names.append(item["name"])
            where = "、".join(names) if names else "多套片子"
            print(f"  是不是只有这个圈子：{label}（{where}）")
        else:
            print("  是不是只有这个圈子：先跑五套圈子的统计")


def cmd_circle(args: argparse.Namespace) -> None:
    payload = scan_circles(Path(args.root), _lexicon(args.lexicon))
    _write(Path(args.out), payload)
    _print_circle(payload)
    print(f"\n写入 {args.out}")


def cmd_video(args: argparse.Namespace) -> None:
    circle_path = Path(args.circle)
    circle = json.loads(circle_path.read_text(encoding="utf-8")) if circle_path.exists() else None
    gz_path = Path(args.gz)
    payload = scan_video(gz_path, _lexicon(args.lexicon), circle)
    meta_path = Path(args.meta) if args.meta else gz_path.with_name(gz_path.name.replace(".jsonl.gz", ".meta.json"))
    title = gz_path.name
    if meta_path.exists():
        meta = read_meta(meta_path)
        title = f"{meta.get('title') or title}  {meta.get('bvid') or ''}"
    if args.out:
        _write(Path(args.out), {"title": title.strip(), **payload})
    _print_video(title.strip(), payload)


def cmd_baseline(args: argparse.Namespace) -> None:
    families = _lexicon(args.lexicon)
    forms = []
    for family in families:
        if args.family and family["id"] != args.family and family["name"] != args.family:
            continue
        for variant in family["variants"]:
            forms.append(variant["text"])
        report = split_report([variant["text"] for variant in family["variants"]])
        print(f"\n{family['name']}")
        for row in report["rows"]:
            print(f"  {row['form']}  →  {' / '.join(row['tokens'])}")
        if report["different_cuts"]:
            print("  常规分词把这些写法拆成了不同的词")
        elif report["forms"] > 1:
            print("  这些写法字面不同，按词频会分成几条")
    if not forms:
        raise SystemExit("词表里没有这句")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="留下一份圈子说法记录。弹幕原文不进仓库。")
    parser.add_argument("--lexicon", help="说法词表。缺省用仓库里的词表")
    sub = parser.add_subparsers(dest="cmd", required=True)

    circle = sub.add_parser("circle", help="五套放在一起，判断每句是不是只有这个圈子在说")
    circle.add_argument("--root", default="danmaku_out")
    circle.add_argument("--out", default="shuofa_out/circle.json")
    circle.set_defaults(func=cmd_circle)

    video = sub.add_parser("video", help="一条视频上，写出卡在哪一段、有哪些写法")
    video.add_argument("--gz", required=True)
    video.add_argument("--meta")
    video.add_argument("--circle", default="shuofa_out/circle.json")
    video.add_argument("--out")
    video.set_defaults(func=cmd_video)

    baseline = sub.add_parser("baseline", help="给常规分词看同一句的不同写法")
    baseline.add_argument("--family", help="只看这一句。缺省看词表里的全部")
    baseline.set_defaults(func=cmd_baseline)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
