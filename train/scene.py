"""把直播回放收成可以交给 GPU 训练的画面材料。

这条片子是《黑神话：悟空》首次线下试玩现场直播回放，BV19p4y1J7AH，约 122 分钟。
压缩包里没有画面。脚本负责下载、抽帧，并写好 nerfstudio 的两条训练命令：
高斯泼溅 splatfacto，以及 NeRF 的 nerfacto。权重不在这里生成。
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

FILM_BVID = "BV19p4y1J7AH"
FILM_TITLE = "《黑神话：悟空》首次线下试玩现场直播回放"
FILM_SECONDS = 7351
FRAME_TARGET = 400


def video_url(bvid: str) -> str:
    return f"https://www.bilibili.com/video/{bvid}/"


def fetch_video(bvid: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "video.mp4"
    if target.exists() and target.stat().st_size > 0:
        return target
    if shutil.which("yt-dlp") is None:
        raise SystemExit("还没有 yt-dlp。安装之后再执行同一条命令，画面会下到 train_out，不进 git。")
    subprocess.run(
        ["yt-dlp", "-f", "bv*+ba/b", "--merge-output-format", "mp4", "-o", str(target), video_url(bvid)],
        check=True,
    )
    if not target.exists():
        raise SystemExit("yt-dlp 跑完了，但是没有留下 video.mp4。")
    return target


def extract_frames(video: Path, images: Path, *, fps: float = 1.0) -> int:
    if not video.exists():
        raise SystemExit(f"没有画面文件：{video}")
    images.mkdir(parents=True, exist_ok=True)
    for old in images.glob("*.jpg"):
        old.unlink()
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"fps={fps},scale=960:-2",
            str(images / "%06d.jpg"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return len(list(images.glob("*.jpg")))


def gpu_job(video: Path, out_dir: Path, *, bvid: str = FILM_BVID) -> dict:
    processed = out_dir / "processed"
    process = (
        "ns-process-data video --data "
        + shlex.quote(str(video))
        + " --output-dir "
        + shlex.quote(str(processed))
        + f" --num-frames-target {FRAME_TARGET}"
    )
    return {
        "trained": False,
        "needs_gpu": True,
        "bvid": bvid,
        "title": FILM_TITLE,
        "seconds": FILM_SECONDS,
        "video": str(video),
        "video_present": video.exists(),
        "frames": len(list((out_dir / "images").glob("*.jpg"))) if (out_dir / "images").exists() else 0,
        "commands": [
            process,
            "ns-train splatfacto --data " + shlex.quote(str(processed)),
            "ns-train nerfacto --data " + shlex.quote(str(processed)),
        ],
        "tools": {
            "yt-dlp": shutil.which("yt-dlp") is not None,
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "ns-process-data": shutil.which("ns-process-data") is not None,
            "ns-train": shutil.which("ns-train") is not None,
        },
        "note": (
            "直播回放不是绕着物体拍的一组照片。COLMAP 若对不齐机位，高斯泼溅和 NeRF 都训不出来。"
            "这里只把视频、抽帧和训练命令备好，没有权重。"
        ),
    }


def write_job(out_dir: Path, *, bvid: str = FILM_BVID) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = gpu_job(out_dir / "video.mp4", out_dir, bvid=bvid)
    (out_dir / "gpu_job.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def launch(out_dir: Path) -> None:
    payload = write_job(out_dir)
    if not payload["video_present"]:
        raise SystemExit("还没有 video.mp4。先执行 train scene fetch。")
    if not payload["tools"]["ns-train"] or not payload["tools"]["ns-process-data"]:
        raise SystemExit("GPU 机器上还没有 nerfstudio。装好之后执行 gpu_job.json 里的三条命令。")
    for command in payload["commands"]:
        subprocess.run(command, shell=True, check=True)
