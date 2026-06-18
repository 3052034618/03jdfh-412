"""三类问题检查器（增强版）：支持配置、路径片段、同义词匹配、更严格的误报过滤"""

from dataclasses import dataclass, field
from typing import List, Set, Dict, Tuple, Optional
from collections import defaultdict
from pathlib import Path

from .parser import ParsedOutline, Node
from .graph import TraversalResult, PathRecord, traverse_all_paths, ChoicePoint
from .config import CheckerConfig


@dataclass
class Issue:
    """单个问题记录"""
    issue_type: str  # unreachable_ending, conflict, weak_foreshadowing
    severity: str  # error, warning, info
    message: str
    line_numbers: List[int] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)
    details: str = ""
    suggestion: str = ""

    # 新增强字段
    path_segment: str = ""  # 从最后一个选择点到问题位置的路线片段
    choice_chain: str = ""  # 完整选择链
    related_paths: List[PathRecord] = field(default_factory=list)  # 相关路径（用于JSON输出）
    related_endings: List[str] = field(default_factory=list)  # 关联的结局列表（审阅版用）
    node_ids: List[str] = field(default_factory=list)  # 问题涉及的节点ID（用于结局关联）
    is_baseline: bool = False  # 是否是基线中已有的旧问题

    def format(
        self,
        file_path: Optional[str] = None,
        show_path_segment: bool = True,
        show_choice_chain: bool = True
    ) -> str:
        prefix = f"[{self.severity.upper()}]"

        # 定位信息：优先用问题自己的 source_files
        location = ""
        if self.source_files and self.line_numbers:
            files_display = self.source_files[0] if len(self.source_files) == 1 else "(多文件)"
            lines = ",".join(str(l) for l in self.line_numbers)
            location = f" {files_display}:{lines}"
        elif file_path and self.line_numbers:
            lines = ",".join(str(l) for l in self.line_numbers)
            location = f" {file_path}:{lines}"
        elif self.line_numbers:
            lines = ",".join(str(l) for l in self.line_numbers)
            location = f" 行 {lines}"

        output = f"{prefix}{location} {self.issue_type}: {self.message}"
        if self.details:
            output += f"\n  详情: {self.details}"

        if show_choice_chain and self.choice_chain:
            output += f"\n  选择链:\n{self.choice_chain}"

        if show_path_segment and self.path_segment:
            output += f"\n  路线片段:\n{self.path_segment}"

        if self.suggestion:
            output += f"\n  建议: {self.suggestion}"

        return output


@dataclass
class FileReport:
    """单个文件的报告"""
    file_path: str
    issues: List[Issue] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


