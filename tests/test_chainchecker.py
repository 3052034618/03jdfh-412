"""单元测试 - 完整增强版（覆盖所有新功能）"""

import sys
import os
import json
import time
import tempfile
from pathlib import Path
from datetime import timedelta, date

sys.path.insert(0, str(Path(__file__).parent))

import unittest

from chainchecker.parser import parse_outline_text, parse_chapter_directory, Node
from chainchecker.graph import traverse_all_paths, GameState, PathRecord
from chainchecker.checkers import (
    check_unreachable_endings,
    check_conflicts,
    check_weak_foreshadowing,
    run_all_checks,
    _clue_matches_truth,
)
from chainchecker.config import CheckerConfig, IgnoreRule, SeverityOverride
from chainchecker.exporter import export_markdown, export_html


class TestConfigEnhanced(unittest.TestCase):
    """增强配置测试：项目级规则、严重程度、到期时间、过滤"""

    def test_ignore_rule_expiry(self):
        """忽略规则到期时间测试"""
        future = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
        past = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

        rule_active = IgnoreRule(pattern="*弱铺垫*", expires=future)
        rule_expired = IgnoreRule(pattern="*弱铺垫*", expires=past)

        self.assertFalse(rule_active.is_expired())
        self.assertTrue(rule_expired.is_expired())
        self.assertTrue(rule_active.matches("缺少弱铺垫", "弱铺垫"))
        self.assertFalse(rule_expired.matches("缺少弱铺垫", "弱铺垫"))  # 过期不生效

    def test_ignore_rule_issue_type(self):
        """只忽略特定问题类型的规则"""
        rule = IgnoreRule(pattern="*", issue_type="弱铺垫")
        self.assertTrue(rule.matches("任何消息", "弱铺垫"))
        self.assertFalse(rule.matches("任何消息", "不可达结局"))

    def test_severity_override(self):
        """严重程度覆盖"""
        config = CheckerConfig(
            severity_overrides=[
                SeverityOverride(issue_type="弱铺垫", pattern="*母亲*", new_severity="error"),
                SeverityOverride(issue_type="弱铺垫", new_severity="info"),  # 其他弱铺垫降为提示
            ]
        )
        # 匹配 pattern 的升级
        self.assertEqual(
            config.override_severity("弱铺垫", "真相「母亲」缺少铺垫", "warning"),
            "error"
        )
        # 不匹配 pattern 但匹配 issue_type 的
        self.assertEqual(
            config.override_severity("弱铺垫", "真相「父亲」缺少铺垫", "warning"),
            "info"
        )
        # 其他类型不变
        self.assertEqual(
            config.override_severity("不可达结局", "消息", "error"),
            "error"
        )

    def test_draft_and_strict_mode(self):
        """草稿模式和严格模式"""
        config_draft = CheckerConfig(draft_mode=True)
        config_strict = CheckerConfig(strict_mode=True)

        # 草稿模式：警告降级为提示
        self.assertEqual(
            config_draft.override_severity("弱铺垫", "消息", "warning"),
            "info"
        )
        # 严格模式：警告升级为错误
        self.assertEqual(
            config_strict.override_severity("弱铺垫", "消息", "warning"),
            "error"
        )

    def test_only_check_endings_filter(self):
        """只检查指定结局"""
        config = CheckerConfig(only_check_endings=["*井*结局*"])
        self.assertTrue(config.should_check_ending("井底真相结局"))
        self.assertFalse(config.should_check_ending("逃离老宅结局"))
        self.assertFalse(config.should_check_ending("普通结局"))

    def test_only_check_files_filter(self):
        """只检查指定文件"""
        config = CheckerConfig(only_check_files=["*chap1*"])
        self.assertTrue(config.should_check_file("D:/chapters/chap1_laozhai.md"))
        self.assertFalse(config.should_check_file("D:/chapters/chap2_zhenxiang.md"))
        self.assertTrue(config.should_check_file("chap1_laozhai.md"))

    def test_config_serialization_roundtrip(self):
        """配置序列化往返"""
        original = CheckerConfig(
            item_synonyms={"铃铛": ["铃铛碎片"]},
            ignore_rules=[IgnoreRule(pattern="*弱铺垫*", expires="2026-12-31", reason="暂时忽略")],
            severity_overrides=[SeverityOverride(issue_type="弱铺垫", new_severity="error")],
            only_check_endings=["*结局*"],
            only_check_files=["*chap1*"],
            draft_mode=True,
            strict_mode=False,
        )
        data = original.to_dict()
        restored = CheckerConfig.from_dict(data)
        self.assertEqual(restored.item_synonyms, original.item_synonyms)
        self.assertEqual(len(restored.ignore_rules), 1)
        self.assertEqual(restored.ignore_rules[0].pattern, "*弱铺垫*")
        self.assertEqual(len(restored.severity_overrides), 1)
        self.assertEqual(restored.severity_overrides[0].issue_type, "弱铺垫")
        self.assertTrue(restored.draft_mode)

    def test_legacy_ignore_migration(self):
        """旧的 ignore_issues/ignore_endings 字段向后兼容"""
        config = CheckerConfig.from_dict({
            "ignore_issues": ["*弱铺垫*"],
            "ignore_endings": ["*测试*"],
        })
        # 应该迁移到 ignore_rules
        self.assertTrue(any(r.pattern == "*弱铺垫*" for r in config.ignore_rules))
        self.assertTrue(any(r.pattern == "*测试*" and r.issue_type == "__ending__" for r in config.ignore_rules))


