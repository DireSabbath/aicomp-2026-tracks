import gzip
import json
import tempfile
import unittest
from pathlib import Path

from collections import Counter

from wenmai.analyze import analyze, fightin_words
from wenmai.classify import classify, find_symbols
from wenmai.codebook import CODE_NAMES, DIMENSIONS
from wenmai.model import evaluation_report, fit_char_model, template_examples
from wenmai.render import render
from wenmai.train_gpu import build_parser, main as gpu_main

ROOT = Path(__file__).resolve().parents[1]


class CodebookTests(unittest.TestCase):
    def test_seventeen_codes_under_six_dimensions(self):
        self.assertEqual(len(CODE_NAMES), 17)
        self.assertEqual(len(DIMENSIONS), 6)
        self.assertEqual(len(set(CODE_NAMES)), 17)

    def test_longer_symbol_consumes_shorter_name(self):
        found = find_symbols("清明上河图")
        self.assertEqual([name for name, _ in found], ["清明上河图"])

    def test_school_names_and_official_titles_are_not_classics(self):
        self.assertEqual(find_symbols("中国地质大学发来慰问"), [])
        self.assertEqual(find_symbols("兵部尚书不敢"), [])
        self.assertEqual([name for name, _ in find_symbols("开篇就是《大学》")], ["《大学》"])
        self.assertNotIn("观看体验", classify("爱的魔力转圈圈"))
        self.assertNotIn("实践印证", classify("真·家里有矿"))
        self.assertIn("文化符号提及", classify("我会背石鼓歌"))
        self.assertIn("古今适配讨论", classify("古为今用，让年轻人了解这门手艺"))

    def test_rules_match_every_core_sentence(self):
        report = evaluation_report(ROOT / "wenmai" / "gold.json")
        self.assertEqual(report["rules_core"]["exact_match"], 1.0)
        self.assertFalse(report["rules_core"]["misses"])
        covered = set()
        for item in json.loads((ROOT / "wenmai" / "gold.json").read_text(encoding="utf-8"))["core"]:
            covered.update(item["labels"])
        self.assertEqual(covered, set(CODE_NAMES))

    def test_training_sentences_do_not_copy_the_gold_file(self):
        gold = json.loads((ROOT / "wenmai" / "gold.json").read_text(encoding="utf-8"))
        forbidden = {item["text"] for item in gold["core"] + gold["hard"]}
        leaked = [text for text, _ in template_examples() if text in forbidden]
        self.assertEqual(leaked, [])

    def test_char_model_learns_a_praise_cue_and_ignores_laughter(self):
        model = fit_char_model(template_examples(), epochs=8)
        self.assertIn("制作认可", model.predict("画面质感拉满，服化道也好"))
        self.assertEqual(model.predict("哈哈哈哈"), set())

    def test_old_collections_are_not_the_working_set(self):
        specs = json.loads((ROOT / "danmaku" / "collections.json").read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in specs], ["tradition-hot"])
        self.assertEqual(specs[0]["list"], "hot_search")
        groups = {query["group"] for query in specs[0]["queries"]}
        self.assertEqual(groups, set(specs[0]["groups"]))
        lists = ROOT / "danmaku" / "lists"
        banned = {
            "luoxiang",
            "yuanshen-preview",
            "new-sanguo",
            "xiaoyuehan",
            "heishenhua",
            "guo-criminal-3",
            "luoxiang-live",
            "guo-spoken",
            "coverage.json",
            "release-sha256.txt",
        }
        if lists.exists():
            self.assertFalse(banned & {path.name for path in lists.iterdir()})


