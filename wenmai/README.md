# 文脉

传统文化热门视频的弹幕六维读法。码表、规则、字符模型和离线可视化都在这个目录。许可证是 [MIT](LICENSE)。

弹幕正文不在这里。本地分析如果写出 `silver.jsonl` 或 `exemplars.jsonl`，那是抽样原文，不要提交。

## 先跑通，不需要弹幕

```bash
python -m wenmai eval
python -m unittest wenmai.test_wenmai
python danmaku/test_crawl.py
```

`eval` 在团队自写的 33 条核心句和 8 条难句上比较规则与字符模型。核心句用来锁住十七类的操作化定义。难句是规则故意还盖不住的说法。

## 拉弹幕，再出图

选材规则在 [../danmaku/SCOPE.md](../danmaku/SCOPE.md)。

```bash
python danmaku/crawl.py --collections danmaku/collections.json --list-only --out danmaku/lists
python danmaku/crawl.py --collections danmaku/collections.json --out danmaku_out --delay 0.35
python -m wenmai analyze danmaku_out/tradition-hot \
  --list danmaku/lists/tradition-hot/_videos.json \
  --out wenmai/results
python -m wenmai render wenmai/results/summary.json --out wenmai/results/index.html
```

`wenmai/results/summary.json` 和 `index.html` 里没有弹幕原文。用浏览器直接打开 HTML。

中断后重跑爬取会跳过已经写好的视频。列清单时会把进度写进 `_partial.json`，重跑同一条命令会从断点继续。

## 有 GPU 时

```bash
pip install -r wenmai/requirements-gpu.txt
python -m wenmai.train_gpu --data wenmai/sample_silver.jsonl --out /tmp/wenmai-gpu-smoke --cpu --epochs 1
python -m wenmai.train_gpu \
  --data wenmai/results/silver.jsonl \
  --out danmaku_out/gpu-model \
  --model hfl/chinese-macbert-base \
  --epochs 2
```

没有 CUDA 且不加 `--cpu` 时，脚本会退出并说明要接到 GPU。`--check` 只核对银标格式，不加载模型。`sample_silver.jsonl` 是自写样例。真实银标写在 `analyze --out` 那个目录的 `silver.jsonl`，上面的分析命令会把它放在 `wenmai/results/`。默认模型是 `hfl/chinese-macbert-base`。阈值按类在训练集上搜索，并在 33 条核心句和 8 条难句上另算分数。这两份分数对照的是码表，不是人工抽检的弹幕。权重不要提交。

## 目录

| 文件 | 作用 |
| --- | --- |
| `codebook.py` | 六维十七类、符号词表、短语 |
| `classify.py` | 规则多标签 |
| `model.py` | 字符 n-gram 逻辑回归，只依赖 numpy |
| `analyze.py` | 时间曲线、承接、抬升、二级类签名、停留、组间残差、集中度、共现、点互信息、符号绑定、单片卡片、规则缺口计数、稀有类支撑、突发、银标抽样 |
| `render.py` | 离线 HTML |
| `train_gpu.py` | 可选的开源中文编码器微调 |
| `gold.json` | 自写核心句和难句 |
| `技术报告.md` | 按赛题大纲写的说明 |
