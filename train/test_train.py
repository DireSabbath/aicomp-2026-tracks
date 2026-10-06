import gzip
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from train.corpus import iter_comments, require_known_zip, write_comments
from train.scene import FILM_BVID, extract_frames, gpu_job, write_job
from train.sentiment import fit_classifier, predict, weak_label, write_sentiment
from train.topics import fit_btm
from train.vectors import cosine, drop_glued, propose, shares_span, train_skipgram


def _zip(path: Path, rows: list[dict]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        meta = {"bvid": "BVTEST", "title": "测", "parts": [{"page": 1, "duration": 10}]}
        archive.writestr("demo/BVTEST.meta.json", json.dumps(meta))
        raw = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
        archive.writestr("demo/BVTEST.jsonl.gz", gzip.compress(raw.encode()))


class TrainReadyTests(unittest.TestCase):
    def test_export_drops_speaker_and_keeps_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "demo.zip"
            _zip(
                archive,
                [
                    {
                        "id": 9,
                        "midHash": "secret",
                        "content": "人民万岁",
                        "progress_ms": 1000,
                        "page": 1,
                        "ctime": 20,
                    }
                ],
            )
            manifest = write_comments([archive], root / "out")
            text = (root / "out" / "comments.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("midHash", text)
            self.assertNotIn("secret", text)
            self.assertNotIn('"id"', text)
            self.assertIn("人民万岁", text)
            self.assertEqual(manifest["rows"], 1)
            self.assertFalse(manifest["redistributed"])
            row = next(iter_comments(archive))
            self.assertEqual(row["percent"], 0.1)

    def test_known_zip_rejects_a_bad_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "heishenhua.zip"
            path.write_bytes(b"not-the-release")
            with self.assertRaises(SystemExit):
                require_known_zip(path)

    def test_shared_context_pulls_words_together(self):
        texts = ["悟空好帅"] * 40 + ["大圣好帅"] * 40 + ["西瓜虫真多"] * 40
        vocab, vectors = train_skipgram(texts, dim=24, min_count=8, epochs=12, lr=0.08, seed=1)
        close = cosine(vectors, vocab, "悟空", "大圣")
        far = cosine(vectors, vocab, "悟空", "西瓜")
        self.assertGreater(close, far)
        self.assertGreater(close, 0.2)
        self.assertTrue(shares_span("舌尖上", "尖上的"))
        self.assertFalse(shares_span("悟空", "大圣"))
        texts = texts + ["舌尖上的中国"] * 40
        vocab, vectors = train_skipgram(texts, dim=24, min_count=8, epochs=8, lr=0.08, seed=1)
        pairs = drop_glued(texts, propose(vocab, vectors, min_cosine=0.5))
        self.assertFalse(any(shares_span(pair["a"], pair["b"]) or len(pair["a"]) != len(pair["b"]) for pair in pairs))
        self.assertFalse(any({pair["a"], pair["b"]} == {"舌尖", "尖上"} for pair in pairs))

    def test_btm_separates_two_word_pairs(self):
        docs = [[0, 1]] * 40 + [[2, 3]] * 40
        fitted = fit_btm(docs, n_topics=2, n_vocab=4, iters=20, seed=2)
        topic_sun = int(np.argmax(fitted["phi"][:, 0]))
        topic_moon = int(np.argmax(fitted["phi"][:, 2]))
        self.assertNotEqual(topic_sun, topic_moon)

    def test_sentiment_learns_the_labels_it_is_given(self):
        texts = ["今天好看极了爱了"] * 12 + ["这部难看无聊失望"] * 12
        labels = ["正"] * 12 + ["负"] * 12
        vectorizer, model = fit_classifier(texts, labels)
        guessed = predict(vectorizer, model, ["爱了好看", "无聊失望"])
        self.assertEqual(guessed, ["正", "负"])
        self.assertEqual(weak_label("爱了"), "正")
        self.assertEqual(weak_label("失望"), "负")
        self.assertEqual(weak_label("爱了但失望"), "中性")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            comments = root / "comments.jsonl"
            comments.write_text(
                "\n".join(json.dumps({"content": text}, ensure_ascii=False) for text in texts) + "\n",
                encoding="utf-8",
            )
            payload = write_sentiment(comments, root / "model")
            self.assertTrue(payload["trained"])
            self.assertEqual(payload["label_source"], "lexicon")
            self.assertFalse(payload["human_checked"])

    def test_scene_job_is_untrained_until_gpu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            clip = root / "clip.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=64x64:rate=4:duration=1",
                    "-pix_fmt",
                    "yuv420p",
                    str(clip),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            count = extract_frames(clip, root / "images", fps=2)
            self.assertGreaterEqual(count, 2)
            payload = write_job(root, bvid=FILM_BVID)
            self.assertFalse(payload["trained"])
            self.assertTrue(payload["needs_gpu"])
            joined = "\n".join(payload["commands"])
            self.assertIn("splatfacto", joined)
            self.assertIn("nerfacto", joined)
            self.assertIn(FILM_BVID, payload["bvid"])
            self.assertIn("num-frames-target", joined)
            job = gpu_job(root / "video.mp4", root)
            self.assertFalse(job["video_present"])


if __name__ == "__main__":
    unittest.main()