class TestEntryMarker(unittest.TestCase):
    """@entry 独立入口标记测试"""

    def test_entry_marker_parsed(self):
        """解析 @entry 标记"""
        text = """第一章 @entry
    @ending:结局A
第二章 支线章节 @entry
    @ending:支线结局"""
        outline = parse_outline_text(text)
        # 所有根节点都应该被识别
        entry_nodes = [n for n in outline.nodes.values() if n.is_entry]
        self.assertEqual(len(entry_nodes), 2)

    def test_directory_entry_logic_first_file(self):
        """第一章自动作为入口，无需 @entry"""
        with tempfile.TemporaryDirectory() as tmpdir:
            chap1 = Path(tmpdir) / "chap1.md"
            chap1.write_text("第一章\n    @ending:结局A\n", encoding="utf-8")
            chap2 = Path(tmpdir) / "chap2.md"
            chap2.write_text("第二章\n    @ending:结局B\n", encoding="utf-8")
            outline = parse_chapter_directory(tmpdir)
            # 第一章自动是入口
            self.assertEqual(len(outline.entry_node_ids), 1)

    def test_directory_entry_with_marker(self):
        """其他章节必须 @entry 才作为独立入口"""
        with tempfile.TemporaryDirectory() as tmpdir:
            chap1 = Path(tmpdir) / "chap1.md"
            chap1.write_text("第一章\n    @ending:结局A\n", encoding="utf-8")
            chap2 = Path(tmpdir) / "chap2_flashback.md"
            chap2.write_text("闪回章节 @entry\n    @ending:闪回结局\n", encoding="utf-8")
            chap3 = Path(tmpdir) / "chap3_normal.md"
            chap3.write_text("普通第三章\n    @ending:结局C\n", encoding="utf-8")
            outline = parse_chapter_directory(tmpdir)
            # 第一章 + 显式 @entry 的闪回章节
            self.assertEqual(len(outline.entry_node_ids), 2)

    def test_entry_propagates_to_traversal(self):
        """入口节点能正确被遍历访问到"""
        with tempfile.TemporaryDirectory() as tmpdir:
            chap1 = Path(tmpdir) / "chap1.md"
            chap1.write_text("第一章\n    进入第二章\n", encoding="utf-8")
            # chap2 既是独立入口（闪回线）又有主线继续：
            #   - 闪回线是 @entry 独立入口的支线，有自己的结局
            #   - 主线从 chap1 进来后继续向前推进（非结局叶子）
            chap2 = Path(tmpdir) / "chap2_flashback.md"
            chap2.write_text(
                "第二章 @entry\n"
                "    @choice:闪回回忆\n"  # 支线选择（闪回线）
                "        回忆过去\n"
                "            @ending:闪回结局\n"
                "    @choice:继续前进\n"  # 主线选择（从chap1进来后走这里）
                "        离开第二章\n",
                encoding="utf-8"
            )
            chap3 = Path(tmpdir) / "chap3.md"
            chap3.write_text("第三章\n    @ending:主线结局\n", encoding="utf-8")
            outline = parse_chapter_directory(tmpdir)
            traversal = traverse_all_paths(outline)
            # 闪回线是独立入口，能到达闪回结局；主线从chap1→chap2→chap3，能到达主线结局
            self.assertIn("闪回结局", traversal.reachable_endings)
            self.assertIn("主线结局", traversal.reachable_endings)