@dataclass
class CheckReport:
    """完整的检查报告"""
    issues: List[Issue] = field(default_factory=list)
    file_path: Optional[str] = None
    total_endings: int = 0
    reachable_endings: int = 0
    total_paths: int = 0

    # 多文件支持
    is_multi_file: bool = False
    file_reports: Dict[str, FileReport] = field(default_factory=dict)
    ending_file_map: Dict[str, List[str]] = field(default_factory=dict)  # 结局 -> 涉及文件

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def infos(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "info"]

    @property
    def new_issues(self) -> List[Issue]:
        return [i for i in self.issues if not i.is_baseline]

    @property
    def baseline_issues(self) -> List[Issue]:
        return [i for i in self.issues if i.is_baseline]

    @property
    def new_errors(self) -> List[Issue]:
        return [i for i in self.new_issues if i.severity == "error"]

    @property
    def baseline_errors(self) -> List[Issue]:
        return [i for i in self.baseline_issues if i.severity == "error"]

    def get_issues_by_file(self, file_path: str) -> List[Issue]:
        """获取某个文件的所有问题"""
        return [i for i in self.issues if file_path in i.source_files]

    def format(self, show_details: bool = True) -> str:
        lines = []
        width = 70
        lines.append("=" * width)
        lines.append("  因果链检查报告")
        lines.append("=" * width)

        if self.is_multi_file:
            lines.append(f"目录: {self.file_path}")
        else:
            lines.append(f"文件: {self.file_path}")

        lines.append(f"结局总数: {self.total_endings} (可达: {self.reachable_endings} / 不可达: {self.total_endings - self.reachable_endings})")
        lines.append(f"有效路径数: {self.total_paths}")
        lines.append("")

        # 多文件时先显示总览
        if self.is_multi_file and self.ending_file_map:
            lines.append("── 结局跨章节总览 ──")
            for ending in sorted(self.ending_file_map.keys()):
                files = [Path(f).name for f in self.ending_file_map[ending]]
                lines.append(f"  「{ending}」 → 跨越 {len(files)} 章节: {' → '.join(files)}")
            lines.append("")

            lines.append("── 各文件问题汇总 ──")
            for fp in sorted(self.file_reports.keys()):
                rep = self.file_reports[fp]
                fname = Path(fp).name
                total = len(rep.issues)
                lines.append(f"  {fname}: {total} 个问题 ({rep.errors} 错误, {rep.warnings} 警告)")
            lines.append("")

        if not self.issues:
            lines.append("✅ 未发现问题，大纲逻辑完整！")
            return "\n".join(lines)

        lines.append(f"共发现 {len(self.issues)} 个问题 ({len(self.errors)} 错误, {len(self.warnings)} 警告):")
        lines.append("")

        for idx, issue in enumerate(self.issues, 1):
            lines.append(f"{idx}. {issue.format(self.file_path if not self.is_multi_file else None, show_details, show_details)}")
            lines.append("")

        lines.append("-" * width)
        lines.append(f"错误: {len(self.errors)}  警告: {len(self.warnings)}  提示: {len(self.infos)}")
        return "\n".join(lines)


# ============= 辅助函数 =============


def _extract_keywords(text: str) -> List[str]:
    """
    从文本中提取关键词用于匹配：
    - 英文：提取连续2个以上字母的单词
    - 中文：滑动窗口提取所有2字组合
    """
    import re
    keywords: Set[str] = set()

    for m in re.finditer(r'[a-zA-Z]{2,}', text):
        keywords.add(m.group(0))

    i = 0
    while i < len(text):
        if '\u4e00' <= text[i] <= '\u9fff':
            j = i
            while j < len(text) and '\u4e00' <= text[j] <= '\u9fff':
                j += 1
            chinese_segment = text[i:j]
            if len(chinese_segment) >= 2:
                for k in range(len(chinese_segment) - 1):
                    keywords.add(chinese_segment[k:k+2])
            i = j
        else:
            i += 1

    return list(keywords)


def _clue_matches_truth(clue: str, truth: str, config: Optional[CheckerConfig]) -> bool:
    """判断线索是否与真相相关，考虑配置的关键词和同义词"""
    clue_lower = clue.lower()
    truth_lower = truth.lower()

    # 先检查配置的自定义关键词
    if config and config.truth_keywords:
        for kw in config.truth_keywords:
            kw_lower = kw.lower()
            if kw_lower in clue_lower and kw_lower in truth_lower:
                return True

    # 再检查自动提取的关键词
    truth_kws = _extract_keywords(truth_lower)
    threshold = config.clue_match_threshold if config else 1
    matches = sum(1 for kw in truth_kws if len(kw) >= 2 and kw in clue_lower)
    return matches >= threshold


import fnmatch

