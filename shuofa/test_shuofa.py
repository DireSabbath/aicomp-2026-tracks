import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shuofa.baseline import split_report
from shuofa.label import EVERYWHERE, ONLY_HERE, UNSURE, judge
from shuofa.peak import locate
from shuofa.scan import scan_circles, scan_video
from shuofa.textutil import default_lexicon, load_lexicon, match_families, normalize


ROOT = Path(__file__).resolve().parent
LEXICON = load_lexicon(default_lexicon())


def write_video(directory: Path, bvid: str, lines: list[dict]) -> None:
    meta = {
        "bvid": bvid,
        "title": bvid,
        "parts": [{"cid": 1, "page": 1, "duration": 100, "count": len(lines)}],
    }
    (directory / f"{bvid}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    with gzip.open(directory / f"{bvid}.jsonl.gz", "wt", encoding="utf-8") as handle:
        for index, line in enumerate(lines):
            handle.write(
                json.dumps(
                    {
                        "id": index,
                        "progress_ms": line.get("progress_ms"),
                        "mode": 1,
                        "content": line["content"],
                        "ctime": 1,
                        "cid": 1,
                        "page": 1,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


class TextTests(unittest.TestCase):
    def test_punctuation_does_not_split_a_sentence(self):
        self.assertEqual(normalize("好耶！"), normalize("好耶"))

    def test_variants_match_one_family(self):
        late = match_families("三三来迟", LEXICON)
        also = match_families("三迟但到", LEXICON)
        self.assertEqual(late, also)
        self.assertEqual(late, ["sansan"])

    def test_longer_variant_stays_in_the_same_family(self):
        matched = match_families("三军听令，自刎归天！", LEXICON)
        self.assertEqual(matched, ["ziwen"])


class LabelTests(unittest.TestCase):
    def test_only_this_circle(self):
        decision = judge(
            {
                "xiaoyuehan": 0.64,
                "luoxiang": 0.0,
                "new-sanguo": 0.0,
                "yuanshen-preview": 0.0,
                "heishenhua": 0.0,
            }
        )
        self.assertEqual(decision["label"], ONLY_HERE)
        self.assertEqual(decision["home"], "xiaoyuehan")

    def test_everywhere(self):
        decision = judge(
            {
                "yuanshen-preview": 1.0,
                "heishenhua": 0.32,
                "xiaoyuehan": 0.14,
                "luoxiang": 0.07,
                "new-sanguo": 0.04,
            }
        )
        self.assertEqual(decision["label"], EVERYWHERE)
        self.assertIsNone(decision["home"])

    def test_high_home_with_small_leak_stays_in_circle(self):
        decision = judge({"new-sanguo": 0.93, "xiaoyuehan": 0.084, "luoxiang": 0.0})
        self.assertEqual(decision["label"], ONLY_HERE)
        self.assertEqual(decision["home"], "new-sanguo")

    def test_unsure_when_too_rare(self):
        decision = judge({"new-sanguo": 0.1, "luoxiang": 0.0})
        self.assertEqual(decision["label"], UNSURE)


class PeakTests(unittest.TestCase):
    def test_clustered_lines_get_a_span(self):
        peak = locate([10000, 11000, 12000, 14000, 80000])
        self.assertIsNotNone(peak)
        self.assertTrue(peak["held"])
        self.assertEqual(peak["start_ms"], 10000)
        self.assertGreaterEqual(peak["share"], 0.3)

    def test_scattered_lines_have_no_span(self):
        peak = locate([0, 20000, 40000, 60000])
        self.assertIsNotNone(peak)
        self.assertFalse(peak["held"])

    def test_missing_progress_is_ignored(self):
        self.assertIsNone(locate([None, None, 1000]))


class BaselineTests(unittest.TestCase):
    def test_conventional_cut_splits_the_greeting(self):
        report = split_report(["三三来迟", "三迟但到"])
        self.assertTrue(report["different_cuts"])
        self.assertEqual(report["forms"], 2)


class ScanTests(unittest.TestCase):
    def test_synthetic_collections_keep_circle_and_platform_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "xiaoyuehan"
            other = root / "yuanshen-preview"
            home.mkdir()
            other.mkdir()
            for index in range(8):
                write_video(
                    home,
                    f"H{index}",
                    [
                        {"content": "可汗勤政", "progress_ms": 1000},
                        {"content": "好耶", "progress_ms": 2000},
                    ],
                )
            for index in range(2):
                write_video(home, f"E{index}", [{"content": "路过", "progress_ms": 1000}])
            for index in range(5):
                write_video(
                    other,
                    f"Y{index}",
                    [
                        {"content": "好耶", "progress_ms": 3000},
                        {"content": "好耶！", "progress_ms": 4000},
                        {"content": "好耶", "progress_ms": 5000},
                        {"content": "好耶", "progress_ms": 80000},
                    ],
                )
            payload = scan_circles(root, LEXICON)
            by_id = {row["id"]: row for row in payload["families"]}
            self.assertEqual(by_id["kehan"]["label"], ONLY_HERE)
            self.assertEqual(by_id["kehan"]["home"], "xiaoyuehan")
            self.assertEqual(by_id["haoye"]["label"], EVERYWHERE)

            gz = other / "Y0.jsonl.gz"
            video = scan_video(gz, LEXICON, payload)
            haoye = video["rows"][0]
            self.assertEqual(haoye["name"], "好耶")
            self.assertEqual(haoye["label"], EVERYWHERE)
            self.assertIsNotNone(haoye["peak"])


if __name__ == "__main__":
    unittest.main()
