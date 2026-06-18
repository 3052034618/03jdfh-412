"""单元测试 - 增强版（覆盖配置、同义词、路径片段、误报收紧等新功能）"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from chainchecker.parser import parse_outline_text, Node
from chainchecker.graph import traverse_all_paths, GameState, PathRecord
from chainchecker.checkers import (
    check_unreachable_endings,
    check_conflicts,
    check_weak_foreshadowing,
    run_all_checks,
    _clue_matches_truth,
)
from chainchecker.config import CheckerConfig


class TestConfig(unittest.TestCase):
    def test_synonym_matching(self):
        config = CheckerConfig(
            item_synonyms={"破损铃铛": ["铃铛碎片", "铜铃"]}
        )
        self.assertEqual(config.resolve_item_name("铃铛碎片"), "破损铃铛")
        self.assertEqual(config.resolve_item_name("铜铃"), "破损铃铛")
        self.assertEqual(config.resolve_item_name("破损铃铛"), "破损铃铛")
        self.assertTrue(config.items_match("铃铛碎片", "铜铃"))
        self.assertFalse(config.items_match("铃铛碎片", "日记"))

    def test_ignore_disposable_item(self):
        config = CheckerConfig(ignore_items=["火柴", "一次性钥匙"])
        self.assertTrue(config.is_disposable_item("火柴"))
        self.assertFalse(config.is_disposable_item("日记"))

    def test_ignore_issue_pattern(self):
        config = CheckerConfig(ignore_issues=["*弱铺垫*"])
        from chainchecker.checkers import Issue
        issue = Issue(issue_type="弱铺垫", severity="warning", message="测试")
        self.assertTrue(config.should_ignore_issue(issue.message, issue.issue_type))

    def test_ignore_ending_pattern(self):
        config = CheckerConfig(ignore_endings=["*测试*"])
        self.assertTrue(config.should_ignore_ending("测试结局"))
        self.assertFalse(config.should_ignore_ending("真结局"))


class TestGameStateWithSynonyms(unittest.TestCase):
    def test_synonym_has_item(self):
        config = CheckerConfig(
            item_synonyms={"破损铃铛": ["铃铛碎片"]}
        )
        s = GameState(items=frozenset(["铃铛碎片"]), config=config)
        # 虽然物品叫"铃铛碎片"，但用"破损铃铛"查询也能查到
        self.assertTrue(s.has_item("破损铃铛"))
        self.assertTrue(s.has_item("铃铛碎片"))

    def test_synonym_remove(self):
        config = CheckerConfig(
            item_synonyms={"破损铃铛": ["铃铛碎片"]}
        )
        s = GameState(items=frozenset(["铃铛碎片"]), config=config)
        # 用同义词名"破损铃铛"移除，应该能移除"铃铛碎片"
        s2 = s.with_item_removed("破损铃铛")
        self.assertFalse(s2.has_item("铃铛碎片"))
        self.assertFalse(s2.has_item("破损铃铛"))


class TestParserBackwardCompat(unittest.TestCase):
    """向后兼容性测试 - 旧的单文件解析功能应该仍然可用"""
    def test_parse_simple_markers(self):
        text = "拾取物品 @item:+破损铃铛"
        outline = parse_outline_text(text)
        self.assertEqual(len(outline.nodes), 1)
        node = list(outline.nodes.values())[0]
        self.assertIn("破损铃铛", node.items_add)
        # 新字段 source_file 应该被设置
        self.assertEqual(node.source_file, "<text>")

    def test_parse_ending(self):
        text = "进入井底 @ending:井底结局"
        outline = parse_outline_text(text)
        node = list(outline.nodes.values())[0]
        self.assertTrue(node.is_ending)
        self.assertIn("井底结局", node.endings)
        # 新方法 get_display_text
        self.assertIn("井底结局", node.get_display_text())


class TestUnreachableEndings(unittest.TestCase):
    def test_unreachable_ending_detected(self):
        text = """开始
    @choice:走左路
        @ending:左路结局
    @choice:走右路
        @ending:右路结局
    隐藏房间 @cond:不存在的钥匙
        @ending:隐藏结局"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_unreachable_endings(outline, traversal)
        unreachable_names = [i.message for i in issues]
        self.assertTrue(any("隐藏结局" in m for m in unreachable_names))
        # 问题应该带有路径片段
        for issue in issues:
            if "隐藏结局" in issue.message:
                self.assertTrue(issue.path_segment or issue.choice_chain)

    def test_all_endings_reachable(self):
        text = """开始
    @choice:走左路
        @ending:左路结局
    @choice:走右路
        @ending:右路结局"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_unreachable_endings(outline, traversal)
        self.assertEqual(len(issues), 0)

    def test_ignore_ending_by_config(self):
        text = """开始
    @ending:测试结局"""
        config = CheckerConfig(ignore_endings=["*测试*"])
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline, config)
        issues = check_unreachable_endings(outline, traversal, config)
        # 测试结局被忽略，所以没有问题
        self.assertEqual(len(issues), 0)


class TestConflictsTighter(unittest.TestCase):
    """收紧后的冲突检查：一次性道具消耗不报"""

    def test_item_lost_then_required_still_detected(self):
        """烧毁日记后，后续仍然要求阅读日记——必须检测"""
        text = """开始
    获得日记 @item:+日记
        @choice:烧毁日记
            烧掉日记 @item:-日记
                阅读灰烬上的字 @cond:日记
                    @ending:灰烬结局"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_conflicts(outline, traversal)
        # 必须检测到这个冲突
        conflict_items = [i for i in issues if "日记" in i.message]
        self.assertTrue(len(conflict_items) > 0, "烧毁日记后又需要应该检测到冲突")
        # 必须是 error 级别
        self.assertTrue(any(i.severity == "error" for i in conflict_items))
        # 必须带有路径片段
        for i in conflict_items:
            self.assertTrue(i.path_segment or i.choice_chain)

    def test_normal_add_remove_disposable_not_reported(self):
        """正常的一次性道具消耗，不报"""
        text = """开始
    获得火柴 @item:+火柴
        点燃蜡烛 @item:-火柴
            房间亮了
                @ending:通关"""
        config = CheckerConfig(ignore_items=["火柴"])
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline, config)
        issues = check_conflicts(outline, traversal, config)
        # 火柴是一次性道具，正常消耗不报
        error_issues = [i for i in issues if i.severity == "error"]
        self.assertEqual(len(error_issues), 0)
        # 也不应该有 warning 关于 add->remove
        warning_about_match = [i for i in issues if "火柴" in i.message]
        self.assertEqual(len(warning_about_match), 0)

    def test_normal_add_remove_without_dependency_not_reported(self):
        """物品获得后失去，只要后续不依赖它，就不报（收紧后）"""
        text = """开始
    获得铃铛 @item:+铃铛
        失去铃铛 @item:-铃铛
            继续前进
                @ending:结束"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_conflicts(outline, traversal)
        # 收紧后：add->remove 只要后续不需要，就不报
        self.assertEqual(len(issues), 0)

    def test_synonym_conflict_detected(self):
        """使用同义词的冲突也应该被检测到"""
        text = """开始
    获得铃铛碎片 @item:+铃铛碎片
        失去破损铃铛 @item:-破损铃铛
            检查物品 @cond:铃铛碎片
                @ending:结束"""
        config = CheckerConfig(
            item_synonyms={"破损铃铛": ["铃铛碎片"]}
        )
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline, config)
        issues = check_conflicts(outline, traversal, config)
        # 同义词的失去也应该检测到冲突
        conflict_items = [i for i in issues if "铃铛" in i.message or "碎片" in i.message]
        self.assertTrue(len(conflict_items) > 0)

    def test_no_conflict_normal_path(self):
        text = """开始
    获得钥匙 @item:+钥匙
        开门 @cond:钥匙
            @ending:通关"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_conflicts(outline, traversal)
        errors = [i for i in issues if i.severity == "error"]
        self.assertEqual(len(errors), 0)


