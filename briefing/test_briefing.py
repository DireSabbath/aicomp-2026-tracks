"""简报里的数必须来自结构表，四栏差异必须分得开。"""

from __future__ import annotations

import re
import unittest

from briefing.load import Video
from briefing.report import build_report
from briefing.structure import build_type
from briefing.text import place, stretch


def video(bvid: str, comments: list[tuple[str, int]]) -> Video:
    return Video(
        bvid=bvid,
        title=bvid,
        parts=[{"page": 1, "duration": 100}],
        rows=[
            {
                "id": index,
                "progress_ms": progress,
                "content": text,
                "ctime": 1_700_000_000 + index,
                "page": 1,
                "mode": 1,
                "cid": 1,
            }
            for index, (text, progress) in enumerate(comments)
        ],
    )


def integers_outside_quotes(text: str) -> list[int]:
    stripped = re.sub(r"「[^」]*」", "", text)
    return [int(number) for number in re.findall(r"\d+", stripped)]


def table_integers(rows: list[dict]) -> set[int]:
    found: set[int] = set()

    def walk(value) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int):
            found.add(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(rows)
    return found


class BriefingTest(unittest.TestCase):
    def test_structure_and_grounded_briefing(self) -> None:
        left = [
            video("a1", [("同款", 10000)] * 3 + [("只此", 10000)] * 3 + [("错位", 10000)] * 2),
            video("a2", [("同款", 11000)] + [("甲边", 80000)] * 2),
            video("a3", [("甲边", 82000)] * 2 + [("错位", 12000)] * 2),
        ]
        right = [
            video("b1", [("同款", 10000)] * 2 + [("乙边", 60000)] * 2 + [("错位", 80000)] * 2),
            video("b2", [("同款", 12000)] * 2 + [("乙边", 62000)] * 2 + [("错位", 82000)] * 2 + [("台独口号", 10000)] * 3),
            video("b3", [("台独口号", 12000)] * 3),
        ]
        report = build_report(
            [
                ("jia", "甲类型", left),
                ("yi", "乙类型", right),
            ],
            segments=4,
            tolerance=0,
            min_videos=2,
            min_rows=2,
        )
        claims = {claim["text"] for item in report["types"] for claim in item["claims"]}
        self.assertIn("同款", claims)
        self.assertIn("甲边", claims)
        self.assertIn("台独口号", claims)
        self.assertNotIn("只此", claims)
        self.assertNotIn("段", "\n".join(report["briefing"]))
        self.assertIn("同款", {item["text"] for item in report["diff"]["same_peak"]["items"]})
        self.assertIn("错位", {item["text"] for item in report["diff"]["shifted"]["items"]})
        self.assertIn("甲边", {item["text"] for item in report["diff"]["only_a"]["items"]})
        self.assertIn("乙边", {item["text"] for item in report["diff"]["only_b"]["items"]})
        quoted = re.findall(r"「([^」]*)」", "\n".join(report["briefing"]))
        known = {
            row["text"]
            for row in report["table"]
            if row["kind"] in {"claim", "diff_item"}
        }
        self.assertTrue(quoted)
        self.assertTrue(set(quoted) <= known)
        grounded = table_integers(report["table"])
        for sentence in report["briefing"]:
            for number in integers_outside_quotes(sentence):
                self.assertIn(number, grounded, sentence)

    def test_repeated_sentence_stays_in_the_briefing(self) -> None:
        left = [
            video("a1", [("普通说法", 1000)] * 3 + [("人民万岁", 90000)] * 4),
            video("a2", [("普通说法", 2000)] * 3 + [("人民万岁", 91000)] * 4),
        ]
        right = [
            video("b1", [("普通说法", 1000)] * 3),
            video("b2", [("普通说法", 2000)] * 3),
        ]
        report = build_report(
            [("jia", "甲类型", left), ("yi", "乙类型", right)],
            segments=4,
            tolerance=0,
            min_videos=2,
            min_rows=2,
        )
        self.assertEqual(report["types"][0]["volume_peak_segment"], 4)
        claims = {claim["text"] for claim in report["types"][0]["claims"]}
        self.assertIn("人民万岁", claims)
        self.assertIn("人民万岁", "\n".join(report["briefing"]))
        self.assertTrue(any("片尾" in sentence or "片长" in sentence for sentence in report["briefing"]))

    def test_place_names_the_video(self) -> None:
        self.assertEqual(place(0, 5), "开头的5%")
        self.assertEqual(place(45, 50), "片长的45%到50%")
        self.assertEqual(place(75, 100), "片长的75%到片尾")
        self.assertEqual(stretch(0, 100), "从开头一直到片尾")
        self.assertEqual(stretch(55, 90), "从片长的55%到90%")
        self.assertNotIn("段", place(45, 50))

    def test_median_peak_keeps_the_fraction(self) -> None:
        built = build_type(
            "t",
            "题",
            [
                video("m1", [("甲", 1000), ("甲", 1000), ("乙", 30000)]),
                video("m2", [("乙", 30000), ("乙", 30000)]),
            ],
            segments=4,
            min_videos=1,
            min_rows=1,
        )
        self.assertEqual(built["volume_median"][0], 1.0)
        self.assertEqual(built["volume_median"][1], 1.5)
        self.assertEqual(built["volume_peak_segment"], 2)
        self.assertEqual(built["volume_peak_starts"], [25])
        self.assertEqual(built["volume_peak_ends"], [50])

    def test_second_page_offset_and_end_clamp(self) -> None:
        def paged(bvid: str, progress: int) -> Video:
            return Video(
                bvid=bvid,
                title=bvid,
                parts=[{"page": 1, "duration": 50}, {"page": 2, "duration": 50}],
                rows=[
                    {
                        "id": index,
                        "progress_ms": progress,
                        "content": "下集见",
                        "ctime": 1_700_000_000,
                        "page": 2,
                        "mode": 1,
                        "cid": 2,
                    }
                    for index in range(5)
                ],
            )

        early = build_type("p", "分页", [paged("p1", 0), paged("p2", 0)], segments=4, min_videos=2, min_rows=2)
        claim = next(item for item in early["claims"] if item["text"] == "下集见")
        self.assertEqual(claim["entry_segment"], 3)
        self.assertEqual(claim["peak_segment"], 3)
        late = build_type(
            "p",
            "分页",
            [paged("p1", 50000), paged("p2", 50000)],
            segments=4,
            min_videos=2,
            min_rows=2,
        )
        claim = next(item for item in late["claims"] if item["text"] == "下集见")
        self.assertEqual(claim["peak_segment"], 4)

    def test_baseline_is_first_bvid(self) -> None:
        built = build_type(
            "t",
            "题",
            [
                video("b2", [("后", 80000)] * 3),
                video("b1", [("先", 1000)] * 3),
            ],
            segments=4,
            min_videos=1,
            min_rows=1,
        )
        self.assertEqual(built["volume_lines"][0]["bvid"], "b1")
        self.assertEqual(built["baseline_peak_segment"], 1)


if __name__ == "__main__":
    unittest.main()
