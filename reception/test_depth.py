import json
import unittest

from reception.load import Pool
from reception.depth import build_depth, render_depth
from reception.test_voice import _repeat, _video
from reception.voice import keys_for


class DepthTests(unittest.TestCase):
    def test_question_outside_a_case_pool_does_not_invent_keys(self):
        title = "理发变贷款？这还是理发店吗"
        self.assertEqual(keys_for(title, "new-sanguo"), [])
        self.assertEqual(keys_for(title, "guo-criminal-3"), [])
        self.assertEqual(keys_for("劫匪：你一点都不慌吗", "guo-criminal-3"), ["劫匪"])
        self.assertEqual(keys_for("冒充客户算不算商业间谍", "guo-criminal-3"), ["冒充客户", "商业间谍"])
        self.assertIn("酒驾", keys_for("只在停车场开了一段，没开出去算酒驾吗", "样例"))

    def test_same_affair_keeps_each_films_own_words(self):
        parents = _video(
            "BV父母",
            "父母把孩子活活打死，那还是人吗",
            _repeat("感谢父母不杀之恩", 0.4, 6) + _repeat("老师好", 0.1, 4),
        )
        defence_a = _video(
            "BV尺度",
            "正当防卫的尺度",
            _repeat("正当防卫存在的意义就是鼓励人民群众勇于反抗不法侵害", 0.5, 3),
        )
        defence_b = _video(
            "BV二十",
            "电影第二十条观后，正当防卫的难题与破题",
            _repeat("罗老师的观点是不是建立在正当防卫没有被滥用的前提下", 0.6, 2),
        )
        open_question = _video(
            "BV死刑",
            "死刑究竟应不应该废除",
            [(f"第{index}种看法里要谈死刑本身", 0.2 + index / 100) for index in range(8)],
        )
        shot, report = build_depth([Pool("luoxiang", [parents, defence_a, defence_b, open_question])])
        affairs = {item["affair"]: item for item in report["directions"]}
        self.assertIn("父母", affairs)
        self.assertIn("正当防卫", affairs)
        defence = affairs["正当防卫"]
        texts = [film["lines"][0]["text"] for film in defence["films"]]
        self.assertEqual(len(texts), 2)
        self.assertIn("鼓励人民群众勇于反抗不法侵害", defence["reading"])
        self.assertIn("没有被滥用", defence["reading"])
        self.assertIn("服务", defence["reading"])
        html = render_depth(shot, report)
        self.assertIn("感谢父母不杀之恩", html)
        self.assertIn("没有被滥用", html)
        self.assertIn("民声", html)
        self.assertIn("没有发言者", html)
        self.assertNotIn("老师好", json.dumps(report["directions"], ensure_ascii=False))
        self.assertNotIn("<svg", html)
        self.assertNotIn("polyline", html)
        self.assertEqual(report["shown"]["bvid"], "BV父母")
        self.assertIn("3 支的回答收成了反复的原话", report["depth_note"])
        self.assertIn(report["depth_note"], html)
        self.assertEqual(report["unsettled"][0]["bvid"], "BV死刑")
        self.assertNotIn("第0种看法", html)
        robbery = _video(
            "BV抢劫",
            "弟弟被抢劫在工地撞人到楼下",
            [(f"看法{index}，被抢劫之后可以无限防卫", 0.3) for index in range(4)]
            + [(f"另一条完全不同的话{index}还是抢劫", 0.4) for index in range(4)],
        )
        _, robbery_report = build_depth([Pool("guo-spoken", [robbery])])
        pieces = robbery_report["unsettled"][0]["pieces"]
        self.assertTrue(any("无限防卫" in piece["text"] and piece["n"] == 4 for piece in pieces))
        robbery_html = render_depth(shot, robbery_report)
        self.assertIn("无限防卫", robbery_html)
        self.assertNotIn("说法0", robbery_html)


if __name__ == "__main__":
    unittest.main()