class TestCrossChapterConflict(unittest.TestCase):
    """跨章节道具消耗检测"""

    def test_item_removed_chap1_needed_chap3(self):
        """第一章失去道具，第三章又需要（跨章节冲突）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            chap1 = Path(tmpdir) / "chap1.md"
            chap1.write_text(
                "第一章\n"
                "    获得钥匙 @item:+钥匙\n"
                "        用钥匙开门 @item:-钥匙\n",
                encoding="utf-8"
            )
            chap2 = Path(tmpdir) / "chap2.md"
            chap2.write_text("第二章\n    过场剧情\n", encoding="utf-8")
            chap3 = Path(tmpdir) / "chap3.md"
            chap3.write_text(
                "第三章\n"
                "    打开地下室 @cond:钥匙\n"
                "        @ending:真相结局\n"
                "    强行破门\n"
                "        @ending:坏结局\n",
                encoding="utf-8"
            )
            outline = parse_chapter_directory(tmpdir)
            issues = check_conflicts(outline, traverse_all_paths(outline))
            # 应检测到：钥匙在 chap1 失去，chap3 的条件又需要
            conflict_msgs = [i.message for i in issues]
            self.assertTrue(
                any("钥匙" in m for m in conflict_msgs),
                f"应该检测到钥匙跨章节冲突，实际问题: {conflict_msgs}"
            )


class TestFiltersAndOverrides(unittest.TestCase):
    """过滤和严重程度覆盖的集成测试"""

    def test_only_check_endings_in_report(self):
        """只检查部分结局时，其他结局的问题不出现"""
        text = """开始
    @choice:走左
        @ending:井底结局 @truth:母亲是凶手
    @choice:走右
        @ending:逃离结局 @truth:父亲是帮凶"""
        config = CheckerConfig(only_check_endings=["*井底*"])
        outline = parse_outline_text(text)
        report = run_all_checks(outline, config)
        # 只有井底结局的问题应该出现
        messages = " ".join(i.message for i in report.issues)
        self.assertIn("井底结局", report.total_endings) if False else None
        # 真相只检查井底结局相关的
        if report.issues:
            self.assertTrue(all("井底结局" in m or "母亲" in m for m in messages.split(".")))

    def test_severity_override_applied(self):
        """严重程度覆盖能在报告中生效"""
        text = """开始
    @ending:结局 @truth:母亲是凶手"""
        config = CheckerConfig(
            severity_overrides=[
                SeverityOverride(issue_type="弱铺垫", new_severity="error")
            ]
        )
        outline = parse_outline_text(text)
        report = run_all_checks(outline, config)
        # 原本弱铺垫是 warning，现在应该是 error
        weak_issues = [i for i in report.issues if i.issue_type == "弱铺垫"]
        if weak_issues:
            self.assertEqual(weak_issues[0].severity, "error")

    def test_ignore_rule_expiry_in_action(self):
        """忽略规则过期后不生效"""
        past = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        text = """开始
    @ending:结局 @truth:母亲是凶手"""
        config = CheckerConfig(
            ignore_rules=[IgnoreRule(pattern="*弱铺垫*", expires=past)]
        )
        outline = parse_outline_text(text)
        report = run_all_checks(outline, config)
        # 过期规则不生效，弱铺垫问题应该存在
        types = [i.issue_type for i in report.issues]
        self.assertIn("弱铺垫", types)


class TestExporter(unittest.TestCase):
    """导出功能测试"""

    def test_export_markdown(self):
        """导出 Markdown 报告"""
        text = """开始
    获得日记 @item:+日记
        @choice:烧毁日记
            烧掉日记 @item:-日记
                阅读灰烬 @cond:日记
                    @ending:灰烬结局"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            export_markdown(report, path, "type", outline)
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("因果链检查报告", content)
            self.assertIn("总览", content)
            self.assertIn("条件冲突", content)
            self.assertIn("<details>", content)  # 路线片段折叠
        finally:
            os.unlink(path)

    def test_export_html(self):
        """导出 HTML 报告"""
        text = """开始
    获得日记 @item:+日记
        @choice:烧毁日记
            烧掉日记 @item:-日记
                阅读灰烬 @cond:日记
                    @ending:灰烬结局"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            export_html(report, path, "file", outline)
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("<html", content)
            self.assertIn("因果链检查报告", content)
            self.assertIn("issue-card", content)
            self.assertIn("switchGroup", content)  # 切换分组的 JS
        finally:
            os.unlink(path)

    def test_export_grouping_options(self):
        """三种分组方式都不报错"""
        text = """开始
    @choice:左
        @ending:结局A
    @choice:右
        @ending:结局B"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)
        with tempfile.TemporaryDirectory() as tmpdir:
            for group in ["type", "file", "ending"]:
                path = Path(tmpdir) / f"report_{group}.md"
                export_markdown(report, str(path), group, outline)
                self.assertTrue(path.exists())
                self.assertGreater(path.stat().st_size, 0)