def _apply_filters_and_overrides(issues: List[Issue], config: Optional[CheckerConfig]) -> List[Issue]:
    """对问题列表应用过滤（结局/文件）和严重程度覆盖"""
    result: List[Issue] = []
    for issue in issues:
        # 1. 结局路径过滤（通过问题消息中的结局名判断）
        if config and config.only_check_endings:
            if issue.issue_type != "条件冲突":
                matched = False
                for pattern in config.only_check_endings:
                    if fnmatch.fnmatch(issue.message, f"*{pattern}*"):
                        matched = True
                        break
                if not matched:
                    continue

        # 2. 文件过滤
        if config and config.only_check_files and issue.source_files:
            if not any(config.should_check_file(sf) for sf in issue.source_files):
                continue

        # 3. 严重程度覆盖
        if config:
            issue.severity = config.override_severity(
                issue.issue_type, issue.message, issue.severity
            )

        result.append(issue)
    return result


def _should_ignore(issue: Issue, config: Optional[CheckerConfig]) -> bool:
    """根据配置判断是否应该忽略此问题"""
    if config is None:
        return False
    return config.should_ignore_issue(issue.message, issue.issue_type)


# ============= 检查器实现 =============


def check_unreachable_endings(
    outline: ParsedOutline,
    traversal: TraversalResult,
    config: Optional[CheckerConfig] = None
) -> List[Issue]:
    """检查不可到达的结局"""
    issues: List[Issue] = []

    all_ending_nodes = outline.all_ending_nodes()
    all_ending_names = set()
    ending_nodes_map: Dict[str, List[Node]] = defaultdict(list)

    for node in all_ending_nodes:
        for ending_name in node.endings:
            if config and config.should_ignore_ending(ending_name):
                continue
            all_ending_names.add(ending_name)
            ending_nodes_map[ending_name].append(node)

    for ending_name in sorted(all_ending_names):
        if not traversal.ending_is_reachable(ending_name):
            nodes = ending_nodes_map[ending_name]
            lines = [n.line_number for n in nodes]
            files = list(set(n.source_file for n in nodes))

            # 尝试构造路线片段：找一条到达结局前一个节点的路径
            sample_path = _find_sample_path_to_node(outline, nodes[0])

            details_parts = []
            for n in nodes:
                fname = Path(n.source_file).name
                details_parts.append(f"{fname}:{n.line_number} → {n.text[:60]}")
            details = "; ".join(details_parts)

            issue = Issue(
                issue_type="不可达结局",
                severity="error",
                message=f"结局「{ending_name}」没有任何有效路径可以到达",
                line_numbers=lines,
                source_files=files,
                details=details,
                suggestion="检查进入该结局的条件是否能被满足，或者是否有选择分支能够通向该结局"
            )
            issue.node_ids = [n.id for n in nodes]
            issue.related_endings = [ending_name]

            if sample_path:
                issue.path_segment = _format_node_path(outline, sample_path)
                issue.choice_chain = _format_node_choices(outline, sample_path)

            if not _should_ignore(issue, config):
                issues.append(issue)

    return issues


def _find_sample_path_to_node(outline: ParsedOutline, target: Node) -> List[str]:
    """从入口节点到目标节点的一条示例路径（用于不可达结局显示参考路径）"""
    from collections import deque

    # 确定起点
    start_ids: List[str] = []
    if outline.is_multi_file and outline.entry_node_ids:
        start_ids = list(outline.entry_node_ids)
    else:
        for root_id in outline.root_ids:
            if outline.is_multi_file:
                root_node = outline.get_node(root_id)
                if root_node and root_node.parent is not None:
                    continue
            start_ids.append(root_id)

    for start_id in start_ids:
        queue: deque = deque()
        queue.append([start_id])
        visited: Set[str] = set()

        while queue:
            path = queue.popleft()
            last_nid = path[-1]
            if last_nid == target.id:
                return path
            if last_nid in visited:
                continue
            visited.add(last_nid)

            node = outline.get_node(last_nid)
            if node:
                for child_id in node.children:
                    queue.append(path + [child_id])

    return []


def _format_node_path(outline: ParsedOutline, node_ids: List[str]) -> str:
    """格式化节点路径为显示字符串"""
    parts = []
    for nid in node_ids:
        node = outline.get_node(nid)
        if node:
            fname = Path(node.source_file).name
            parts.append(f"  ↳ [{fname}:{node.line_number}] {node.get_display_text()}")
    return "\n".join(parts)


