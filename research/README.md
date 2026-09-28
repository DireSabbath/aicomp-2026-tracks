# 相关研究

这里聚合的是弹幕，以及任何程度相关的研究：视频弹幕论文、弹幕工具、平台公布的年度弹幕、niconico 视频网站、直播聊天、短文本和突发检测的方法源头。

聚合物是书目和链接。仓库不收录论文全文。

- 给人读的目录：[catalog.md](catalog.md)
- 同一份机器可读目录：[catalog.json](catalog.json)

可用的人、代理、数据、模型、接口和预算在仓库根目录的 [资源清单.md](../资源清单.md)。书目增加或删减，不改那份清单。

## 这次怎么收

检索日期是 2026-09-28。合计 469 条。`sweep` 里的 `direct_after_dedupe` 等是第一轮的数；补遗之后看 `total` 和 `current_counts`。

第一轮从 OpenAlex 下载了 1179 条去重后的记录。查询是题名或摘要里的 `danmaku`、`danmu`、`弹幕`，以及题名里的 `niconico`。摘要检索会把「弹」和「幕」拆开，命中导弹、幕墙、幕后和烟幕弹。题名里没有连续的弹幕、danmaku、danmu、bullet screen 或 time-sync 的记录没有写入目录。

第二轮用题名短语再查 `time-sync comment`、`time-synchronized comment`、`bullet comment` 和 `comment barrage`。去重前补入 77 条。拒绝了 42 条：混沌系统的 synchronization、法语里表示「怎样」的 comment 配上水坝 barrage，以及 silver bullet 一类说法。

写入「直接：视频弹幕」的条件是题名含上述词或短语，并且不是弹幕射击游戏，也不是中药胆木。同名异义排除了 12 条。同一 DOI，或同一题名加同一年，只留被引较高的一条。预印本和正式版本如果题名或年份不同，会各留一条。

题名不用这些词、但这次打开过页面的，另补在目录后部：DanmakuTPPBench、BERT-SVM 弹幕分析、弹幕工具、年度弹幕报道、BTM、突发主题、词汇规范化、Kleinberg 的流突发、AutoPhrase，以及 Twitch 聊天和表情。时间同步评论的高光论文已在第二轮题名里。没有打开过页面的论文不补进去。

这不是「世界上每一篇都已收齐」的证明。没写进目录的，只说明这次检索没有核到可引用的页面。

## 同日补遗

仓库仍然只收书目和链接。找思路时去读原文；原文不进仓库。

上次有 792 条因为题名里没有连续的弹幕、danmaku、danmu、bullet screen 或 time-sync 而被丢掉。这次重取了它们的 OpenAlex 摘要，其中 763 条摘要非空。摘要里若只是把哔哩哔哩称作弹幕站、把「弹幕」拆成导弹或幕墙、或把胆木写成 Danmu，不补。补入的是：研究对象就是盖在画面上或钉在时间上的评论，或者弹幕是被分析的数据，而不是一句话带过。

另外用 Crossref 对过几条题名不带 danmaku 的说法，补上了时间轴评论的可视化、2017 年的 DanMOOC，以及比较弹幕模式的一篇。Johnson 2013 的 niconico 评论流也在这批里。

打开并读过、但没有放进仓库的原文：VideoForest 的作者 PDF，Wu、Pitié 与 Jones 2021 的 Anthology PDF，Yu 与 Watts 2017 的巴斯大学 PDF，Zhang 等 2023 的 Frontiers PDF。其余补遗读的是 OpenAlex 或 Crossref 给出的摘要。Crossref 没有摘要、PDF 也没打开的，目录注里写明了。

OpenAlex 在后续请求里返回 429。因此这些还没扫完：`timed comments`、`time-synced`、`bullet-screen` 的全量结果、种子论文的施引和参考文献、2025 年以后的刷新，以及 arXiv。`Time-synchronized sentiment labeling via autonomous online comments data mining` 的摘要是空的，正文没打开，所以没有补。这次补了 47 条。

## 相关程度

| 标记 | 含义 |
| --- | --- |
| 直接：视频弹幕 | 对象是视频上的弹幕、飞过的评论或时间对齐的屏幕评论。题名可以不出现这些词；补遗的判断写在该条注里 |
| 工具与代码 | 处理弹幕的程序。许可证以各仓库当时的标注为准 |
| 平台公布 | 平台公布的年度弹幕次数，不是论文 |
| niconico 视频网站 | 弹幕界面的来源网站。这些条目不是中文弹幕语料论文 |
| 直播聊天 | Twitch 一类的同步聊天或表情 |
| 短文本、短语与突发方法的源头 | 微博、短信或一般文本上的方法。被弹幕论文引用过，不等于已经在弹幕上算出跨视频的结果 |
