# 2026 AIC：AI+开源与通用资料

从 [aicomp.cn](https://www.aicomp.cn/) 保留算法主题赛中的 AI+开源，以及全大赛共用的章程、报名和宣传资料。

## 保留范围

| 范围 | 页面 | 说明 |
| --- | ---: | --- |
| AI+开源 | 2 | 赛题规则，以及通知、竞赛规则、技术报告大纲 |
| 通用资料 | 9 | 大赛概况、竞赛章程、第八届办赛通知、报名、对公转账、教师注册、赛区联系方式、宣传资料 |

## 目录

- `data/catalog.json`：页面目录、联系方式、附件 URL
- `data/markdown/`：正文
- `data/raw/`：原始 JSON
- `data/attachments/_files/`：PDF、图片和宣传压缩包
- `视频主题筛选.md`：按演示视频要求和评分细则筛过的选题

赛区组委会联系方式在官网是图片，本地文件为：

- `data/attachments/_files/2026年省级市级选拔赛赛区联系方式_01.png`
- `data/attachments/_files/2026年省级市级选拔赛赛区联系方式_00-1.png`

重新执行 `python scrape.py` 会再次抓取全部赛道。当前这份目录只应保留上述范围。