def _format_node_choices(outline: ParsedOutline, node_ids: List[str]) -> str:
    """格式化路径中的选择点"""
    parts = []
    last_choice_label = None
    for nid in node_ids:
        node = outline.get_node(nid)
        if node and node.is_choice and node.choice_label:
            last_choice_label = node.choice_label
            fname = Path(node.source_file).name
            parts.append(f"  [{fname}:{node.line_number}] 选择「{last_choice_label}」")
    if not parts:
        return "  （无选择点，直线路径）"
    return "\n".join(parts)


def _static_traverse_for_conflicts(
    outline: ParsedOutline,
    node_id: str,
    items_state: Set[str],
    removed_items: Dict[str, Tuple[int, str, int]],  # item -> (line, file, visit_order)
    flags_state: Set[str],
    cleared_flags: Dict[str, Tuple[int, str, int]],
    item_action_history: List[Tuple[str, str, int, str]],
    flag_action_history: List[Tuple[str, str, int, str]],
    current_node_ids: List[str],
    seen_conflicts: Set[Tuple[str, str, str, str]],
    issues: List[Issue],
    config: Optional[CheckerConfig],
    visit_order: int = 0,
) -> None:
    """
    静态DFS遍历所有分支（不做条件过滤），专门用于检测条件冲突。
    收紧规则：只有"失去后被后续条件依赖"才报 ERROR；正常 add->remove 一次性消耗不报。

    visit_order 是全局递增的访问序号，用于跨章节判断"先失去后需要"的先后顺序
    （因为每个文件的 line_number 是独立的，不能直接比较）
    """
    node = outline.get_node(node_id)
    if node is None:
        return

    visit_order += 1
    new_node_ids = current_node_ids + [node_id]

    # 1. 检查当前节点的条件是否与状态冲突（失去物品后又需要）
    for cond in node.conditions:
        item_name = None
        if cond.startswith('item:'):
            item_name = cond[5:]
        elif not cond.startswith('flag:') and not cond.startswith('!'):
            item_name = cond

        if item_name:
            resolved = config.resolve_item_name(item_name) if config else item_name
            # 检查当前状态中是否有这个物品（考虑同义词）
            has_item = False
            for it in items_state:
                it_resolved = config.resolve_item_name(it) if config else it
                if it_resolved == resolved:
                    has_item = True
                    break

            if not has_item:
                # 检查是否曾经被移除过（用 visit_order 判断先后，跨文件也安全）
                for rm_item, (rm_line, rm_file, rm_order) in removed_items.items():
                    rm_resolved = config.resolve_item_name(rm_item) if config else rm_item
                    if rm_resolved == resolved and rm_order < visit_order:
                        key = ("item_lost_cond", resolved, rm_file + ":" + str(rm_line), node.source_file + ":" + str(node.line_number))
                        if key not in seen_conflicts:
                            seen_conflicts.add(key)

                            # 构造路径片段和选择链
                            path_seg = _format_node_path(outline, new_node_ids[-8:])
                            choice_chain = _format_node_choices(outline, new_node_ids)

                            issue = Issue(
                                issue_type="条件冲突",
                                severity="error",
                                message=f"物品「{item_name}」在{Path(rm_file).name}:{rm_line}被失去/烧毁/消耗，但在{Path(node.source_file).name}:{node.line_number}的条件中仍然需要它",
                                line_numbers=[rm_line, node.line_number],
                                source_files=[rm_file, node.source_file],
                                details=f"路径中失去物品后，后续节点要求该物品存在，逻辑矛盾（跨章节检测）",
                                path_segment=path_seg,
                                choice_chain=choice_chain,
                                suggestion=f"在{Path(rm_file).name}:{rm_line}后移除对「{item_name}」的条件要求，或在那里不要失去该物品"
                            )
                            issue.node_ids = [node_id]
                            if not _should_ignore(issue, config):
                                issues.append(issue)
                        break

    # 2. 应用当前节点的状态变化
    new_items = set(items_state)
    new_removed = dict(removed_items)
    new_item_hist = list(item_action_history)

    for item in node.items_add:
        resolved = config.resolve_item_name(item) if config else item
        # 添加时移除对应的 removed 记录
        keys_to_remove = [k for k in new_removed if (config.resolve_item_name(k) if config else k) == resolved]
        for k in keys_to_remove:
            del new_removed[k]
        new_items.add(item)
        new_item_hist.append(("add", item, node.line_number, node.source_file))

    for item in node.items_remove:
        resolved = config.resolve_item_name(item) if config else item
        # 移除对应的 items
        items_to_remove = [it for it in new_items if (config.resolve_item_name(it) if config else it) == resolved]
        for it in items_to_remove:
            new_items.discard(it)
        new_removed[item] = (node.line_number, node.source_file, visit_order)  # 记录访问序号
        new_item_hist.append(("remove", item, node.line_number, node.source_file))

    new_flags = set(flags_state)
    new_cleared = dict(cleared_flags)
    new_flag_hist = list(flag_action_history)

    for flag in node.flags_set:
        keys_to_remove = [k for k in new_cleared if k == flag]
        for k in keys_to_remove:
            del new_cleared[k]
        new_flags.add(flag)
        new_flag_hist.append(("set", flag, node.line_number, node.source_file))

    for flag in node.flags_clear:
        new_flags.discard(flag)
        new_cleared[flag] = (node.line_number, node.source_file, visit_order)
        new_flag_hist.append(("clear", flag, node.line_number, node.source_file))

    # 3. 递归子节点
    for child_id in node.children:
        _static_traverse_for_conflicts(
            outline, child_id,
            new_items, new_removed,
            new_flags, new_cleared,
            new_item_hist, new_flag_hist,
            new_node_ids,
            seen_conflicts, issues, config,
            visit_order  # 父节点的 visit_order 作为子节点的基数
        )


