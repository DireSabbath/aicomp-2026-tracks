# 弹幕爬取

通用脚本 `crawl.py` 拉取 B 站播放器当前公开弹幕池的全部分段。每段 6 分钟，接口是 `https://api.bilibili.com/x/v2/dm/web/seg.so`。

历史弹幕接口会返回「账号未登录」。视频页面上的累计弹幕数因此大于这里的条数。脚本保存的是现在还能拉下来的那一池，同一条不重复写入。

每条记录有：`id`、`progress_ms`（视频内毫秒）、`mode`、`content`、`ctime`（发送时间，接口有则保留）、`cid`、`page`。用户标识 `midHash` 不写入。

## 用法

```bash
python danmaku/test_crawl.py
python danmaku/crawl.py --bvid BV1BK411L7DJ --out danmaku_out
python danmaku/crawl.py --collections danmaku/collections.json --list-only --out danmaku/lists
python danmaku/crawl.py --collections danmaku/collections.json --out danmaku_out
python danmaku/crawl.py --collections danmaku/collections.json --only yuanshen-preview --limit 2
```

`danmaku/lists/` 里是已经列好的视频。爬取默认读这份清单。`--refresh-list` 会丢掉清单，重新向接口要列表。中断后重跑会跳过已经写好的视频。弹幕输出在 `danmaku_out/`，不进 git。每个视频一个 `.jsonl.gz`，合集汇总是 `_collection.json`。

`collections.json` 里的五套是：罗翔说刑法（账号合集、系列，加上搜索里这个账号的视频）、原神官方标题含「前瞻」的视频、吃蛋挞的折棒「吐槽新三国」合集、小约翰可汗四个专栏、黑神话官方合集及搜索到的该账号视频。

脚本启动时向 `finger/spi` 要一个匿名 buvid，合集分页不带它会返回 -352。不保存登录态。空间投稿搜索在部分网络下会返回 -412，所以全账号列表走合集和站内搜索，不走那个接口。
