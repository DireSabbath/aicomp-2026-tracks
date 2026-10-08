import gzip
import json
import tempfile
import unittest
from pathlib import Path

from collections import Counter

from wenmai.analyze import analyze, collect_gap_texts, fightin_words, is_gap_candidate, is_margin_candidate
from wenmai.budget import (
    ARCH_MODEL,
    PRIMARY_MODEL,
    SCALE_MODEL,
    MarginBook,
    budget_model_names,
    fold_predictions,
    inference_batch_for,
    next_follow_up,
    public_budget_run,
    smaller_batch,
    summarize_runs,
    write_budget,
)
from wenmai.classify import classify, find_symbols
from wenmai.codebook import CODE_NAMES, DIMENSIONS
from wenmai.model import (
    evaluation_report,
    fit_char_model,
    rule_gap_counts,
    template_examples,
    thresholds_from_scores,
)
from wenmai.render import render
from wenmai.resample import bootstrap_lifts
from wenmai.train_gpu import (
    GPU_NOTE,
    WEIGHT_IGNORE,
    attach_corpus,
    build_parser,
    disagreement_counts,
    fit_with_oom_retry,
    gold_public,
    warm_model_cache,
    main as gpu_main,
    nearest_queue,
)

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
        self.assertIn("制作认可", classify("这期讲得真好"))
        self.assertIn("古今共情", classify("古代人也太厉害了"))
        self.assertEqual(classify("有字幕不错"), {"观看体验"})
        self.assertEqual([name for name, _ in find_symbols("千里江山图")], ["千里江山图"])
        self.assertEqual([name for name, _ in find_symbols("这幅千里江山")], ["千里江山"])

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
            self.assertIn("按一支片子读", page)
            self.assertIn("规则没标、模型标了", page)
            self.assertIn("稀有类的支撑", page)
            self.assertEqual(len(summary["video_cards"]), 1)
            self.assertIn("rule_gap", summary)
            self.assertNotIn("text", summary["rule_gap"])
            self.assertIn("support", summary)
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

    def test_rule_gap_counts_do_not_keep_the_sentence(self):
        import numpy as np

        gap = rule_gap_counts(lambda text: {"学习意愿"} if "想学" in text else set(), ["想学这门手艺", "哈哈"])
        self.assertEqual(gap["sample_n"], 2)
        self.assertEqual(gap["fired_n"], 1)
        self.assertEqual(gap["by_code"]["学习意愿"], 1)
        self.assertNotIn("想学这门手艺", json.dumps(gap, ensure_ascii=False))
        matrix = np.array([[0.9, 0.1], [0.2, 0.8], [0.05, 0.1]], dtype=np.float32)
        targets = np.array([[1, 0], [0, 1], [0, 0]], dtype=np.int8)
        thresholds = thresholds_from_scores(matrix, targets)
        self.assertAlmostEqual(float(thresholds[0]), 0.25)
        self.assertGreaterEqual(float(thresholds[1]), 0.15)
        self.assertIn("不是从弹幕里抽出来的人工金标", GPU_NOTE)

    def test_empty_pool_card_and_symbol_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "pool"
            corpus.mkdir()
            coded = {"id": 1, "progress_ms": 1000, "timeline_ms": 1000, "content": "后母戊鼎画面质感拉满"}
            with gzip.open(corpus / "BV1FULL.jsonl.gz", "wt", encoding="utf-8") as handle:
                for index in range(20):
                    row = dict(coded)
                    row["id"] = index
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            (corpus / "BV1FULL.meta.json").write_text(json.dumps({"parts": [{"duration": 60}]}), encoding="utf-8")
            with gzip.open(corpus / "BV1EMPTY.jsonl.gz", "wt", encoding="utf-8") as handle:
                handle.write("")
            (corpus / "BV1EMPTY.meta.json").write_text(json.dumps({"parts": [{"duration": 30}]}), encoding="utf-8")
            listing = root / "_videos.json"
            listing.write_text(
                json.dumps(
                    [
                        {"bvid": "BV1FULL", "title": "有字幕", "group": "museum", "group_title": "文物博物馆"},
                        {"bvid": "BV1EMPTY", "title": "空池片", "group": "museum", "group_title": "文物博物馆"},
                    ]
                ),
                encoding="utf-8",
            )
            summary = analyze(corpus, listing, root / "out")
            cards = {card["bvid"]: card for card in summary["video_cards"]}
            self.assertTrue(cards["BV1EMPTY"]["empty"])
            self.assertEqual(cards["BV1EMPTY"]["danmaku"], 0)
            self.assertIsNone(cards["BV1EMPTY"]["lift"]["知识认知"])
            self.assertFalse(cards["BV1FULL"]["empty"])
            self.assertEqual(cards["BV1FULL"]["symbols"][0]["name"], "后母戊鼎")
            self.assertAlmostEqual(cards["BV1FULL"]["lift"]["知识认知"], 1.0)
            names = [item["name"] for item in summary["symbol_bindings"]]
            self.assertIn("后母戊鼎", names)
            page = render(summary)
            self.assertIn("空池片", page)
            self.assertNotIn("后母戊鼎画面质感拉满", page)
            self.assertIn("相对其他符号点名", page)
            self.assertNotIn("是全库该维密度", "".join(summary.get("findings") or []))


