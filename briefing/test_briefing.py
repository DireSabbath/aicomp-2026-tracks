"""简报里的数必须来自结构表，四栏差异必须分得开。"""

from __future__ import annotations

import re
import unittest

from briefing.load import Video
from briefing.report import build_report
from briefing.structure import build_type
from briefing.text import place, stretch
from briefing.web import render_page


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


def outside_quotes(text: str) -> str:
    return re.sub(r"「[^」]*」", "", text)


def integers_outside_quotes(text: str) -> list[int]:
    return [int(number) for number in re.findall(r"\d+", outside_quotes(text))]


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
            video(
                "a1",
                [("同款", 10000)] * 3
                + [("悟空", 10000)] * 3
                + [("只在这一条视频", 10000)] * 3
                + [("错位", 10000)] * 2,
            ),
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
        words = {claim["text"] for item in report["types"] for claim in item["words"]}
        phrases = {claim["text"] for item in report["types"] for claim in item["phrases"]}
        self.assertIn("同款", words)
        self.assertIn("甲边", words)
        self.assertIn("台独口号", phrases)
        self.assertNotIn("悟空", words)
        self.assertNotIn("台独口号", words)
        self.assertIn("悟空", {item["text"] for item in report["types"][0]["solo_words"]})
        self.assertIn("只在这一条视频", {item["text"] for item in report["types"][0]["solo_phrases"]})
        self.assertNotIn("只在这一条视频", phrases)
        briefing = "\n".join(report["briefing"])
        self.assertNotIn("段", outside_quotes(briefing))
        self.assertIn("同款", {item["text"] for item in report["diff"]["same_peak"]["items"]})
        self.assertIn("错位", {item["text"] for item in report["diff"]["shifted"]["items"]})
        self.assertIn("甲边", {item["text"] for item in report["diff"]["only_a"]["items"]})
        self.assertIn("乙边", {item["text"] for item in report["diff"]["only_b"]["items"]})
        self.assertNotIn("台独口号", {item["text"] for bucket in report["diff"].values() for item in bucket["items"]})
        self.assertIn("台独口号", {item["text"] for item in report["phrase_diff"]["only_b"]["items"]})
        quoted = re.findall(r"「([^」]*)」", briefing)
        known = {row["text"] for row in report["table"] if row["kind"] in {"claim", "diff_item"}}
        self.assertTrue(quoted)
        self.assertTrue(set(quoted) <= known)
        grounded = table_integers(report["table"])
        for sentence in report["briefing"]:
            for number in integers_outside_quotes(sentence):
                self.assertIn(number, grounded, sentence)
        left_same = [
            row
            for row in report["table"]
            if row["kind"] == "claim" and row["type_id"] == "jia" and row["layer"] == "word" and row["diff_bucket"] == "same_peak"
        ]
        self.assertEqual(len(left_same), report["diff"]["same_peak"]["count"])
        left_words = {claim["text"]: claim for claim in report["types"][0]["words"]}
        self.assertIn("错位", {item["text"] for item in left_words["同款"]["neighbors"]})
        diff_text = {row["text"] for row in report["table"] if row["kind"] == "diff_item"}
        self.assertNotIn("悟空", diff_text)
        self.assertNotIn("只在这一条视频", diff_text)

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
        phrases = {claim["text"] for claim in report["types"][0]["phrases"]}
        self.assertIn("人民万岁", phrases)
        briefing = "\n".join(report["briefing"])
        self.assertIn("人民万岁", briefing)
        self.assertTrue(any("片尾" in sentence or "片长" in sentence for sentence in report["briefing"]))
        self.assertNotIn("段", outside_quotes(briefing))

    def test_punctuation_variants_merge_and_point_back(self) -> None:
        left = [
            video("a1", [("《阶段性成果》", 10000)] * 2 + [("猿神，启动！", 50000)] * 2),
            video("a2", [("阶段性成果", 11000)] * 2 + [("猿神启动", 51000)] * 2),
        ]
        right = [
            video("b1", [("其他句子在这里", 10000)] * 2),
            video("b2", [("其他句子在这里", 11000)] * 2),
        ]
        report = build_report(
            [("jia", "甲", left), ("yi", "乙", right)],
            segments=4,
            tolerance=0,
            min_videos=2,
            min_rows=2,
        )
        phrases = {claim["text"]: claim for claim in report["types"][0]["phrases"]}
        self.assertIn("阶段性成果", phrases)
        self.assertEqual(phrases["阶段性成果"]["n_rows"], 4)
        self.assertEqual(phrases["阶段性成果"]["n_videos"], 2)
        evidence = {item["text"] for item in phrases["阶段性成果"]["evidence"]}
        self.assertIn("《阶段性成果》", evidence)
        self.assertIn("阶段性成果", evidence)
        self.assertIn("猿神启动", phrases)
        self.assertEqual(phrases["猿神启动"]["n_videos"], 2)
        exported = {text for row in report["table"] if row["kind"] == "claim" for text in row["evidence_text"]}
        self.assertIn("《阶段性成果》", exported)

    def test_short_reactions_are_counted_but_not_claims(self) -> None:
        comments = [("啊？", 1000)] * 6 + [("好耶！", 1000)] * 6 + [("这是", 1000)] * 6 + [("哈哈哈哈", 1000)] * 6
        built = build_type(
            "t",
            "题",
            [video("a1", comments), video("a2", comments)],
            segments=4,
            min_videos=2,
            min_rows=2,
        )
        texts = {claim["text"] for claim in built["claims"]} | {claim["text"] for claim in built["phrases"]}
        self.assertNotIn("啊？", texts)
        self.assertNotIn("好耶", texts)
        self.assertNotIn("这是", texts)
        self.assertNotIn("哈哈哈哈", texts)
        self.assertEqual(built["usable_rows"], 48)

    def test_place_names_the_video(self) -> None:
        self.assertEqual(place(0, 5), "开头的5%")
        self.assertEqual(place(45, 50), "片长的45%到50%")
        self.assertEqual(place(75, 100), "片长的75%到片尾")
        self.assertEqual(stretch(0, 100), "从开头一直到片尾")
        self.assertEqual(stretch(55, 90), "从片长的55%到90%")
        self.assertNotIn("段", place(45, 50))
        self.assertNotIn("段", place(0, 100))

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
        claim = next(item for item in early["claims"] if item["text"] == "下集")
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
        claim = next(item for item in late["claims"] if item["text"] == "下集")
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

    def test_page_speaks_in_progress(self) -> None:
        left = [video("a1", [("阶段性成果", 10000)] * 3), video("a2", [("阶段性成果", 11000)] * 3)]
        right = [video("b1", [("前方高能预警", 80000)] * 3), video("b2", [("前方高能预警", 81000)] * 3)]
        report = build_report(
            [("jia", "甲类型", left), ("yi", "乙类型", right)],
            segments=4,
            tolerance=0,
            min_videos=2,
            min_rows=2,
        )
        html = render_page(report)
        self.assertIn(">说法<", html)
        self.assertIn(">对照<", html)
        self.assertIn("不显示是谁发的", html)
        self.assertNotIn("民意", html)
        self.assertNotIn("政策建议", html)
        self.assertIn("阶段性成果", html)
        self.assertNotIn("段", outside_quotes("\n".join(report["briefing"])))


if __name__ == "__main__":
    unittest.main()
