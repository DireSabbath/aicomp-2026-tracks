import gzip
import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from reception.analyze import build_type
from reception.load import Pool, Row, Video, load_zip, normalize, percent_in_film
from reception.page import build_report, render_page
from reception.__main__ import main


def _row(bvid: str, content: str, percent: float) -> Row:
    return Row(bvid, content, normalize(content), percent, 1)


def _video(bvid: str, pairs: list[tuple[str, float]]) -> Video:
    return Video(bvid, bvid, [_row(bvid, content, percent) for content, percent in pairs])


def _pool(title: str, videos: list[Video]) -> Pool:
    return Pool(title, videos)


def _repeat(bvid: str, content: str, percent: float, times: int) -> list[tuple[str, float]]:
    return [(content, percent) for _ in range(times)]


def _write_zip(path: Path, folder: str, videos: list[dict]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for video in videos:
            stem = f"{folder}/{video['bvid']}"
            archive.writestr(stem + ".meta.json", json.dumps({"bvid": video["bvid"], "title": video["bvid"], "parts": video["parts"]}))
            raw = "\n".join(json.dumps(row, ensure_ascii=False) for row in video["rows"])
            archive.writestr(stem + ".jsonl.gz", gzip.compress(raw.encode()))


class ReceptionTests(unittest.TestCase):
    def test_percent_across_parts(self):
        parts = [{"page": 1, "duration": 100}, {"page": 2, "duration": 100}]
        self.assertEqual(percent_in_film(0, 2, parts), 0.5)
        self.assertEqual(percent_in_film(50_000, 2, parts), 0.75)
        self.assertEqual(percent_in_film(0, 1, parts), 0.0)

    def test_percent_skips_and_clamps(self):
        parts = [{"page": 1, "duration": 100}]
        self.assertIsNone(percent_in_film(None, 1, parts))
        self.assertIsNone(percent_in_film(0, 1, []))
        self.assertAlmostEqual(percent_in_film(200_000, 1, parts), 99_999 / 100_000)

    def test_load_zip_skips_unplaced_and_offsets_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.zip"
            _write_zip(
                path,
                "sample",
                [
                    {
                        "bvid": "BV1",
                        "parts": [{"page": 1, "duration": 100}, {"page": 2, "duration": 100}],
                        "rows": [
                            {"content": "震撼首发", "progress_ms": None, "page": 1},
                            {"content": "……", "progress_ms": 10, "page": 1},
                            {"content": "猿神，启动！", "progress_ms": 0, "page": 2},
                        ],
                    }
                ],
            )
            pool = load_zip(path)
        self.assertEqual(pool.title, "sample")
        self.assertEqual(pool.skipped, 2)
        self.assertEqual(len(pool.rows), 1)
        self.assertEqual(pool.rows[0].percent, 0.5)
        self.assertEqual(pool.rows[0].content, "猿神，启动！")
        self.assertEqual(pool.rows[0].norm, "猿神启动")

    def test_literal_merge_dialogue_and_people_phrase(self):
        def filler(bvid: str) -> list[tuple[str, float]]:
            pairs = []
            for window, count in {0: 50, 1: 50, 2: 8, 3: 8, 4: 8, 5: 8, 6: 8, 7: 8, 9: 8}.items():
                percent = (window + 0.5) / 10
                for index in range(count):
                    pairs.append((f"垫{window}位{index}{bvid}", percent))
            return pairs

        left_pairs = filler("甲") + _repeat("甲", "前方高能", 0.05, 4) + _repeat("甲", "前方高能预警", 0.05, 4)
        left_pairs += _repeat("甲", "高能预警", 0.05, 3)
        left_pairs += _repeat("甲", "哈哈哈", 0.85, 2) + _repeat("甲", "哈哈", 0.85, 2)
        left_pairs += _repeat("甲", "人民万岁", 0.55, 3)
        left_pairs += _repeat("甲", "猿神，启动！", 0.33, 2)
        left_pairs += _repeat("甲", "这句接话", 0.62, 2)
        left_pairs += _repeat("甲", "只此一家", 0.45, 4)
        right_pairs = filler("乙") + _repeat("乙", "前方高能", 0.06, 4) + _repeat("乙", "前方高能预警", 0.06, 4)
        right_pairs += _repeat("乙", "高能预警", 0.06, 3)
        right_pairs += _repeat("乙", "哈哈哈", 0.85, 2) + _repeat("乙", "哈哈", 0.85, 2)
        right_pairs += _repeat("乙", "人民万岁", 0.56, 3)
        right_pairs += _repeat("乙", "接话啊", 0.62, 2)
        right_pairs += [("乙的另一句", 0.33), ("猿神,启动！", 0.34)]
        built = build_type(_pool("heishenhua", [_video("甲", left_pairs), _video("乙", right_pairs)]))
        groups = [set(thing["norms"]) for thing in built["things"]]
        self.assertTrue(any(group == {"前方高能", "前方高能预警", "高能预警"} for group in groups))
        self.assertFalse(any("这句接话" in group and "接话啊" in group for group in groups))
        self.assertTrue(any(group == {"猿神启动"} for group in groups))
        self.assertTrue(any("人民万岁" in group for group in groups))
        self.assertFalse(any("只此一家" in group for group in groups))
        self.assertTrue(any(item["text"] == "只此一家" for item in built["solos"]))
        topic = next(thing for thing in built["things"] if "前方高能" in thing["norms"])
        self.assertEqual(topic["mode"], "topic")
        self.assertEqual(topic["evidence"][0]["content"], topic["text"])
        dialogue = next(thing for thing in built["things"] if "哈哈" in thing["norms"])
        self.assertEqual(dialogue["mode"], "dialogue")
        self.assertGreater(dialogue["median"], built["crowded"][0]["end"])
        texts = {thing["text"] for thing in built["things"]}
        quoted = re.findall(r"「([^」]*)」", "\n".join(__import__("reception.page", fromlist=["readings"]).readings({**built, "title": "黑神话官方"})))
        self.assertTrue(quoted)
        self.assertTrue(set(quoted) <= texts)

    def test_stray_row_does_not_glue_two_ends(self):
        pairs_a = _repeat("甲", "前方高能", 0.10, 5) + [("前方高能", 0.90)]
        pairs_b = _repeat("乙", "前方高能", 0.10, 5) + _repeat("乙", "前方高能预警", 0.90, 4) + _repeat("甲", "前方高能预警", 0.90, 0)
        pairs_a += _repeat("甲", "前方高能预警", 0.90, 4)
        built = build_type(_pool("sample", [_video("甲", pairs_a), _video("乙", pairs_b)]))
        groups = [set(thing["norms"]) for thing in built["things"]]
        self.assertIn({"前方高能"}, groups)
        self.assertIn({"前方高能预警"}, groups)

    def test_two_types_match(self):
        left = _pool(
            "heishenhua",
            [
                _video("甲", _repeat("甲", "前方高能", 0.20, 3) + _repeat("甲", "哈哈", 0.20, 3) + _repeat("甲", "只在黑神话", 0.40, 3)),
                _video("乙", _repeat("乙", "前方高能", 0.20, 3) + _repeat("乙", "哈哈", 0.20, 3) + _repeat("乙", "只在黑神话", 0.40, 3)),
            ],
        )
        right = _pool(
            "yuanshen-preview",
            [
                _video("丙", _repeat("丙", "前方高能预警", 0.22, 3) + _repeat("丙", "哈哈哈", 0.80, 3) + _repeat("丙", "<script>alert(1)</script>", 0.50, 2)),
                _video("丁", _repeat("丁", "前方高能预警", 0.22, 3) + _repeat("丁", "哈哈哈", 0.80, 3) + _repeat("丁", "<script>alert(1)</script>", 0.50, 2)),
            ],
        )
        report = build_report(left, right)
        paired = {(item["left"], item["right"], item["shifted"]) for item in report["match"]["pairs"]}
        self.assertIn(("前方高能", "前方高能预警", False), paired)
        self.assertIn(("哈哈", "哈哈哈", True), paired)
        self.assertIn("只在黑神话", report["match"]["only_left"])
        self.assertIn("<script>alert(1)</script>", report["match"]["only_right"])
        html = render_page(report)
        self.assertIn("试点按字面接近归并。同义不同字还没有并到一块。这些视频算不算同一类，还没有人签字。材料里没有发言者，页面不显示是谁发的。", html)
        self.assertIn("0.72", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("\\u003cscript>alert", html)
        self.assertNotIn("<svg", html)
        self.assertNotIn("polyline", html)
        self.assertIn("黑神话官方", html)
        self.assertIn("原神前瞻", html)
        quotes = re.findall(r"「([^」]*)」", "\n".join(report["readings"]))
        shown = {thing["text"] for thing in report["left"]["shown"] + report["right"]["shown"]}
        self.assertTrue(set(quotes) <= shown)
        self.assertFalse(any(re.search(r"\d+\.\d", line) for line in report["readings"]))

    def test_people_phrase_stays_on_the_page(self):
        left = _pool(
            "heishenhua",
            [
                _video("甲", _repeat("甲", "人民万岁", 0.75, 3)),
                _video("乙", _repeat("乙", "人民万岁", 0.76, 3)),
            ],
        )
        right = _pool("yuanshen-preview", [_video("丙", _repeat("丙", "接话啊", 0.10, 2)), _video("丁", _repeat("丁", "接话啊", 0.10, 2))])
        html = render_page(build_report(left, right))
        self.assertIn("人民万岁", html)
        self.assertIn("没有发言者", html)

    def test_cli_writes_page(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            left = root / "a.zip"
            right = root / "b.zip"
            _write_zip(
                left,
                "heishenhua",
                [
                    {
                        "bvid": "BV甲",
                        "parts": [{"page": 1, "duration": 10}],
                        "rows": [{"content": "人民万岁", "progress_ms": 1000, "page": 1}, {"content": "人民万岁", "progress_ms": 1200, "page": 1}],
                    },
                    {
                        "bvid": "BV乙",
                        "parts": [{"page": 1, "duration": 10}],
                        "rows": [{"content": "人民万岁", "progress_ms": 1000, "page": 1}, {"content": "人民万岁", "progress_ms": 1400, "page": 1}],
                    },
                ],
            )
            _write_zip(
                right,
                "yuanshen-preview",
                [
                    {
                        "bvid": "BV丙",
                        "parts": [{"page": 1, "duration": 10}],
                        "rows": [{"content": "哈哈哈", "progress_ms": 8000, "page": 1}, {"content": "哈哈", "progress_ms": 8100, "page": 1}],
                    },
                    {
                        "bvid": "BV丁",
                        "parts": [{"page": 1, "duration": 10}],
                        "rows": [{"content": "哈哈哈", "progress_ms": 8200, "page": 1}, {"content": "哈哈", "progress_ms": 8300, "page": 1}],
                    },
                ],
            )
            out = root / "out"
            main([str(left), str(right), "--out", str(out), "--limit-videos", "1"])
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["left"]["n_videos"], 1)
            html = (out / "index.html").read_text()
            self.assertIn("一类视频的观众接收", html)
            self.assertIn("没有发言者", html)


if __name__ == "__main__":
    unittest.main()
