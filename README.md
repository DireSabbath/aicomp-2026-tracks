# 文脉：传统文化热门视频的弹幕六维读法

2026 AIC「AI+开源」作品。热门传统文化视频下的弹幕很多，人工按六维十七类来编码看不过来。这个仓库把码表做成可复算的流程：规则负责可解释的编码，字符模型对照规则还盖不住的说法，离线页面把时间、符号和载体分组画出来。

```bash
python -m wenmai eval
python -m unittest wenmai.test_wenmai
python danmaku/test_crawl.py
```

拉全量、出图和 GPU 微调见 [wenmai/README.md](wenmai/README.md)。技术报告在 [wenmai/技术报告.md](wenmai/技术报告.md)。赛题怎么读、作品对上哪一项评分、当前弹幕分析的完整清单在 [wenmai/赛题解读与分析清单.md](wenmai/赛题解读与分析清单.md)。选材规则在 [danmaku/SCOPE.md](danmaku/SCOPE.md)。

弹幕正文不进 git。`reception/` 是更早的民声试点，不再定义选材。

## 赛题资料

从 [aicomp.cn](https://www.aicomp.cn/) 保留算法主题赛中的 AI+开源，以及全大赛共用的章程、报名和宣传资料。

## 保留范围

| 范围 | 页面 | 说明 |
| --- | ---: | --- |
| AI+开源 | 2 | 赛题规则，以及通知、竞赛规则、技术报告大纲 |
| 通用资料 | 9 | 大赛概况、竞赛章程、第八届办赛通知、报名、对公转账、教师注册、赛区联系方式、宣传资料 |

## 目录

- `wenmai/`：码表、分析、可视化和报告
- `danmaku/`：爬取脚本和热门视频清单
- `data/catalog.json`：页面目录、联系方式、附件 URL
- `data/markdown/`：赛题正文
- `data/raw/`：原始 JSON

赛区组委会联系方式在官网是图片，本地文件为：

- `data/attachments/_files/2026年省级市级选拔赛赛区联系方式_01.png`
- `data/attachments/_files/2026年省级市级选拔赛赛区联系方式_00-1.png`

重新执行 `python scrape.py` 会再次抓取全部赛道。当前这份目录只应保留上述范围。
