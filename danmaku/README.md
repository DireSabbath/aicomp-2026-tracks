# 弹幕爬取

通用脚本 `crawl.py` 拉取 B 站播放器当前公开弹幕池的全部分段。每段 6 分钟，接口是 `https://api.bilibili.com/x/v2/dm/web/seg.so`。脚本保存的是现在播放器里的那一池，同一条不重复写入。页面上的累计条数可以更大。一段里没有弹幕时仍会继续拉后面的段，避免把后半段丢掉。

每条记录有：`id`、`progress_ms`（视频内毫秒）、`timeline_ms`（多分P时按前几P的时长接上）、`mode`、`content`、`ctime`（发送时间，接口有则保留）、`cid`、`page`。用户标识 `midHash` 不写入。

## 当前选材

只有 `collections.json` 里的 `tradition-hot`：传统文化热门视频。规则、阈值和五组载体写在 [SCOPE.md](SCOPE.md)。

先前的罗翔说刑法、原神前瞻、吐槽新三国、小约翰可汗、黑神话官方、郭律说刑事、罗翔直播课堂都已从清单里移出，不再作为这套作品的语料。

## 用法

```bash
python danmaku/test_crawl.py
python danmaku/crawl.py --bvid BV1BK411L7DJ --out danmaku_out
python danmaku/crawl.py --collections danmaku/collections.json --list-only --out danmaku/lists
python danmaku/crawl.py --collections danmaku/collections.json --out danmaku_out
```

`danmaku/lists/` 里是已经列好的视频。爬取默认读这份清单。`--refresh-list` 会丢掉清单，重新向接口要列表。中断后重跑会跳过已经写好的视频。列清单中断时，`--list-only` 会接着 `_partial.json` 里已经完成的检索词继续。弹幕输出在 `danmaku_out/`，不进 git。每个视频一个 `.jsonl.gz`，合集汇总是 `_collection.json`。

脚本不限主题。`--bvid` 可以拉任意视频。当前仓库要回答的问题只用上面这一份热门传统文化清单。

`hot_search` 走 `https://api.bilibili.com/x/web-interface/search/type`，按页面弹幕计数从高到低翻页。某一页第一条已经低于该词阈值就停止。合集分页仍会向 `finger/spi` 要匿名 buvid。搜索不带这枚 cookie。不保存登录态。

分析入口在 [../wenmai/README.md](../wenmai/README.md)。

`pool_structure.py` 只统计时间结构，不打印正文：

```bash
python danmaku/pool_structure.py danmaku_out/tradition-hot.zip
python danmaku/test_pool_structure.py
```
