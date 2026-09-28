# 相关研究

这里聚合的是弹幕，以及任何程度相关的研究：视频弹幕论文、弹幕工具、平台公布的年度弹幕、niconico 视频网站、直播聊天、短文本和突发检测的方法源头。

聚合物是书目和链接。仓库不收录论文全文。

- 给人读的目录：[catalog.md](catalog.md)
- 同一份机器可读目录：[catalog.json](catalog.json)

可用的人、代理、数据、模型、接口和预算在仓库根目录的 [资源清单.md](../资源清单.md)。书目增加或删减，不改那份清单。

## 这次怎么收

检索日期是 2026-09-28。合计 588 条。`sweep` 里的 `direct_after_dedupe`、`rescan_added` 等是前两轮留下的数；当前条目看 `total` 和 `current_counts`。

第一轮从 OpenAlex 下载了 1179 条去重后的记录。查询是题名或摘要里的 `danmaku`、`danmu`、`弹幕`，以及题名里的 `niconico`。摘要检索会把「弹」和「幕」拆开，命中导弹、幕墙、幕后和烟幕弹。题名里没有连续的弹幕、danmaku、danmu、bullet screen 或 time-sync 的记录没有写入目录。

第二轮用题名短语再查 `time-sync comment`、`time-synchronized comment`、`bullet comment` 和 `comment barrage`。去重前补入 77 条。拒绝了 42 条：混沌系统的 synchronization、法语里表示「怎样」的 comment 配上水坝 barrage，以及 silver bullet 一类说法。

第一轮写入「直接：视频弹幕」的条件是题名含上述词或短语，并且不是弹幕射击游戏，也不是中药胆木。补遗两轮改看对象：盖在画面上或钉在时间上的评论，题名里可以没有这些词。同名异义排除了 12 条。同一 DOI，或同一题名加同一年，只留被引较高的一条。预印本和正式版本如果题名或年份不同，会各留一条。

题名不用这些词、但这次打开过页面的，另补在目录后部：DanmakuTPPBench、BERT-SVM 弹幕分析、弹幕工具、年度弹幕报道、BTM、突发主题、词汇规范化、Kleinberg 的流突发、AutoPhrase，以及 Twitch 聊天和表情。时间同步评论的高光论文已在第二轮题名里。没有打开过页面的论文不补进去。

这不是「世界上每一篇都已收齐」的证明。没写进目录的，只说明这次检索没有核到可引用的页面。

## 同日补遗

仓库仍然只收书目和链接。找思路时去读原文；原文不进仓库。目录里的注是判断，不是摘要抄录。

第一轮补遗 47 条。上次有 792 条因为题名里没有连续的弹幕、danmaku、danmu、bullet screen 或 time-sync 而被丢掉。重取了它们的 OpenAlex 摘要，其中 763 条摘要非空。摘要里若只是把哔哩哔哩称作弹幕站、把「弹幕」拆成导弹或幕墙、或把胆木写成 Danmu，不补。补入的是：研究对象就是盖在画面上或钉在时间上的评论，或者弹幕是被分析的数据，而不是一句话带过。Crossref 另补了时间轴评论的可视化、2017 年的 DanMOOC、比较弹幕模式的一篇，以及 Johnson 2013 的 niconico 评论流。打开并读过、但没有放进仓库的原文：VideoForest 的作者 PDF，Wu、Pitié 与 Jones 2021 的 Anthology PDF，Yu 与 Watts 2017 的巴斯大学 PDF，Zhang 等 2023 的 Frontiers PDF。

第二轮补遗 119 条。第一轮的题名短语把 bullet screen、barrage、bullet chat 拆开了，所以「bullet screen」论文大多不在最初的 1179 条里。这轮按题名再查并看完返回的全部结果：bullet screen 178 条，on-screen 72 条，timeline 24 条，nicovideo 14 条，acfun 11 条，overlaid 6 条，scrolling 12 条，overlay 3 条，2025-09-01 之后的 danmaku 78 条。题名检索另查完：bullet chat 15 条，bullet chats 11 条，video barrage 6 条，bullet-titling 5 条，flying comment 0 条，timed comment 81 条，time-synced 60 条。施引也翻完：Cassany 等 2020 的 106 条，Johnson 2013 的 108 条，Wu 等 2017 的 60 条，DanmuVis 的 10 条。`live comments` 的题名加摘要检索共 118 条，题名都看过；排在前 100 之后的 18 条题名与屏幕评论无关。arXiv 网页检索看过 danmaku、danmu、bullet screen 和 time-synced comment；导出接口返回 406，没有再用。GitHub 上仓库名含 danmaku 的检索返回 2002 个。这轮只打开了绘制引擎和格式转换四条：DanmakuFlameMaster、weizhenye/Danmaku、danmaku2ass、DanmakuFactory。停更仓库、播放器插件和界面组件没有逐个打开，所以没有补。

这轮读的是 OpenAlex 摘要或 arXiv 摘要页。摘要空、正文又没打开的，目录注里写明了，只在题名已经写明对象时才补。没有补进目录的包括：ACFun 只是面部风格化的缩写；弹幕射击游戏；无线传感器和 Amazon Time Sync 一类时间同步协议；SoundCloud 上给音乐片段贴的标签；元宇宙接受度论文只是把哔哩哔哩当作数据来源；Marketing Science 那篇电影 live comments 的摘要只有一句话，没有写覆盖画面；心外科教学片里的讲解、足球解说生成、奥斯卡 YouTube 直播评论、会议听众评论、BBS 上的电视评论。`Time-synchronized sentiment labeling via autonomous online comments data mining`（10.1016/j.bdr.2025.100552）摘要是空的，没有打开到正文，所以没有补。预印本和勘误并进正式版本的「另见」，不另立一条。

## 相关程度

| 标记 | 含义 |
| --- | --- |
| 直接：视频弹幕 | 对象是视频上的弹幕、飞过的评论或时间对齐的屏幕评论。题名可以不出现这些词；补遗的判断写在该条注里 |
| 工具与代码 | 处理弹幕的程序。许可证以各仓库当时的标注为准 |
| 平台公布 | 平台公布的年度弹幕次数，不是论文 |
| niconico 视频网站 | 弹幕界面的来源网站。这些条目不是中文弹幕语料论文 |
| 直播聊天 | Twitch 一类的同步聊天或表情 |
| 短文本、短语与突发方法的源头 | 微博、短信或一般文本上的方法。被弹幕论文引用过，不等于已经在弹幕上算出跨视频的结果 |