def check_conflicts(
    outline: ParsedOutline,
    traversal: TraversalResult,
    config: Optional[CheckerConfig] = None
) -> List[Issue]:
    """
    检查条件冲突（收紧版）：
    - 只报 ERROR：物品被"消耗"（失去）后，后续路径的条件又需要它
    - 正常的 add->remove 一次性消耗不报（除非配置为非忽略项且后续有依赖）
    - 物品/标记的 set->clear 序列也只在后续有依赖时报
    - 多文件模式下从正确的入口开始静态遍历
    """
    issues: List[Issue] = []
    seen_conflicts: Set[Tuple[str, str, str, str]] = set()

    # ===== 确定起点：优先用 entry_node_ids =====
    start_ids: List[str] = []
    if outline.is_multi_file and outline.entry_node_ids:
        start_ids = list(outline.entry_node_ids)
    else:
        for root_id in outline.root_ids:
            if outline.is_multi_file:
                root_node = outline.get_node(root_id)
                if root_node and root_node.parent is not None:
                    continue
            start_ids.append(root_id)

    for start_id in start_ids:
        _static_traverse_for_conflicts(
            outline, start_id,
            set(), {},
            set(), {},
            [], [],
            [],
            seen_conflicts, issues, config,
            visit_order=0
        )

    return issues