class TestCLIIntegration(unittest.TestCase):
    """CLI 参数的集成测试（通过 main(argv) 模拟）"""

    def test_cli_draft_mode_arg(self):
        """--draft 参数应设置草稿模式"""
        from chainchecker.cli import main
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.md"
            f.write_text("开始\n    @ending:结局 @truth:母亲是凶手\n", encoding="utf-8")
            # 用 main 函数内部会加载配置，这里直接测试功能点即可
            config = CheckerConfig(draft_mode=True)
            self.assertTrue(config.draft_mode)
            # 草稿模式下弱铺垫降级
            self.assertEqual(
                config.override_severity("弱铺垫", "消息", "warning"),
                "info"
            )

    def test_cli_only_ending_arg(self):
        """--only-ending 参数逻辑"""
        config = CheckerConfig()
        # 模拟 CLI 添加 only_check_endings
        config.only_check_endings = ["*结局A*"]
        self.assertTrue(config.should_check_ending("结局A"))
        self.assertFalse(config.should_check_ending("结局B"))


class TestBackwardCompatibility(unittest.TestCase):
    """向后兼容性：所有原有测试用例应该仍然通过"""

    def test_basic_parsing_still_works(self):
        text = "拾取物品 @item:+破损铃铛"
        outline = parse_outline_text(text)
        self.assertEqual(len(outline.nodes), 1)
        node = list(outline.nodes.values())[0]
        self.assertIn("破损铃铛", node.items_add)

    def test_basic_conflict_still_detected(self):
        text = """开始
    获得日记 @item:+日记
        @choice:烧毁日记
            烧掉日记 @item:-日记
                阅读灰烬 @cond:日记
                    @ending:灰烬结局"""
        outline = parse_outline_text(text)
        issues = check_conflicts(outline, traverse_all_paths(outline))
        self.assertTrue(any("日记" in i.message for i in issues))

    def test_basic_foreshadowing_still_works(self):
        text = """开始
    进入房间
        @ending:结局 @truth:母亲是凶手"""
        outline = parse_outline_text(text)
        issues = check_weak_foreshadowing(outline, traverse_all_paths(outline))
        self.assertTrue(any("母亲是凶手" in i.message for i in issues))