class TestWeakForeshadowingTighter(unittest.TestCase):
    """收紧后的弱铺垫检查：结局现场线索不算铺垫"""

    def test_truth_without_clue_detected(self):
        text = """开始
    进入房间
        @ending:真结局 @truth:母亲是凶手"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_weak_foreshadowing(outline, traversal)
        self.assertTrue(any("母亲是凶手" in i.message for i in issues))
        # 应该带有路径片段
        for i in issues:
            self.assertTrue(i.path_segment or i.choice_chain)

    def test_truth_with_proper_clue_ok(self):
        text = """开始
    发现线索 @clue:母亲衣服上有血迹
        进入房间
            @ending:真结局 @truth:母亲是凶手"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_weak_foreshadowing(outline, traversal)
        self.assertEqual(len(issues), 0)

    def test_ending_clue_not_counted_as_foreshadowing(self):
        """结局现场的线索不算铺垫——必须检测为弱铺垫"""
        text = """开始
    进入房间
        @ending:真结局 @truth:母亲是凶手 @clue:母亲的尸体在眼前"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_weak_foreshadowing(outline, traversal)
        # 结局节点的线索不算铺垫，所以应该报弱铺垫
        self.assertTrue(any("母亲是凶手" in i.message for i in issues),
                        "结局现场的线索不应算作铺垫")

    def test_clue_in_other_path_only_detected(self):
        text = """开始
    @choice:走左路
        发现线索 @clue:母亲衣服上有血迹
            @ending:左路结局
    @choice:走右路
        @ending:右路结局 @truth:母亲是凶手"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_weak_foreshadowing(outline, traversal)
        self.assertTrue(any("母亲是凶手" in i.message for i in issues))

    def test_config_keyword_matching(self):
        """配置的自定义关键词应该能增强匹配"""
        config = CheckerConfig(truth_keywords=["母亲"])
        # 线索中包含"母亲"，真相中也包含"母亲"，应该匹配成功
        self.assertTrue(_clue_matches_truth(
            "母亲的衣服上有血迹",
            "母亲是凶手",
            config
        ))
        # 没有配置关键词时也能用自动提取的
        self.assertTrue(_clue_matches_truth(
            "母亲的衣服上有血迹",
            "母亲是凶手",
            None
        ))


