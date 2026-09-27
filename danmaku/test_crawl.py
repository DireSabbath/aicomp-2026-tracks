import unittest

from crawl import bv_to_aid, decode_danmaku_segment, segment_count_from_view


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

    def test_segment_count(self):
        inner = encode_varint((2 << 3) | 0) + encode_varint(3)
        blob = encode_varint((4 << 3) | 2) + encode_varint(len(inner)) + inner
        self.assertEqual(segment_count_from_view(blob), 3)


if __name__ == "__main__":
    unittest.main()
