import unittest

from datetime import datetime, timedelta, timezone

from crawl import (
    HISTORY_DAY_CAP,
    RATE_LIMIT_CODES,
    bv_to_aid,
    decode_danmaku_segment,
    jump_target_day,
    months_from,
    segment_count_from_view,
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

    def test_rate_limit_codes_are_retried(self):
        self.assertIn(-702, RATE_LIMIT_CODES)
        self.assertNotIn(0, RATE_LIMIT_CODES)
        self.assertNotIn(-101, RATE_LIMIT_CODES)

    def test_months_from(self):
        zone = timezone(timedelta(hours=8))
        pubdate = int(datetime(2024, 6, 15, 12, 0, tzinfo=zone).timestamp())
        months = months_from(pubdate, datetime(2024, 8, 1, tzinfo=zone))
        self.assertEqual(months, ["2024-06", "2024-07", "2024-08"])

    def test_jump_stops_when_pool_is_under_cap(self):
        ctime = int(datetime(2024, 6, 15, 0, 30, tzinfo=timezone.utc).timestamp())
        self.assertIsNone(jump_target_day([ctime], "2024-08-01", HISTORY_DAY_CAP - 1))

    def test_jump_uses_china_day_before_oldest_ctime(self):
        # 2024-06-14 16:30 UTC is 2024-06-15 00:30 in China.
        ctime = int(datetime(2024, 6, 14, 16, 30, tzinfo=timezone.utc).timestamp())
        self.assertEqual(jump_target_day([ctime], "2024-08-01", HISTORY_DAY_CAP), "2024-06-14")
        same_day = int(datetime(2024, 8, 1, 2, 0, tzinfo=timezone.utc).timestamp())
        self.assertEqual(jump_target_day([same_day], "2024-08-01", HISTORY_DAY_CAP), "2024-07-31")

    def test_segment_count(self):
        inner = encode_varint((2 << 3) | 0) + encode_varint(3)
        blob = encode_varint((4 << 3) | 2) + encode_varint(len(inner)) + inner
        self.assertEqual(segment_count_from_view(blob), 3)


if __name__ == "__main__":
    unittest.main()