def check_weak_foreshadowing(
    outline: ParsedOutline,
    traversal: TraversalResult,
    config: Optional[CheckerConfig] = None
) -> List[Issue]:
    """
    检查弱铺垫（收紧版）：
    - 只使用结局节点之前收集的线索（clues_found_before_ending）
    - 结局现场的线索（clues_at_ending）不算作铺垫
    - 支持同义词和配置关键词匹配
    """
    issues: List[Issue] = []
    seen_weak: Set[str] = set()

    # 检查每条到达结局的路径
    for ending_name, paths in traversal.reachable_ending_nodes.items():
        if config and config.should_ignore_ending(ending_name):
            continue

        for path in paths:
            # 找出这条路径最后揭示的真相（在结局节点上的）
            ending_truths: Set[Tuple[str, int, str]] = set()
            for node_id in reversed(path.node_ids):
                node = outline.get_node(node_id)
                if node is None:
                    continue
                if node.is_ending:
                    for truth in node.truths:
                        ending_truths.add((truth, node.line_number, node.source_file))
                    break

            # 只使用结局前收集的线索
            path_clues = path.clues_found_before_ending
            path_clues_text = " ".join(path_clues).lower()

            for truth_text, truth_line, truth_file in ending_truths:
                truth_lower = truth_text.lower()

                has_foreshadowing = False
                matching_clues = []

                # 检查路径中的每条线索是否与真相相关
                for clue in path_clues:
                    clue_lower = clue.lower()
                    if _clue_matches_truth(clue_lower, truth_lower, config):
                        matching_clues.append(clue)
                        has_foreshadowing = True

                # 检查其他路径中是否有相关线索（用于提示）
                other_path_clues = []
                if not has_foreshadowing:
                    all_clues = outline.all_clues()
                    for clue in all_clues:
                        if clue not in path_clues and _clue_matches_truth(clue.lower(), truth_lower, config):
                            other_path_clues.append(clue)
                            if len(other_path_clues) >= 3:
                                break

                if not has_foreshadowing and truth_text not in seen_weak:
                    seen_weak.add(truth_text)

                    detail_parts = []
                    if other_path_clues:
                        clue_names = ", ".join(f"「{c}」" for c in other_path_clues[:3])
                        detail_parts.append(f"其他路径中有相关线索: {clue_names}（但不在当前结局路径中）")
                    else:
                        detail_parts.append("全文未发现相关铺垫线索")

                    path_seg = path.format_path_segment(outline)
                    choice_chain = path.format_choice_chain()

                    issue = Issue(
                        issue_type="弱铺垫",
                        severity="warning",
                        message=f"真相「{truth_text}」在结局「{ending_name}」中揭示，但缺少前置铺垫",
                        line_numbers=[truth_line],
                        source_files=[truth_file],
                        details="; ".join(detail_parts),
                        path_segment=path_seg,
                        choice_chain=choice_chain,
                        suggestion=f"在到达该结局的路径中，提前添加 @clue 标记来暗示「{truth_text}」相关的信息"
                    )
                    issue.related_endings = [ending_name]

                    if not _should_ignore(issue, config):
                        issues.append(issue)

    return issues


def _build_file_reports(report: CheckReport, outline: ParsedOutline) -> None:
    """按文件汇总问题"""
    for fp in outline.file_order if outline.is_multi_file else [report.file_path]:
        if fp is None:
            continue
        file_issues = []
        for issue in report.issues:
            if fp in issue.source_files or (not issue.source_files and fp == report.file_path):
                file_issues.append(issue)
        if file_issues or outline.is_multi_file:
            report.file_reports[fp] = FileReport(file_path=fp, issues=file_issues)


def _fill_related_endings(report: CheckReport, traversal: TraversalResult) -> None:
    """
    根据遍历结果填充每个问题的 related_endings。
    - 已有 related_endings 的（如不可达结局、弱铺垫）跳过
    - 有 node_ids 的，通过遍历所有经过这些节点的路径来收集结局
    """
    for issue in report.issues:
        if issue.related_endings:
            continue
        if not issue.node_ids:
            continue

        node_set = set(issue.node_ids)
        endings: Set[str] = set()
        for path in traversal.all_paths:
            path_nodes = set(path.node_ids)
            if node_set & path_nodes:
                endings.update(path.reached_endings)

        issue.related_endings = sorted(endings)


