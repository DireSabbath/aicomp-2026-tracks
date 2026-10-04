import contextlib
import gzip
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from reception.load import Pool, Row, Video, load_zip, normalize
from reception.stage import render_shot
from reception.voice import answer_rows, build_voice, is_ritual, main, public_keys


def _row(bvid: str, content: str, percent: float) -> Row:
    return Row(bvid, content, normalize(content), percent, 1)


def _video(bvid: str, title: str, pairs: list[tuple[str, float]]) -> Video:
    return Video(bvid, title, [_row(bvid, content, percent) for content, percent in pairs])


def _repeat(content: str, percent: float, times: int) -> list[tuple[str, float]]:
    return [(content, percent) for _ in range(times)]


class VoiceTests(unittest.TestCase):
    def test_trailer_and_bare_question_do_not_carry_voice(self):
        self.assertEqual(public_keys("原神4.0前瞻特别节目"), [])
        self.assertEqual(public_keys("黑神话实机演示法律"), [])
        self.assertEqual(public_keys("这剧里还能有一个正常人吗"), [])
        self.assertEqual(public_keys("何不取个折中的法子"), [])
        self.assertEqual(public_keys("什么样的殖民地能薅法国羊毛"), [])
        self.assertEqual(public_keys("这就是桃园结义被掩盖的真相"), [])

    def test_public_title_keeps_the_affair_not_the_question_mark(self):
        keys = public_keys("父母把孩子活活打死，那还是人吗")
        self.assertEqual(keys, ["父母", "孩子", "打死"])
        self.assertEqual(public_keys("正当防卫的尺度"), ["正当防卫"])
        self.assertIn("法律", public_keys("法律应该限制未成年人文身吗"))
        self.assertIn("文身", public_keys("法律应该限制未成年人文身吗"))

    def test_ritual_and_echo_do_not_answer(self):
        self.assertTrue(is_ritual("老师好"))
        self.assertTrue(is_ritual("哈哈"))
        video = _video(
            "BV1",
            "父母把孩子活活打死，那还是人吗",
            _repeat("老师好", 0.1, 6)
            + _repeat("梦幻联动", 0.2, 4)
            + _repeat("父母", 0.3, 5)
            + _repeat("感谢父母不杀之恩", 0.4, 4)
            + [("今天天气不错", 0.5)],
        )
        answers = answer_rows(video, public_keys(video.title))
        self.assertEqual({row.content for row in answers}, {"感谢父母不杀之恩"})

    def test_page_quotes_the_repeated_answer(self):
        chorus = _video(
            "BV父母",
            "父母把孩子活活打死，那还是人吗",
            _repeat("老师好", 0.1, 8)
            + _repeat("总有一款适合你", 0.2, 5)
            + _repeat("感谢父母不杀之恩", 0.45, 4)
            + [("谢父母不杀之恩", 0.46), ("谢父母不杀之恩", 0.47)],
        )
        louder_keyword = _video(
            "BV警察",
            "英国警察如何拖垮绑匪",
            _repeat("警察学校", 0.3, 2) + [(f"路过的警察{index}", 0.2) for index in range(12)],
        )
        trailer = _video("BV预告", "新版本前瞻特别节目", _repeat("法律应该怎么改", 0.4, 6))
        second = _video(
            "BV防卫",
            "正当防卫的尺度",
            _repeat("正当防卫存在的意义就是鼓励人民群众勇于反抗不法侵害", 0.5, 2),
        )
        shot, report = build_voice(
            [Pool("样例", [louder_keyword, trailer, second, chorus])]
        )
        self.assertEqual(report["shown"]["bvid"], "BV父母")
        self.assertIn("感谢父母不杀之恩", shot["direction"])
        self.assertIn("服务", shot["direction"])
        self.assertIn("另外 1 支片子", shot["note"])
        self.assertEqual(report["choruses"][0]["bvid"], "BV父母")
        html = render_shot(shot)
        self.assertIn("感谢父母不杀之恩", html)
        self.assertIn("民声", html)
        self.assertIn("服务", html)
        self.assertIn("没有发言者", html)
        self.assertNotIn("老师好", shot["note"])
        self.assertNotIn("总有一款适合你", shot["note"])
        self.assertTrue(all("老师好" not in knot["text"] for knot in shot["knots"]))
        self.assertNotIn("警察学校", html)
        self.assertNotIn("<svg", html)
        self.assertNotIn("polyline", html)
        self.assertNotIn("midHash", html)

    def test_bad_line_is_skipped_and_cli_writes_the_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "sample.zip"
            with zipfile.ZipFile(path, "w") as archive:
                stem = "sample/BV1"
                archive.writestr(
                    stem + ".meta.json",
                    json.dumps(
                        {
                            "bvid": "BV1",
                            "title": "父母把孩子活活打死，那还是人吗",
                            "parts": [{"page": 1, "duration": 10}],
                        },
                        ensure_ascii=False,
                    ),
                )
                rows = [{"content": "感谢父母不杀之恩", "progress_ms": 1000, "page": 1, "ctime": 10}] * 3
                rows.append({"content": "老师好", "progress_ms": 2000, "page": 1, "ctime": 11})
                raw = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
                raw += "\n{broken\n"
                archive.writestr(stem + ".jsonl.gz", gzip.compress(raw.encode()))
            with self.assertRaises(json.JSONDecodeError):
                load_zip(path)
            pool = load_zip(path, skip_bad=True)
            self.assertEqual(pool.skipped, 1)
            self.assertEqual(len(pool.rows), 4)
            out = root / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                main([str(path), "--out", str(out)])
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(report["shown"]["bvid"], "BV1")
            self.assertIn("民声", report["chain"])
            html = (out / "index.html").read_text()
            self.assertIn("感谢父母不杀之恩", html)
            self.assertIn("没有发言者", html)
            self.assertNotIn("<svg", html)
            self.assertNotIn("polyline", html)


if __name__ == "__main__":
    unittest.main()
