"""单元测试 - 验证三类检查器的正确性"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from chainchecker.parser import parse_outline_text
from chainchecker.graph import traverse_all_paths, GameState
from chainchecker.checkers import (
    check_unreachable_endings,
    check_conflicts,
    check_weak_foreshadowing,
    run_all_checks,
)


class TestParser(unittest.TestCase):
    def test_parse_simple_markers(self):
        text = "拾取物品 @item:+破损铃铛"
        outline = parse_outline_text(text)
        self.assertEqual(len(outline.nodes), 1)
        node = list(outline.nodes.values())[0]
        self.assertIn("破损铃铛", node.items_add)

    def test_parse_ending(self):
        text = "进入井底 @ending:井底结局"
        outline = parse_outline_text(text)
        node = list(outline.nodes.values())[0]
        self.assertTrue(node.is_ending)
        self.assertIn("井底结局", node.endings)

    def test_parse_conditions(self):
        text = "开门 @cond:钥匙 @cond:!锁着"
        outline = parse_outline_text(text)
        node = list(outline.nodes.values())[0]
        self.assertIn("钥匙", node.conditions)
        self.assertIn("!锁着", node.conditions)

    def test_parse_flags(self):
        text = "触发事件 @flag:见过母亲 @flag:!警告过"
        outline = parse_outline_text(text)
        node = list(outline.nodes.values())[0]
        self.assertIn("见过母亲", node.flags_set)
        self.assertIn("警告过", node.flags_clear)

    def test_parse_clue_truth(self):
        text = "发现线索 @clue:墙上有血字 @truth:凶手是母亲"
        outline = parse_outline_text(text)
        node = list(outline.nodes.values())[0]
        self.assertIn("墙上有血字", node.clues)
        self.assertIn("凶手是母亲", node.truths)

    def test_indent_hierarchy(self):
        text = """第一章
    进入房间
        发现物品 @item:+钥匙
    离开房间"""
        outline = parse_outline_text(text)
        self.assertEqual(len(outline.nodes), 4)
        root_ids = outline.root_ids
        self.assertEqual(len(root_ids), 1)
        root = outline.get_node(root_ids[0])
        self.assertEqual(len(root.children), 2)


class TestGameState(unittest.TestCase):
    def test_items_and_flags(self):
        s = GameState()
        s2 = s.with_item_added("钥匙").with_flag_set("开门")
        self.assertTrue(s2.has_item("钥匙"))
        self.assertTrue(s2.has_flag("开门"))
        self.assertFalse(s.has_item("钥匙"))

    def test_meets_condition(self):
        s = GameState(items=frozenset(["钥匙"]), flags=frozenset(["见过"]))
        self.assertTrue(s.meets_condition("钥匙"))
        self.assertTrue(s.meets_condition("item:钥匙"))
        self.assertTrue(s.meets_condition("flag:见过"))
        self.assertTrue(s.meets_condition("!没有的物品"))
        self.assertFalse(s.meets_condition("!钥匙"))
        self.assertFalse(s.meets_condition("没见过的东西"))


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


class TestConflicts(unittest.TestCase):
    def test_item_lost_then_required(self):
        """烧毁日记后，后续仍然要求阅读日记——典型冲突"""
        text = """开始
    获得日记 @item:+日记
        @choice:烧毁日记
            烧掉日记 @item:-日记 @flag:烧毁日记
                阅读灰烬上的字 @cond:日记
                    @ending:灰烬结局"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_conflicts(outline, traversal)
        conflict_msgs = [i.message for i in issues]
        self.assertTrue(
            any("日记" in m and ("失去" in m or "条件中仍然需要" in m or "烧毁" in m)
                for m in conflict_msgs),
            f"未检测到日记冲突，实际问题: {conflict_msgs}"
        )

    def test_item_add_remove_warning(self):
        text = """开始
    获得铃铛 @item:+铃铛
        失去铃铛 @item:-铃铛
            @ending:结束"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_conflicts(outline, traversal)
        self.assertTrue(any("铃铛" in i.message for i in issues))

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


class TestWeakForeshadowing(unittest.TestCase):
    def test_truth_without_clue(self):
        text = """开始
    进入房间
        @ending:真结局 @truth:母亲是凶手"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_weak_foreshadowing(outline, traversal)
        self.assertTrue(any("母亲是凶手" in i.message for i in issues))

    def test_truth_with_proper_clue(self):
        text = """开始
    发现线索 @clue:母亲衣服上有血迹
        进入房间
            @ending:真结局 @truth:母亲是凶手"""
        outline = parse_outline_text(text)
        traversal = traverse_all_paths(outline)
        issues = check_weak_foreshadowing(outline, traversal)
        self.assertEqual(len(issues), 0)

    def test_clue_in_other_path_only(self):
        """线索只在另一条路径中出现，当前结局路径没有铺垫"""
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


class TestIntegration(unittest.TestCase):
    def test_full_report(self):
        text = """# 完整测试大纲
开始
    获得日记 @item:+日记
        @choice:阅读日记
            @clue:日记记载母亲行为怪异
                @flag:读过日记
        @choice:烧毁日记
            烧掉日记 @item:-日记 @flag:烧毁日记
                阅读灰烬 @cond:日记
                    @ending:灰烬结局
    最终章
        @cond:读过日记
            @ending:真相结局 @truth:母亲是井中怨灵
        @ending:隐藏结局 @cond:不存在的钥匙"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)
        # 应检测到：不可达结局(隐藏结局)、条件冲突(灰烬结局路径)
        types = set(i.issue_type for i in report.issues)
        self.assertIn("不可达结局", types)
        self.assertIn("条件冲突", types)


if __name__ == "__main__":
    unittest.main(verbosity=2)