def run_all_checks(
    outline: ParsedOutline,
    config: Optional[CheckerConfig] = None
) -> CheckReport:
    """运行所有检查并生成报告"""
    if config is None:
        config = CheckerConfig.load()

    traversal = traverse_all_paths(outline, config)

    all_ending_nodes = outline.all_ending_nodes()
    all_ending_names = set()
    for node in all_ending_nodes:
        for ending_name in node.endings:
            if not config.should_ignore_ending(ending_name) and config.should_check_ending(ending_name):
                all_ending_names.add(ending_name)

    report = CheckReport(
        file_path=outline.file_path,
        total_endings=len(all_ending_names),
        reachable_endings=sum(1 for e in traversal.reachable_endings
                              if config.should_check_ending(e) and not config.should_ignore_ending(e)),
        total_paths=len(traversal.all_paths),
        is_multi_file=outline.is_multi_file
    )

    # 填充结局跨文件映射
    for ending_name in traversal.ending_file_map:
        if config.should_check_ending(ending_name) and not config.should_ignore_ending(ending_name):
            report.ending_file_map[ending_name] = list(traversal.ending_file_map[ending_name])

    issues: List[Issue] = []
    issues.extend(check_unreachable_endings(outline, traversal, config))
    issues.extend(check_conflicts(outline, traversal, config))
    issues.extend(check_weak_foreshadowing(outline, traversal, config))

    # 应用过滤和严重程度覆盖
    issues = _apply_filters_and_overrides(issues, config)

    # 按严重程度排序，同类型按行号
    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: (
        severity_order.get(i.severity, 99),
        i.issue_type,
        i.line_numbers[0] if i.line_numbers else 0
    ))

    report.issues = issues

    # 填充关联结局
    _fill_related_endings(report, traversal)

    # 按文件汇总
    _build_file_reports(report, outline)

    return report


# ============= 基线功能 =============

BASELINE_FILENAME = ".chaincheck.baseline.json"


def issue_unique_key(issue: Issue) -> str:
    """生成问题的唯一标识键（用于基线对比）"""
    lines_key = ",".join(str(l) for l in issue.line_numbers)
    files_key = ",".join(Path(f).name for f in issue.source_files) if issue.source_files else ""
    # 用类型+消息前80字+文件+行号作为唯一键
    return f"{issue.issue_type}|{issue.message[:80]}|{files_key}|{lines_key}"


def save_baseline(report: CheckReport, output_path: str = BASELINE_FILENAME) -> None:
    """将当前报告的问题保存为基线文件"""
    import json
    baseline = {
        "version": 1,
        "issue_count": len(report.issues),
        "issues": [
            {
                "key": issue_unique_key(issue),
                "issue_type": issue.issue_type,
                "severity": issue.severity,
                "message": issue.message,
                "source_files": issue.source_files,
                "line_numbers": issue.line_numbers,
                "related_endings": issue.related_endings,
            }
            for issue in report.issues
        ]
    }
    Path(output_path).write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def load_baseline(baseline_path: str = BASELINE_FILENAME) -> Optional[Set[str]]:
    """加载基线文件，返回问题键的集合。文件不存在返回 None。"""
    import json
    path = Path(baseline_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {item["key"] for item in data.get("issues", [])}
    except (json.JSONDecodeError, KeyError):
        return None


def apply_baseline(report: CheckReport, baseline_keys: Set[str]) -> Tuple[int, int]:
    """
    将基线应用到报告上，标记 is_baseline。
    返回 (新增问题数, 基线问题数)
    """
    new_count = 0
    baseline_count = 0
    for issue in report.issues:
        key = issue_unique_key(issue)
        if key in baseline_keys:
            issue.is_baseline = True
            baseline_count += 1
        else:
            issue.is_baseline = False
            new_count += 1
    return new_count, baseline_count