class ResampleAndGpuReadoutTests(unittest.TestCase):
    def test_gap_candidate_rejects_coded_and_laughter(self):
        found = None
        for index in range(2000):
            candidate = f"测试缺口句子{index}号"
            if is_gap_candidate(candidate, set()):
                found = candidate
                break
        self.assertIsNotNone(found)
        self.assertFalse(is_gap_candidate(found, {"学习意愿"}))
        self.assertFalse(is_gap_candidate("哈哈哈哈", set()))
        self.assertFalse(is_gap_candidate("好", set()))

    def test_gap_collection_follows_the_same_rule_and_drops_empty_pools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "pool"
            corpus.mkdir()
            kept = None
            for index in range(400):
                text = f"缺口抽样用句{index}"
                if is_gap_candidate(text, set()):
                    kept = text
                    break
            self.assertIsNotNone(kept)
            with gzip.open(corpus / "BV1GAP.jsonl.gz", "wt", encoding="utf-8") as handle:
                handle.write(json.dumps({"id": 1, "content": kept}, ensure_ascii=False) + "\n")
                handle.write(json.dumps({"id": 2, "content": "哈哈哈哈"}, ensure_ascii=False) + "\n")
            with gzip.open(corpus / "BV1EMPTY.jsonl.gz", "wt", encoding="utf-8") as handle:
                handle.write("")
            listing = root / "_videos.json"
            listing.write_text(
                json.dumps(
                    [
                        {"bvid": "BV1GAP", "group": "museum", "group_title": "文物博物馆"},
                        {"bvid": "BV1EMPTY", "group": "museum", "group_title": "文物博物馆"},
                    ]
                ),
                encoding="utf-8",
            )
            texts = collect_gap_texts(corpus, listing)
            self.assertEqual(texts, [kept])
            summary = analyze(corpus, listing, root / "out")
            self.assertNotIn(kept, json.dumps(summary, ensure_ascii=False))

    def test_corpus_attachment_counts_gap_and_keeps_margin_text_out_of_metrics(self):
        import numpy as np
        from argparse import Namespace

        gap_text = None
        for index in range(800):
            text = f"未编码缺口{index}号"
            if is_gap_candidate(text, set()):
                gap_text = text
                break
        self.assertIsNotNone(gap_text)
        near = "贴阈值测句甲"
        coded = "想学这门手艺"
        self.assertIn("学习意愿", classify(coded))
        self.assertFalse(classify(near))
        self.assertTrue(is_margin_candidate(near, set()))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "pool"
            corpus.mkdir()
            with gzip.open(corpus / "BV1GAP.jsonl.gz", "wt", encoding="utf-8") as handle:
                for content in (gap_text, near, coded, "哈哈哈哈", "  "):
                    handle.write(json.dumps({"content": content}, ensure_ascii=False) + "\n")
            listing = root / "_videos.json"
            listing.write_text(
                json.dumps([{"bvid": "BV1GAP", "group": "museum", "group_title": "文物博物馆"}]),
                encoding="utf-8",
            )
            out = root / "gpu"

            def score(texts):
                rows = []
                for text in texts:
                    row = [0.0] * len(CODE_NAMES)
                    if "贴阈值" in text:
                        row[0] = 0.49
                    rows.append(row)
                return np.array(rows, dtype=np.float32)

            fragment = attach_corpus(
                None,
                None,
                None,
                Namespace(
                    corpus=corpus,
                    list=listing,
                    margin_limit=2,
                    margin_per_code=1,
                    margin_out=None,
                    out=out,
                    max_length=64,
                ),
                np.array([0.5] * len(CODE_NAMES), dtype=np.float32),
                1,
                write_margin=True,
                score_fn=score,
            )
            self.assertEqual(fragment["gap"]["sample_n"], 1)
            self.assertEqual(fragment["gap"]["fired_n"], 0)
            self.assertEqual(fragment["corpus"]["coded_n"], 1)
            self.assertGreaterEqual(fragment["corpus"]["unlabeled_n"], 1)
            self.assertGreater(fragment["corpus"]["disagreement"]["rule_only"]["学习意愿"], 0)
            public = json.dumps(
                {key: fragment[key] for key in ("corpus", "gap")},
                ensure_ascii=False,
            )
            self.assertNotIn(gap_text, public)
            self.assertNotIn(near, public)
            margin = json.loads((out / "margin-queue.json").read_text(encoding="utf-8"))
            self.assertIn(near, [row["text"] for row in margin["rows"]])
            self.assertNotIn("哈哈哈哈", json.dumps(margin, ensure_ascii=False))
            self.assertTrue(margin["per_code"][CODE_NAMES[0]])

    def test_oom_retry_halves_batch_and_cache_skips_other_formats(self):
        seen = []

        def fit(batch):
            seen.append(batch)
            if batch > 2:
                raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
            return {"ok": batch}

        packed, used = fit_with_oom_retry(fit, 8)
        self.assertEqual(seen, [8, 4, 2])
        self.assertEqual(used, 2)
        self.assertEqual(packed["ok"], 2)

        def other(_batch):
            raise RuntimeError("disk full")

        with self.assertRaises(RuntimeError) as caught:
            fit_with_oom_retry(other, 8)
        self.assertIn("disk full", str(caught.exception))
        calls = []

        def download(**kwargs):
            calls.append(kwargs)

        warm_model_cache(["hfl/chinese-macbert-base"], download=download)
        self.assertEqual(calls[0]["repo_id"], "hfl/chinese-macbert-base")
        self.assertEqual(calls[0]["ignore_patterns"], list(WEIGHT_IGNORE))
        self.assertIn("*.h5", WEIGHT_IGNORE)
        self.assertNotIn("*.bin", WEIGHT_IGNORE)
        kept = public_budget_run(
            {
                "model": PRIMARY_MODEL,
                "seed": 0,
                "macro_f1": 0.2,
                "train_batch": 4,
                "gap": {"sample_n": 1500, "fired_n": 3, "by_code": {CODE_NAMES[0]: 3}},
                "corpus": {"coded_n": 9, "unlabeled_n": 4, "disagreement": {"model_only": {}, "rule_only": {}}},
            },
            keep_misses=False,
        )
        self.assertEqual(kept["train_batch"], 4)
        self.assertEqual(kept["gap_sample_n"], 1500)
        self.assertEqual(kept["gap_fired_n"], 3)
        self.assertEqual(kept["corpus_coded_n"], 9)
        self.assertNotIn("text", json.dumps(kept, ensure_ascii=False))

    def test_video_bootstrap_point_lift_and_no_sentence(self):
        import numpy as np

        from wenmai.codebook import CODE_NAMES as codes
        from wenmai.codebook import DIM_NAMES as dims

        def blank(group, n, code=None, count=0):
            code_row = np.zeros(len(codes), dtype=np.int32)
            dim_row = np.zeros(len(dims), dtype=np.int32)
            if code:
                code_row[codes.index(code)] = count
                dim_row[dims.index("审美鉴赏")] = count
            return {
                "group": group,
                "group_title": group,
                "n": n,
                "codes": code_row,
                "dims": dim_row,
                "sym_n": 0,
                "sym_dims": np.zeros(len(dims), dtype=np.int32),
                "sym_count": {},
                "sym_by": {},
            }

        records = [
            blank("opera", 20, "传统美学褒扬", 20),
            blank("museum", 20),
        ]
        report = bootstrap_lifts(records, draws=20, seed=0)
        matched = [
            row
            for row in report["code_lifts"]
            if row["group"] == "opera" and row["code"] == "传统美学褒扬"
        ]
        self.assertEqual(len(matched), 1)
        self.assertAlmostEqual(matched[0]["lift"], 2.0)
        self.assertLessEqual(matched[0]["low"], matched[0]["lift"])
        self.assertGreaterEqual(matched[0]["high"], matched[0]["lift"])
        self.assertNotIn("text", json.dumps(report, ensure_ascii=False))
        dumped = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("画面质感", dumped)

    def test_gpu_readout_keeps_gold_misses_and_hides_margin_text_from_counts(self):
        import numpy as np

        false_pos = [0] * len(CODE_NAMES)
        false_neg = [0] * len(CODE_NAMES)
        false_pos[0] = 1
        false_neg[1] = 4
        counts = disagreement_counts(false_pos, false_neg)
        self.assertEqual(counts["model_only"][CODE_NAMES[0]], 1)
        self.assertEqual(counts["rule_only"][CODE_NAMES[1]], 4)
        self.assertNotIn("text", json.dumps(counts, ensure_ascii=False))
        public = gold_public(
            {
                "exact_match": 0.5,
                "micro_f1": 0.5,
                "macro_f1": 0.5,
                "n": 1,
                "misses": [{"text": "自写句", "missing": ["学习意愿"], "extra": []}],
            }
        )
        self.assertEqual(public["misses"][0]["text"], "自写句")
        probs = np.array([[0.50, 0.10] + [0.0] * 15, [0.90, 0.20] + [0.0] * 15], dtype=np.float32)
        thresholds = np.array([0.5] * 17, dtype=np.float32)
        queue = nearest_queue(["离阈值近的一句", "离阈值远的一句"], probs, thresholds, limit=1)
        self.assertEqual(queue[0]["text"], "离阈值近的一句")
        self.assertLess(queue[0]["distance"], 0.2)
        gap = rule_gap_counts(lambda text: {"学习意愿"} if "想学" in text else set(), ["想学", "哈哈"])
        self.assertNotIn("想学", json.dumps({key: gap[key] for key in ("sample_n", "fired_n", "by_code")}, ensure_ascii=False))

    def test_resample_artifact_matches_summary_and_hides_text(self):
        resample_path = ROOT / "wenmai" / "results" / "resample.json"
        summary_path = ROOT / "wenmai" / "results" / "summary.json"
        resample = json.loads(resample_path.read_text(encoding="utf-8"))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(resample["videos"], 564)
        self.assertEqual(resample["draws"], 1000)
        self.assertEqual(resample["seed"], 0)
        self.assertNotIn('"text"', resample_path.read_text(encoding="utf-8"))
        for row in resample["code_lifts"]:
            group = summary["groups"][row["group"]]
            self.assertAlmostEqual(row["lift"], group["code_lift"][row["code"]])
            self.assertEqual(row["count"], group["by_code"][row["code"]])
        for row in resample["dimension_lifts"]:
            group = summary["groups"][row["group"]]
            self.assertAlmostEqual(row["lift"], group["lift"][row["dimension"]])

    def test_margin_candidate_is_the_unlabeled_band_and_gap_is_its_subset(self):
        self.assertFalse(is_margin_candidate("哈哈哈哈", set()))
        self.assertFalse(is_margin_candidate("想学昆曲", {"学习意愿"}))
        self.assertFalse(is_margin_candidate("好", set()))
        sentence = "想学这门手艺啊"
        self.assertTrue(is_margin_candidate(sentence, set()))
        if is_gap_candidate(sentence, set()):
            self.assertTrue(is_margin_candidate(sentence, set()))

    def test_3090_three_hours_schedules_scale_then_seeds(self):
        import numpy as np

        elapsed = 570.0
        finished = set()
        seed = 1
        jobs = []
        while True:
            job = next_follow_up(
                elapsed_s=elapsed,
                budget_s=3 * 3600,
                train_s=90,
                pass_s=480,
                vram_gb=23.7,
                primary_model=PRIMARY_MODEL,
                finished=finished,
                next_seed=seed,
            )
            if job is None:
                break
            jobs.append(job)
            finished.add((job["model"], job["seed"], job["kind"]))
            elapsed += job["cost_s"]
            if job["kind"] == "train":
                seed += 1
        self.assertEqual(jobs[0]["model"], SCALE_MODEL)
        self.assertEqual(jobs[0]["kind"], "pass")
        self.assertEqual(jobs[0]["infer_batch"], 64)
        self.assertEqual(jobs[1]["model"], ARCH_MODEL)
        self.assertGreater(sum(1 for job in jobs if job["kind"] == "train"), 20)
        self.assertLessEqual(elapsed, 3 * 3600)
        self.assertLess(3 * 3600 - elapsed, 90 + 90)
        self.assertEqual(inference_batch_for(23.7, PRIMARY_MODEL), 256)
        narrow = next_follow_up(
            elapsed_s=570,
            budget_s=3 * 3600,
            train_s=90,
            pass_s=480,
            vram_gb=10,
            primary_model=PRIMARY_MODEL,
            finished=set(),
            next_seed=1,
        )
        self.assertEqual(narrow["model"], ARCH_MODEL)
        self.assertIsNone(
            next_follow_up(
                elapsed_s=10700,
                budget_s=10800,
                train_s=90,
                pass_s=480,
                vram_gb=24,
                primary_model=PRIMARY_MODEL,
                finished={(SCALE_MODEL, 0, "pass"), (ARCH_MODEL, 0, "pass")},
                next_seed=3,
            )
        )
        probs = np.array(
            [
                [1.0, 0.0] + [0.0] * 15,
                [0.51, 0.0] + [0.0] * 15,
                [0.0, 0.0] + [0.0] * 15,
            ],
            dtype=np.float32,
        )
        book = MarginBook(1)
        stats = fold_predictions(
            ["已编码的一句", "贴着阈值", "离得远"],
            [{CODE_NAMES[1]}, set(), set()],
            probs,
            np.array([0.5] * 17, dtype=np.float32),
            book,
        )
        self.assertEqual(stats["coded_n"], 1)
        self.assertEqual(stats["fn"][1], 1)
        self.assertEqual(stats["fp"][0], 1)
        self.assertEqual(book.ranked()[0]["text"], "贴着阈值")
        crowded = MarginBook(1)
        crowded.consider("同一句", 0.4, [])
        crowded.consider("同一句", 0.05, ["学习意愿"])
        crowded.consider("另一句", 0.2, [])
        self.assertEqual([row["text"] for row in crowded.ranked()], ["同一句"])
        self.assertAlmostEqual(crowded.ranked()[0]["distance"], 0.05)
        rare = CODE_NAMES[-1]
        books = {code: MarginBook(1) for code in CODE_NAMES}
        near = [0.0] * 17
        near[0] = 0.5
        far_on_rare = [0.0] * 17
        far_on_rare[CODE_NAMES.index(rare)] = 0.5
        fold_predictions(
            ["贴着第一类", "贴着稀有类"],
            [set(), set()],
            np.array([near, far_on_rare], dtype=np.float32),
            np.array([0.5] * 17, dtype=np.float32),
            MarginBook(1),
            books,
        )
        self.assertEqual(books[rare].ranked()[0]["text"], "贴着稀有类")
        self.assertEqual(books[CODE_NAMES[0]].ranked()[0]["text"], "贴着第一类")
        names = budget_model_names(PRIMARY_MODEL, 23.7)
        self.assertEqual(names[0], PRIMARY_MODEL)
        self.assertIn(SCALE_MODEL, names)
        self.assertIn(ARCH_MODEL, names)
        self.assertNotIn(SCALE_MODEL, budget_model_names(PRIMARY_MODEL, 10))
        public = public_budget_run(
            {
                "model": PRIMARY_MODEL,
                "seed": 1,
                "macro_f1": 0.5,
                "per_code_f1": {},
                "gold_core": {"exact_match": 1.0, "misses": [{"text": "自写句", "missing": [], "extra": []}]},
                "gold_hard": {"exact_match": 0.0},
                "corpus": {"coded_n": 3, "unlabeled_n": 2, "disagreement": {"model_only": {}, "rule_only": {}}},
            },
            keep_misses=False,
        )
        self.assertNotIn("text", json.dumps(public, ensure_ascii=False))
        summary = summarize_runs(
            [
                {"model": PRIMARY_MODEL, "macro_f1": 0.2, "gold_core_exact": 0.5, "gold_hard_exact": 0.0, "per_code_f1": {CODE_NAMES[0]: 0.1}},
                {"model": PRIMARY_MODEL, "macro_f1": 0.4, "gold_core_exact": 1.0, "gold_hard_exact": 0.0, "per_code_f1": {CODE_NAMES[0]: 0.3}},
                {"model": SCALE_MODEL, "macro_f1": 0.9, "gold_core_exact": 1.0, "gold_hard_exact": 1.0},
                {"model": PRIMARY_MODEL, "error": "out of memory"},
            ],
            PRIMARY_MODEL,
        )
        self.assertEqual(summary["primary_runs"], 2)
        self.assertEqual(summary["macro_f1"]["min"], 0.2)
        self.assertEqual(summary["macro_f1"]["max"], 0.4)
        self.assertEqual(summary["per_code_f1"][CODE_NAMES[0]]["min"], 0.1)
        self.assertEqual(summary["per_code_f1"][CODE_NAMES[0]]["max"], 0.3)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "budget.json"
            write_budget(path, {"summary": summary})
            self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["summary"]["primary_runs"], 2)
        self.assertIsNone(smaller_batch(8, "other error"))
        self.assertEqual(smaller_batch(8, "CUDA out of memory"), 4)


if __name__ == "__main__":
    unittest.main()