class PipelineTests(unittest.TestCase):
    def test_analyze_and_render_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "pool"
            corpus.mkdir()
            rows = [
                {"id": 1, "progress_ms": 1000, "timeline_ms": 1000, "content": "后母戊鼎画面质感拉满"},
                {"id": 2, "progress_ms": 2000, "timeline_ms": 2000, "content": "哈哈哈哈"},
                {"id": 3, "progress_ms": 3000, "timeline_ms": 3000, "content": "想学昆曲，求教程"},
            ]
            with gzip.open(corpus / "BV1TEST.jsonl.gz", "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            (corpus / "BV1TEST.meta.json").write_text(
                json.dumps({"parts": [{"duration": 60}]}),
                encoding="utf-8",
            )
            listing = root / "_videos.json"
            listing.write_text(
                json.dumps(
                    [
                        {
                            "bvid": "BV1TEST",
                            "title": "测试",
                            "group": "museum",
                            "group_title": "文物博物馆",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            summary = analyze(corpus, listing, root / "out")
            self.assertEqual(summary["danmaku"], 3)
            self.assertEqual(summary["videos"], 1)
            self.assertEqual(summary["empty_pools"], 0)
            self.assertGreater(summary["by_code"]["制作认可"], 0)
            self.assertGreater(summary["by_code"]["文化符号提及"], 0)
            self.assertIn("文物博物馆", summary["groups"]["museum"]["title"])
            page = render(summary)
            self.assertIn("<svg", page)
            self.assertIn("一条弹幕可以同时", page)
            for code in CODE_NAMES:
                self.assertIn(code, page)
            self.assertNotIn("后母戊鼎画面质感拉满", page)
            self.assertIn("相对抬升", page)
            self.assertIn("当前池为空", page)
            self.assertIn("点互信息", page)
            self.assertIn("每万条", page)
            self.assertIn("停留", page)
            self.assertIn("有字", page)
            museum = summary["groups"]["museum"]
            self.assertEqual(museum["empty"], 0)
            self.assertIn("by_code", museum)
            self.assertIn("code_lift", museum)
            self.assertIn("words", museum)
            self.assertEqual(len(summary["video_stars"]), 1)
            self.assertEqual(summary["video_stars"][0]["dominant"], "知识认知")
            self.assertIn("六维星图", page)
            codes = summary["codes"]
            left = codes.index("制作认可")
            right = codes.index("文化符号提及")
            self.assertGreater(summary["pmi"][left][right], 0)
            self.assertEqual(len(summary["hours"]["coded"]), 24)
            self.assertIn("lift", summary["groups"]["museum"])
            self.assertIn("concentration", summary)
            self.assertTrue((root / "out" / "summary.json").exists())
            self.assertIn("文化符号提及", classify("后母戊鼎"))

    def test_starfield_mix_leans_toward_the_heavier_dimension(self):
        from wenmai.starfield import place, render_view

        knowledge = place({"知识认知": 1})
        aesthetic = place({"审美鉴赏": 1})
        mixed = place({"知识认知": 0.8, "审美鉴赏": 0.2})

        def gap(left, right):
            return sum((a - b) ** 2 for a, b in zip(left, right))

        self.assertLess(gap(mixed, knowledge), gap(mixed, aesthetic))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "star.png"
            render_view(
                [
                    {
                        "bvid": "BV1STAR",
                        "title": "测试",
                        "group_title": "文物博物馆",
                        "danmaku": 40,
                        "coded": 10,
                        "by_dimension": {"知识认知": 8, "审美鉴赏": 2},
                        "dominant": "知识认知",
                    },
                    {
                        "bvid": "BV1DUST",
                        "title": "闲谈",
                        "group_title": "典籍诗词",
                        "danmaku": 12,
                        "coded": 0,
                        "by_dimension": {},
                        "dominant": "",
                    },
                ],
                0.55,
                0.42,
                "测试角度",
                path,
            )
            self.assertGreater(path.stat().st_size, 1000)

    def test_fightin_words_keeps_a_gram_unique_to_one_group(self):
        group = Counter({"青铜": 40, "这个": 80})
        rest = Counter({"这个": 200, "真的": 50})
        words = fightin_words(group, rest)
        grams = [item["gram"] for item in words]
        self.assertIn("青铜", grams)
        self.assertNotIn("这个", grams)
        self.assertGreater(next(item["z"] for item in words if item["gram"] == "青铜"), 2)
        spread = fightin_words(
            Counter({"赐福": 40, "青铜": 30}),
            Counter({"真的": 80}),
            video_counts=Counter({"赐福": 1, "青铜": 8}),
            top_counts=Counter({"赐福": 40, "青铜": 6}),
        )
        spread_grams = [item["gram"] for item in spread]
        self.assertIn("青铜", spread_grams)
        self.assertNotIn("赐福", spread_grams)
        self.assertGreaterEqual(spread[0]["videos"], 8)

    def test_gpu_script_can_be_imported_without_torch(self):
        self.assertIn("--cpu", build_parser().format_help())
        self.assertIn("--check", build_parser().format_help())
        self.assertIn("chinese-macbert", build_parser().get_default("model"))
        code = gpu_main(
            ["--data", str(ROOT / "wenmai" / "sample_silver.jsonl"), "--out", "/tmp/wenmai-gpu-unused", "--check"]
        )
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
