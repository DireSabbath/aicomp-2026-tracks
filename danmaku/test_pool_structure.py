import unittest

from pool_structure import merge, summarize_video


def row(progress, ctime, text="合成"):
    return {
        "id": progress,
        "progress_ms": progress,
        "mode": 1,
        "content": text,
        "ctime": ctime,
        "page": 1,
    }


class PoolStructureTest(unittest.TestCase):
    def test_opening_week_and_later_tail_share_one_bin(self):
        opening = 1_700_000_000
        rows = [row(index * 1000, opening + index) for index in range(30)]
        rows.append(row(5000, opening + 30 * 86400))
        rows.append(row(8000, opening + 40 * 86400))
        video = summarize_video(rows)
        self.assertFalse(video["skipped"])
        self.assertEqual(video["week_offset_days"], 0)
        self.assertAlmostEqual(video["premiere_share"], 30 / 32)
        self.assertEqual(len(video["bin_spans"]), 1)
        self.assertGreater(video["bin_spans"][0], 7)
        self.assertNotIn("content", json_keys(video))

    def test_short_video_is_skipped(self):
        video = summarize_video([row(0, 1_700_000_000)])
        self.assertTrue(video["skipped"])

    def test_merge_does_not_keep_text(self):
        opening = 1_700_000_000
        rows = [row(index * 1000, opening) for index in range(30)]
        report = merge([summarize_video(rows)])
        self.assertEqual(report["analyzed_videos"], 1)
        self.assertEqual(report["bins"], 1)
        blob = str(report)
        self.assertNotIn("合成", blob)


def json_keys(value):
    found = set()
    if isinstance(value, dict):
        found.update(value)
        for item in value.values():
            found.update(json_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(json_keys(item))
    return found


if __name__ == "__main__":
    unittest.main()
