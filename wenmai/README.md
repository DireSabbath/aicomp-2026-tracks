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

## 抬升的区间

全量点估计仍在 `analyze` 写出的摘要里。下面这条按有字的视频做放回重抽样，给已经跨过 1.3 倍的二级类、各维抬升和符号绑定一个 2.5% 到 97.5% 的区间。空池不进抽样框。

```bash
python -m wenmai resample danmaku_out/tradition-hot \
  --list danmaku/lists/tradition-hot/_videos.json \
  --out wenmai/results/resample.json
```

## 有 GPU 时

3090 24GB 上按约 3 小时排作业。种子 0 的主模型写 `metrics.json`：银标分数、核心句和难句的逐句差异、已编码弹幕相对规则的多标和漏标、与分析相同的那 1,500 条缺口的各类次数。离阈值最近的未编码句子写到输出目录的 `margin-queue.json`：`rows` 是全局最近的，`per_code` 是每个类自己最近的，避免稀有类被挤掉。全量前向的 batch 在 24GB 上用 256，训练 batch 仍是 16。后续作业按训练循环本身的耗时来估，不把第一次下载权重的时间乘进大模型。CUDA 上会先把这几份权重下到本机缓存，下载失败也不中断。

预算里接着各跑一轮 `hfl/chinese-macbert-large` 和 `hfl/chinese-roberta-wwm-ext` 的全量对照，其余时间重复主模型的种子。范围写在 `budget.json`。报告只采用主模型种子 0。重复种子的权重不保存。这些分数对照的是码表，不是人工金标，也不替换页面上的规则计数。

```bash
pip install -r wenmai/requirements-gpu.txt
python -m wenmai.train_gpu --data wenmai/sample_silver.jsonl --out /tmp/wenmai-gpu-smoke --cpu --epochs 1
python -m wenmai.train_gpu \
  --data wenmai/results/silver.jsonl \
  --out danmaku_out/gpu-model \
  --model hfl/chinese-macbert-base \
  --epochs 2 \
  --hours 3 \
  --corpus danmaku_out/tradition-hot \
  --list danmaku/lists/tradition-hot/_videos.json
```

没有 CUDA 且不加 `--cpu` 时，脚本会退出并说明要接到 GPU。`--hours` 只在 CUDA 上继续排后续作业。`--check` 只核对银标格式，不加载模型。`sample_silver.jsonl` 是自写样例。真实银标写在 `analyze --out` 那个目录的 `silver.jsonl`，上面的分析命令会把它放在 `wenmai/results/`。权重、缺口原文和边际清单都不要提交。

## 目录

| 文件 | 作用 |
| --- | --- |
| `codebook.py` | 六维十七类、符号词表、短语 |
| `classify.py` | 规则多标签 |
| `model.py` | 字符 n-gram 逻辑回归，只依赖 numpy |
| `analyze.py` | 时间曲线、承接、抬升、二级类签名、停留、组间残差、集中度、共现、点互信息、符号绑定、单片卡片、规则缺口计数、稀有类支撑、突发、银标抽样 |
| `resample.py` | 按有字的视频放回重抽样，给抬升和符号绑定一个区间 |
| `budget.py` | 按显存和墙钟排列编码器对照，不加载模型 |
| `render.py` | 离线 HTML |
| `train_gpu.py` | 可选的开源中文编码器微调，3090 上可用 `--hours 3` |
| `gold.json` | 自写核心句和难句 |
| `技术报告.md` | 按赛题大纲写的说明 |
| `技术报告.pdf` | 提交用 PDF，由 `export_report.py` 从上一份稿导出 |
| `export_report.py` | 把技术报告印成 A4 PDF，并单独数正文页 |
| `赛题解读与分析清单.md` | 赛题解读、评分对应，以及当前弹幕分析的完整清单 |