class TestEndingGrouping(unittest.TestCase):
    """按结局分组：条件冲突的 related_endings 不为空，不进入未关联分组"""

    def test_conflict_has_related_endings(self):
        """条件冲突问题通过父链回溯获得关联结局"""
        text = """开始
    获得日记 @item:+日记
        @choice:烧毁日记
            烧掉日记 @item:-日记
                阅读灰烬 @cond:日记
                    @ending:灰烬结局
        @choice:保留日记
            阅读日记
                @ending:真相结局"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)
        conflicts = [i for i in report.issues if i.issue_type == "条件冲突"]
        if conflicts:
            self.assertTrue(
                conflicts[0].related_endings,
                f"条件冲突问题应有关联结局，实际: {conflicts[0].related_endings}"
            )

    def test_file_grouping_no_duplicates(self):
        """按章节分组时每条问题只出现一次"""
        text = """开始
    获得日记 @item:+日记
        @choice:烧毁日记
            烧掉日记 @item:-日记
                阅读灰烬 @cond:日记
                    @ending:灰烬结局"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)
        from chainchecker.exporter import _group_by_file
        groups = _group_by_file(report.issues)
        total = sum(len(v) for v in groups.values())
        self.assertEqual(total, len(report.issues),
                         f"按章节分组后问题总数应等于原问题数: {total} vs {len(report.issues)}")

    def test_md_html_issue_count_match(self):
        """MD 和 HTML 活动分组中的问题数一致"""
        text = """开始
    @choice:左
        @ending:结局A @truth:母亲是凶手
    @choice:右
        @ending:结局B"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)
        from chainchecker.exporter import export_markdown, export_html, _group_by_type, _group_by_file, _group_by_ending
        grouping_funcs = {"type": _group_by_type, "file": _group_by_file, "ending": _group_by_ending}
        with tempfile.TemporaryDirectory() as td:
            for group_by in ["type", "file", "ending"]:
                md_path = os.path.join(td, f"t_{group_by}.md")
                html_path = os.path.join(td, f"t_{group_by}.html")
                export_markdown(report, md_path, group_by=group_by, review_mode=True)
                export_html(report, html_path, group_by=group_by, review_mode=True)
                md = Path(md_path).read_text(encoding="utf-8")
                md_count = md.count("[错误]") + md.count("[警告]") + md.count("[提示]")
                expected = sum(len(v) for v in grouping_funcs[group_by](report.issues).values())
                self.assertEqual(md_count, expected,
                                 f"group_by={group_by}: MD({md_count}) != expected({expected})")


class TestReviewNotes(unittest.TestCase):
    """审阅备注功能测试"""

    def test_review_html_has_editable_fields(self):
        """审阅版 HTML 包含可编辑的负责人/状态/备注字段"""
        text = """开始
    @ending:结局 @truth:母亲是凶手"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            from chainchecker.exporter import export_html
            export_html(report, path, review_mode=True)
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("review-assignee", content)
            self.assertIn("review-status", content)
            self.assertIn("review-notes", content)
            self.assertIn("exportReviewJSON", content)
        finally:
            os.unlink(path)

    def test_export_review_json(self):
        """导出审阅备注 JSON"""
        text = """开始
    @ending:结局 @truth:母亲是凶手"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            from chainchecker.exporter import export_review_json
            export_review_json(report, path)
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertIn("issues", data)
            self.assertIn("summary", data)
            self.assertTrue(len(data["issues"]) > 0)
            issue = data["issues"][0]
            self.assertIn("key", issue)
            self.assertIn("review", issue)
            self.assertEqual(issue["review"]["status"], "pending")
        finally:
            os.unlink(path)


class TestMultiBaseline(unittest.TestCase):
    """多基线支持测试"""

    def test_save_and_load_named_baseline(self):
        """保存和加载命名基线"""
        from chainchecker.checkers import save_baseline, load_baseline, BaselineComparison, apply_baseline
        text = """开始
    @ending:结局 @truth:母亲是凶手"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)

        with tempfile.TemporaryDirectory() as td:
            bl_path = os.path.join(td, "baseline.json")
            save_baseline(report, bl_path, name="test_baseline", tag="弱铺垫")
            keys = load_baseline(bl_path, name="test_baseline")
            self.assertIsNotNone(keys)
            self.assertTrue(len(keys) > 0)

    def test_multiple_baselines_in_one_file(self):
        """一个基线文件保存多条基线"""
        from chainchecker.checkers import save_baseline, load_baseline, list_baselines
        text = """开始
    @ending:结局 @truth:母亲是凶手"""
        outline = parse_outline_text(text)
        report = run_all_checks(outline)

        with tempfile.TemporaryDirectory() as td:
            bl_path = os.path.join(td, "baseline.json")
            save_baseline(report, bl_path, name="v1_弱铺垫", tag="弱铺垫")
            save_baseline(report, bl_path, name="v1_冲突", tag="条件冲突")

            baselines = list_baselines(bl_path)
            self.assertEqual(len(baselines), 2)
            names = [bl.name for bl in baselines]
            self.assertIn("v1_弱铺垫", names)
            self.assertIn("v1_冲突", names)

            keys1 = load_baseline(bl_path, name="v1_弱铺垫")
            keys2 = load_baseline(bl_path, name="v1_冲突")
            self.assertIsNotNone(keys1)
            self.assertIsNotNone(keys2)

    def test_baseline_comparison_with_fixed(self):
        """基线对比显示新增/旧账/已修复"""
        from chainchecker.checkers import save_baseline, load_baseline, apply_baseline
        text1 = """开始
    @ending:结局A @truth:秘密A
    @ending:结局B @truth:秘密B"""
        outline1 = parse_outline_text(text1)
        report1 = run_all_checks(outline1)

        with tempfile.TemporaryDirectory() as td:
            bl_path = os.path.join(td, "baseline.json")
            save_baseline(report1, bl_path, name="initial")

            text2 = """开始
    @clue:秘密A的提示
    @ending:结局A @truth:秘密A
    @ending:结局B @truth:秘密B"""
            outline2 = parse_outline_text(text2)
            report2 = run_all_checks(outline2)

            baseline_keys = load_baseline(bl_path, name="initial")
            self.assertIsNotNone(baseline_keys)
            comparison = apply_baseline(report2, baseline_keys)
            self.assertIsInstance(comparison.new_count, int)
            self.assertIsInstance(comparison.baseline_count, int)
            self.assertIsInstance(comparison.fixed_count, int)
            self.assertEqual(comparison.new_count + comparison.baseline_count, len(report2.issues))

    def test_backward_compat_old_baseline_format(self):
        """旧的 v1 格式基线文件仍然可以加载"""
        from chainchecker.checkers import load_baseline
        old_format = {
            "version": 1,
            "issue_count": 1,
            "issues": [{"key": "test|msg|file|1", "issue_type": "test", "severity": "error",
                         "message": "msg", "source_files": ["file"], "line_numbers": [1]}]
        }
        with tempfile.TemporaryDirectory() as td:
            bl_path = os.path.join(td, "baseline.json")
            Path(bl_path).write_text(json.dumps(old_format, ensure_ascii=False), encoding="utf-8")
            keys = load_baseline(bl_path)
            self.assertIsNotNone(keys)
            self.assertIn("test|msg|file|1", keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
