"""python -m train prepare|vectors|topics|sentiment|scene

正文写到 --out 指向的目录，不进 git。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from train.corpus import write_comments
from train.scene import FILM_BVID, extract_frames, fetch_video, launch, write_job
from train.sentiment import write_sentiment
from train.topics import write_topics
from train.vectors import write_vectors


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="把弹幕训练备到接上 CPU 或 GPU 就能开训")
    sub = parser.add_subparsers(dest="cmd", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("zips", nargs="+", type=Path)
    prepare.add_argument("--out", type=Path, required=True)

    vectors = sub.add_parser("vectors")
    vectors.add_argument("comments", type=Path)
    vectors.add_argument("--out", type=Path, required=True)
    vectors.add_argument("--dim", type=int, default=64)
    vectors.add_argument("--epochs", type=int, default=5)
    vectors.add_argument("--min-count", type=int, default=5)

    topics = sub.add_parser("topics")
    topics.add_argument("comments", type=Path)
    topics.add_argument("--out", type=Path, required=True)
    topics.add_argument("--topics", type=int, default=12)
    topics.add_argument("--iters", type=int, default=30)
    topics.add_argument("--min-count", type=int, default=5)

    sentiment = sub.add_parser("sentiment")
    sentiment.add_argument("comments", type=Path)
    sentiment.add_argument("--out", type=Path, required=True)
    sentiment.add_argument("--labels", type=Path)

    scene = sub.add_parser("scene")
    scene.add_argument("action", choices=("job", "fetch", "frames", "launch"))
    scene.add_argument("--out", type=Path, required=True)
    scene.add_argument("--bvid", default=FILM_BVID)
    scene.add_argument("--fps", type=float, default=1.0)

    args = parser.parse_args(argv)
    if args.cmd == "prepare":
        manifest = write_comments(args.zips, args.out)
        print(f"写出 {manifest['rows']} 条到 {args.out / 'comments.jsonl'}", flush=True)
        return
    if args.cmd == "vectors":
        payload = write_vectors(args.comments, args.out, dim=args.dim, epochs=args.epochs, min_count=args.min_count)
        print(f"词表 {payload['vocab']}，近邻 {len(payload['pairs'])} 对", flush=True)
        return
    if args.cmd == "topics":
        payload = write_topics(args.comments, args.out, n_topics=args.topics, iters=args.iters, min_count=args.min_count)
        print(f"主题 {len(payload['topics'])} 个，用了 {payload['docs']} 条短文本", flush=True)
        return
    if args.cmd == "sentiment":
        payload = write_sentiment(args.comments, args.out, labels_path=args.labels)
        print(f"标签来源 {payload['label_source']}，{payload['counts']}", flush=True)
        return
    if args.action == "job":
        payload = write_job(args.out, bvid=args.bvid)
        print(payload["note"], flush=True)
        return
    if args.action == "fetch":
        path = fetch_video(args.bvid, args.out)
        print(path, flush=True)
        return
    if args.action == "frames":
        count = extract_frames(args.out / "video.mp4", args.out / "images", fps=args.fps)
        write_job(args.out, bvid=args.bvid)
        print(f"抽出 {count} 帧", flush=True)
        return
    launch(args.out)


if __name__ == "__main__":
    main()
