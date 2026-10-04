# 接到 CPU 或 GPU 就能开训

弹幕正文从本地压缩包读出，写到 `train_out/`，不进 git。发布包的校验和必须和 `danmaku/lists/release-sha256.txt` 一致。材料里没有发言者，导出的行里也不写弹幕 id。

先准备语料：

```bash
python -m train prepare /path/heishenhua.zip --out train_out/heishenhua
```

五个包可以一次放进同一条命令。未知文件名不会因为校验和缺失而停；五个已发布的文件名如果校验和对不上，会停。

## 字块向量（CPU）

同一条评论里的二字到四字块互相做上下文，跳元负采样。拿来建议并句的近邻只留二字对二字、三字对三字，余弦不低于 0.72，不能共用一个二字片段，也不能总在同一条评论里出现。这样会去掉「舌尖上 / 尖上的」这种同一句切开的碎片。悟空和大圣会不会并成一句，由这次训出来的数决定，程序里没有同义词表。

词表打出来的负向在这批包里很少，分类器会偏向中性。要能用的情感，换上人工标签再训。

```bash
python -m train vectors train_out/heishenhua/comments.jsonl --out train_out/heishenhua/vectors
```

## 情感分类器（CPU）

三类：正、负、中性。压缩包里没有情感标签。不加 `--labels` 时，用 `train/sentiment.py` 里写明的词表打弱标签再训线性分类器。`sentiment.json` 里 `human_checked` 为 false。

人工标签是一行一个 JSON，字段是 `text` 和 `label`（正、负、中性）。换上之后用同一条命令重训：

```bash
python -m train sentiment train_out/heishenhua/comments.jsonl --out train_out/heishenhua/sentiment
python -m train sentiment train_out/heishenhua/comments.jsonl --labels labels.jsonl --out train_out/heishenhua/sentiment
```

## 短文本主题（CPU）

BTM：同一条弹幕里的二字块组成词对，吉布斯抽样。不按整篇文档估主题。

```bash
python -m train topics train_out/heishenhua/comments.jsonl --out train_out/heishenhua/topics
```

## 直播画面的三维（GPU）

片子是 BV19p4y1J7AH，约 122 分钟。压缩包里没有画面。下载和抽帧可以在 CPU 上做；高斯泼溅和 NeRF 要在装了 nerfstudio 的 GPU 机器上开训。直播机位不是绕着物体拍的，COLMAP 对不齐时这两条会失败。失败也不是已经训完。

```bash
python -m train scene job --out train_out/scene
python -m train scene fetch --out train_out/scene
python -m train scene frames --out train_out/scene
```

`gpu_job.json` 里 `trained` 固定是 false，并写着三条命令：`ns-process-data video`（抽约 400 帧做位姿），`ns-train splatfacto`，`ns-train nerfacto`。工具都在 PATH 里之后：

```bash
python -m train scene launch --out train_out/scene
```

画面文件不进 git。需要 `ffmpeg` 和 `yt-dlp`。GPU 机器另装 nerfstudio，不写进仓库依赖。