class TestChoicePointAndPathSegment(unittest.TestCase):
    """选择点追踪和路径片段测试"""

    def test_choice_points_recorded(self):
        text = """开始
    @choice:去卧室
        翻找抽屉
            @choice:拿钥匙
                @ending:好结局
            @choice:不拿
                @ending:坏结局"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        # 每条路径应该有2个选择点
        for path in traversal.all_paths:
            if path.reached_endings:
                self.assertEqual(len(path.choice_points), 2)

    def test_path_segment_generation(self):
        text = """开始
    @choice:选择A
        节点1
            节点2
                @ending:结局A"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        for path in traversal.reachable_ending_nodes.get("结局A", []):
            segment = path.format_path_segment(outline)
            # 路径片段应该包含从选择点到结局的节点
            self.assertIn("选择A", segment)
            self.assertIn("结局A", segment)


class TestIntegration(unittest.TestCase):
    def test_full_report_backward_compat(self):
        """向后兼容：单文件完整报告"""
        text = """# 完整测试大纲
开始
    获得日记 @item:+日记
        @choice:阅读日记
            @clue:日记记载母亲行为怪异
                @flag:读过日记
        @choice:烧毁日记
            烧掉日记 @item:-日记
                阅读灰烬 @cond:日记
                    @ending:灰烬结局
    最终章
        @cond:读过日记
            @ending:真相结局 @truth:母亲是井中怨灵
        @ending:隐藏结局 @cond:不存在的钥匙"""
        config = CheckerConfig()  # 空配置
        outline = parse_outline_text(text)
        report = run_all_checks(outline, config)
        # 应检测到：不可达结局(隐藏结局)、条件冲突(灰烬结局路径)
        types = set(i.issue_type for i in report.issues)
        self.assertIn("不可达结局", types)
        self.assertIn("条件冲突", types)
        # 问题应该带有路径片段
        for issue in report.issues:
            if issue.severity == "error":
                self.assertTrue(issue.path_segment or issue.choice_chain,
                                f"问题缺少路径片段: {issue.message}")

    def test_ignore_issue_by_config(self):
        """通过配置忽略弱铺垫问题"""
        text = """开始
    进入房间
        @ending:结局 @truth:母亲是凶手"""
        config = CheckerConfig(ignore_issues=["*弱铺垫*"])
        outline = parse_outline_text(text)
        report = run_all_checks(outline, config)
        types = set(i.issue_type for i in report.issues)
        self.assertNotIn("弱铺垫", types)


class TestNodeDisplay(unittest.TestCase):
    def test_display_text_various_types(self):
        n1 = Node(id="1", line_number=1, text="@ending:测试结局", indent=0, source_file="test.md",
                  endings={"测试结局"})
        self.assertEqual(n1.get_display_text(), "结局:测试结局")

        n2 = Node(id="2", line_number=2, text="@choice:开门", indent=0, source_file="test.md",
                  choice_label="开门")
        self.assertEqual(n2.get_display_text(), "选择:开门")

        n3 = Node(id="3", line_number=3, text="@cond:钥匙 去开门", indent=0, source_file="test.md",
                  conditions={"钥匙"})
        self.assertEqual(n3.get_display_text(), "条件:钥匙")

        n4 = Node(id="4", line_number=4, text="走进黑暗的走廊 @item:+手电筒", indent=0, source_file="test.md")
        self.assertIn("走进黑暗的走廊", n4.get_display_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
