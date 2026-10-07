import unittest

from crawl import (
    BilibiliClient,
    bv_to_aid,
    decode_danmaku_segment,
    prune_hot_videos,
    resolve_collection,
    segment_count_from_view,
    video_in_scope,
)


def encode_varint(number: int) -> bytes:
    out = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        if number:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def encode_elem(content: str, progress: int, danmaku_id: int) -> bytes:
    text = content.encode()
    return b"".join(
        [
            encode_varint((1 << 3) | 2),
            encode_varint(
                len(
                    body := b"".join(
                        [
                            encode_varint((1 << 3) | 0),
                            encode_varint(danmaku_id),
                            encode_varint((2 << 3) | 0),
                            encode_varint(progress),
                            encode_varint((7 << 3) | 2),
                            encode_varint(len(text)),
                            text,
                        ]
                    )
                )
            ),
            body,
        ]
    )


class DecodeTests(unittest.TestCase):
    def test_bv_to_aid(self):
        self.assertEqual(bv_to_aid("BV1BK411L7DJ"), 497651138)

    def test_roundtrip_segment(self):
        blob = encode_elem("???", 40000, 99) + encode_elem("????", 40100, 100)
        rows = decode_danmaku_segment(blob)
        self.assertEqual([row["content"] for row in rows], ["???", "????"])
        self.assertEqual(rows[0]["progress_ms"], 40000)
        self.assertEqual(rows[1]["id"], 100)

    def test_listed_collection_keeps_the_given_videos(self):
        videos = resolve_collection(
            None,
            {"mid": 1, "list": "listed", "videos": [{"bvid": "BV1", "aid": 2, "title": "甲"}]},
        )
        self.assertEqual(videos, [{"bvid": "BV1", "aid": 2, "title": "甲"}])

    def test_segment_count(self):
        inner = encode_varint((2 << 3) | 0) + encode_varint(3)
        blob = encode_varint((4 << 3) | 2) + encode_varint(len(inner)) + inner
        self.assertEqual(segment_count_from_view(blob), 3)


class ScopeTests(unittest.TestCase):
    def test_scope_cleans_title_and_applies_filters(self):
        self.assertTrue(
            video_in_scope(
                '<em class="keyword">国家宝藏</em>第一期',
                1000,
                min_danmaku=1000,
                title_contains="国家宝藏",
                title_any=None,
                title_exclude=["原神"],
            )
        )
        self.assertFalse(
            video_in_scope(
                "原神里的国家宝藏",
                9000,
                min_danmaku=1000,
                title_contains="国家宝藏",
                title_any=None,
                title_exclude=["原神"],
            )
        )
        self.assertFalse(
            video_in_scope(
                "敦煌旅行日记",
                8000,
                min_danmaku=1000,
                title_contains="敦煌",
                title_any=["壁画", "莫高"],
                title_exclude=[],
            )
        )
        self.assertFalse(
            video_in_scope(
                "如何轻松游玩V社火爆新游死锁deadlock",
                5000,
                min_danmaku=500,
                title_contains="社火",
                title_any=None,
                title_exclude=["死锁"],
            )
        )
        self.assertFalse(
            video_in_scope(
                "两年画完全部宝可梦",
                8000,
                min_danmaku=1500,
                title_contains="年画",
                title_any=None,
                title_exclude=["宝可梦"],
            )
        )
        self.assertFalse(
            video_in_scope(
                "穿越剧的鼻祖寻秦记",
                20000,
                min_danmaku=2000,
                title_contains="越剧",
                title_any=None,
                title_exclude=["穿越剧"],
            )
        )
        self.assertFalse(
            video_in_scope(
                "国家宝藏",
                999,
                min_danmaku=1000,
                title_contains="国家宝藏",
                title_any=None,
                title_exclude=[],
            )
        )

    def test_hot_search_keeps_the_first_group(self):
        class Fake:
            def __init__(self):
                self.exclude = None

            def search_hot(
                self,
                keyword,
                min_danmaku,
                title_contains=None,
                title_any=None,
                title_exclude=None,
                max_pages=50,
            ):
                self.exclude = title_exclude
                return [
                    {
                        "bvid": "BV1TEST",
                        "aid": 1,
                        "title": "国家宝藏第一期",
                        "danmaku_counter": min_danmaku,
                    }
                ]

        fake = Fake()
        videos = resolve_collection(
            fake,
            {
                "id": "tradition-hot",
                "list": "hot_search",
                "min_danmaku": 1000,
                "title_exclude": ["原神"],
                "groups": {"museum": "文物博物馆", "festival": "节庆民俗"},
                "queries": [
                    {"group": "museum", "keyword": "国家宝藏", "min_danmaku": 1000},
                    {"group": "festival", "keyword": "国家宝藏", "min_danmaku": 1000},
                ],
            },
        )
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["group"], "museum")
        self.assertEqual(videos[0]["group_title"], "文物博物馆")
        self.assertEqual(videos[0]["queries"], ["国家宝藏"])
        self.assertIn("原神", fake.exclude)

    def test_prune_drops_titles_the_scope_no_longer_allows(self):
        spec = {
            "title_exclude": ["游戏", "魔刀"],
            "queries": [
                {
                    "keyword": "才浅",
                    "title_contains": "才浅",
                    "title_any": ["三星堆", "面具"],
                }
            ],
        }
        kept = prune_hot_videos(
            [
                {"bvid": "BVKEEP", "title": "才浅 三星堆黄金面具", "query": "才浅"},
                {"bvid": "BVDROP1", "title": "才浅手工 魔刀千刃", "query": "才浅"},
                {"bvid": "BVDROP2", "title": "蜀道行 三星堆 游戏演示", "query": "三星堆"},
            ],
            spec,
        )
        self.assertEqual([item["bvid"] for item in kept], ["BVKEEP"])


class FetchTests(unittest.TestCase):
    def test_empty_middle_segments_do_not_drop_the_tail(self):
        client = BilibiliClient.__new__(BilibiliClient)
        client.delay = 0
        client._last = 0.0
        client.cookie = ""
        seen = []

        def get(url, referer, raw=False, retries=5, cookie=False):
            if "pagelist" in url:
                return {"code": 0, "data": [{"cid": 1, "page": 1, "duration": 1800}]}
            if "dm/web/view" in url:
                return b""
            index = int(url.split("segment_index=")[1])
            seen.append(index)
            if index == 3:
                return encode_elem("青铜", 1000, 9)
            return b""

        client.get = get
        rows, info = client.fetch_video_danmaku("BV1TEST", aid=1)
        self.assertEqual(sorted(seen), [1, 2, 3, 4, 5])
        self.assertEqual(info["count"], 1)
        self.assertEqual(info["parts"][0]["segments"], 5)
        self.assertEqual(rows[0]["content"], "青铜")


if __name__ == "__main__":
    unittest.main()
