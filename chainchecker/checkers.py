"""三类问题检查器：不可达结局、条件冲突、弱铺垫"""

from dataclasses import dataclass, field
from typing import List, Set, Dict, Tuple, Optional
from collections import defaultdict

from .parser import ParsedOutline, Node
from .graph import TraversalResult, PathRecord, traverse_all_paths


@dataclass
class Issue:
    """单个问题记录"""
    issue_type: str  # unreachable_ending, conflict, weak_foreshadowing
    severity: str  # error, warning, info
    message: str
    line_numbers: List[int] = field(default_factory=list)
    details: str = ""
    suggestion: str = ""

    def format(self, file_path: Optional[str] = None) -> str:
        prefix = f"[{self.severity.upper()}]"
        location = ""
        if file_path and self.line_numbers:
            lines = ",".join(str(l) for l in self.line_numbers)
            location = f" {file_path}:{lines}"
        elif self.line_numbers:
            lines = ",".join(str(l) for l in self.line_numbers)
            location = f" 行 {lines}"

        output = f"{prefix}{location} {self.issue_type}: {self.message}"
        if self.details:
            output += f"\n  详情: {self.details}"
        if self.suggestion:
            output += f"\n  建议: {self.suggestion}"
        return output


@dataclass
class CheckReport:
    """完整的检查报告"""
    issues: List[Issue] = field(default_factory=list)
    file_path: Optional[str] = None
    total_endings: int = 0
    reachable_endings: int = 0
    total_paths: int = 0

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def infos(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "info"]

    def format(self) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("  因果链检查报告")
        lines.append("=" * 60)

        if self.file_path:
            lines.append(f"文件: {self.file_path}")
        lines.append(f"结局总数: {self.total_endings} (可达: {self.reachable_endings})")
        lines.append(f"有效路径数: {self.total_paths}")
        lines.append("")

        if not self.issues:
            lines.append("✅ 未发现问题，大纲逻辑完整！")
            return "\n".join(lines)

        lines.append(f"共发现 {len(self.issues)} 个问题:")
        lines.append("")

        for idx, issue in enumerate(self.issues, 1):
            lines.append(f"{idx}. {issue.format(self.file_path)}")
            lines.append("")

        lines.append("-" * 60)
        lines.append(f"错误: {len(self.errors)}  警告: {len(self.warnings)}  提示: {len(self.infos)}")
        return "\n".join(lines)


# ============= 检查器实现 =============


def check_unreachable_endings(
    outline: ParsedOutline,
    traversal: TraversalResult
) -> List[Issue]:
    """检查不可到达的结局"""
    issues = []

    all_ending_nodes = outline.all_ending_nodes()
    all_ending_names = set()
    ending_nodes_map: Dict[str, List[Node]] = defaultdict(list)

    for node in all_ending_nodes:
        for ending_name in node.endings:
            all_ending_names.add(ending_name)
            ending_nodes_map[ending_name].append(node)

    for ending_name in sorted(all_ending_names):
        if not traversal.ending_is_reachable(ending_name):
            nodes = ending_nodes_map[ending_name]
            lines = [n.line_number for n in nodes]
            details_parts = []
            for n in nodes:
                details_parts.append(f"行{n.line_number}: {n.text}")
            details = "; ".join(details_parts)

            issues.append(Issue(
                issue_type="不可达结局",
                severity="error",
                message=f"结局「{ending_name}」没有任何有效路径可以到达",
                line_numbers=lines,
                details=details,
                suggestion="检查进入该结局的条件是否能被满足，或者是否有选择分支能够通向该结局"
            ))

    return issues


def _static_traverse_for_conflicts(
    outline: ParsedOutline,
    node_id: str,
    items_state: Set[str],
    removed_items: Dict[str, int],  # item -> 被移除的行号
    flags_state: Set[str],
    cleared_flags: Dict[str, int],
    item_action_history: List[Tuple[str, str, int]],
    flag_action_history: List[Tuple[str, str, int]],
    seen_conflicts: Set[Tuple[str, str, int, int]],
    issues: List[Issue],
) -> None:
    """
    静态DFS遍历所有分支（不做条件过滤），专门用于检测条件冲突。
    这样即使路径因条件不满足被动态遍历跳过，也能检测到逻辑矛盾。
    """
    node = outline.get_node(node_id)
    if node is None:
        return

    # 1. 先检查当前节点的条件是否与状态冲突
    for cond in node.conditions:
        item_name = None
        if cond.startswith('item:'):
            item_name = cond[5:]
        elif not cond.startswith('flag:') and not cond.startswith('!'):
            item_name = cond

        if item_name and item_name not in items_state and item_name in removed_items:
            removed_line = removed_items[item_name]
            if removed_line < node.line_number:
                key = ("item_lost_cond", item_name, removed_line, node.line_number)
                if key not in seen_conflicts:
                    seen_conflicts.add(key)
                    issues.append(Issue(
                        issue_type="条件冲突",
                        severity="error",
                        message=f"物品「{item_name}」在行{removed_line}被失去/烧毁/消耗，但在行{node.line_number}的条件中仍然需要它",
                        line_numbers=[removed_line, node.line_number],
                        details=f"路径中失去物品后，后续节点要求该物品存在，逻辑矛盾",
                        suggestion=f"在行{removed_line}后移除对「{item_name}」的条件要求，或在行{removed_line}处不要失去该物品"
                    ))

    # 2. 记录 add->remove 警告
    for action, item, line in item_action_history:
        pass  # 在下面统一检查

    # 检查 add -> remove 序列
    last_item_action: Dict[str, Tuple[str, int]] = {}
    for action, item, line in item_action_history:
        if item in last_item_action:
            prev_action, prev_line = last_item_action[item]
            if prev_action != action:
                key = ("item", item, min(prev_line, line), max(prev_line, line))
                if key not in seen_conflicts:
                    seen_conflicts.add(key)
                    if prev_action == "add" and action == "remove":
                        issues.append(Issue(
                            issue_type="条件冲突",
                            severity="warning",
                            message=f"物品「{item}」在行{prev_line}获得后又在行{line}失去",
                            line_numbers=[prev_line, line],
                            details=f"需确认后续剧情是否还有依赖「{item}」的分支",
                            suggestion="如果失去后不再使用，可以忽略；否则需要补充剧情逻辑或条件检查"
                        ))
                    elif prev_action == "remove" and action == "add":
                        issues.append(Issue(
                            issue_type="条件冲突",
                            severity="info",
                            message=f"物品「{item}」在行{prev_line}失去后又在行{line}重新获得",
                            line_numbers=[prev_line, line],
                            details="请确认这是设计意图",
                            suggestion="如为设计意图可忽略，否则检查物品获取逻辑"
                        ))
        last_item_action[item] = (action, line)

    # 检查 set -> clear 序列
    last_flag_action: Dict[str, Tuple[str, int]] = {}
    for action, flag, line in flag_action_history:
        if flag in last_flag_action:
            prev_action, prev_line = last_flag_action[flag]
            if prev_action != action:
                key = ("flag", flag, min(prev_line, line), max(prev_line, line))
                if key not in seen_conflicts:
                    seen_conflicts.add(key)
                    if prev_action == "set" and action == "clear":
                        issues.append(Issue(
                            issue_type="条件冲突",
                            severity="warning",
                            message=f"标记「{flag}」在行{prev_line}设置后又在行{line}清除",
                            line_numbers=[prev_line, line],
                            details=f"需确认后续剧情是否还有依赖标记「{flag}」的分支",
                            suggestion="如果清除后不再使用，可以忽略；否则需要补充剧情逻辑"
                        ))
        last_flag_action[flag] = (action, line)

    # 3. 应用当前节点的状态变化，生成新状态
    new_items = set(items_state)
    new_removed = dict(removed_items)
    new_item_hist = list(item_action_history)

    for item in node.items_add:
        new_items.add(item)
        new_removed.pop(item, None)
        new_item_hist.append(("add", item, node.line_number))
    for item in node.items_remove:
        new_items.discard(item)
        new_removed[item] = node.line_number
        new_item_hist.append(("remove", item, node.line_number))

    new_flags = set(flags_state)
    new_cleared = dict(cleared_flags)
    new_flag_hist = list(flag_action_history)

    for flag in node.flags_set:
        new_flags.add(flag)
        new_cleared.pop(flag, None)
        new_flag_hist.append(("set", flag, node.line_number))
    for flag in node.flags_clear:
        new_flags.discard(flag)
        new_cleared[flag] = node.line_number
        new_flag_hist.append(("clear", flag, node.line_number))

    # 4. 递归子节点
    for child_id in node.children:
        _static_traverse_for_conflicts(
            outline, child_id,
            new_items, new_removed,
            new_flags, new_cleared,
            new_item_hist, new_flag_hist,
            seen_conflicts, issues
        )


def check_conflicts(
    outline: ParsedOutline,
    traversal: TraversalResult
) -> List[Issue]:
    """
    检查条件冲突：
    - 同一条路径中既获得又失去同一物品
    - 同一条路径中既设置又清除同一标记
    - 物品被"消耗"（失去）后，后续路径又使用它（例如烧毁日记后又阅读日记）
    """
    issues: List[Issue] = []
    seen_conflicts: Set[Tuple[str, str, int, int]] = set()

    for root_id in outline.root_ids:
        _static_traverse_for_conflicts(
            outline, root_id,
            set(), {},
            set(), {},
            [], [],
            seen_conflicts, issues
        )

    return issues


def check_weak_foreshadowing(
    outline: ParsedOutline,
    traversal: TraversalResult
) -> List[Issue]:
    """
    检查弱铺垫：关键真相只在结局出现，前面没有任何线索支撑。
    策略：
    1. 收集所有 @truth 标记（关键真相）
    2. 收集所有 @clue 标记（铺垫线索）
    3. 对每条到达结局的路径，如果该结局包含真相，检查路径中是否有相关线索
    4. 如果真相没有相关线索，则报告弱铺垫

    "相关性"通过关键词匹配判断：真相文本中的关键词出现在线索中。
    """
    issues = []
    seen_weak: Set[str] = set()

    # 收集所有线索文本
    all_clues = list(outline.all_clues())

    # 检查每条到达结局的路径
    for ending_name, paths in traversal.reachable_ending_nodes.items():
        for path in paths:
            # 找出这条路径最后揭示的真相（在结局节点上的）
            ending_truths: Set[Tuple[str, int]] = set()
            for node_id in reversed(path.node_ids):
                node = outline.get_node(node_id)
                if node is None:
                    continue
                if node.is_ending:
                    for truth in node.truths:
                        ending_truths.add((truth, node.line_number))
                    break

            path_clues_text = " ".join(path.clues_found).lower()

            for truth_text, truth_line in ending_truths:
                truth_lower = truth_text.lower()
                truth_keywords = _extract_keywords(truth_lower)

                has_foreshadowing = False
                matching_clues = []

                for clue in all_clues:
                    clue_lower = clue.lower()
                    # 检查线索是否包含真相的关键词
                    matches = sum(1 for kw in truth_keywords if len(kw) >= 2 and kw in clue_lower)
                    if matches > 0:
                        matching_clues.append((clue, matches))
                        # 还要检查这条线索是否在当前路径中
                        if clue in path.clues_found:
                            has_foreshadowing = True

                if not has_foreshadowing and truth_text not in seen_weak:
                    seen_weak.add(truth_text)
                    detail_parts = []
                    if matching_clues:
                        clue_names = ", ".join(f"「{c[0]}」" for c in matching_clues[:3])
                        detail_parts.append(f"其他路径中有相关线索: {clue_names}")
                    else:
                        detail_parts.append("全文未发现相关铺垫线索")

                    issues.append(Issue(
                        issue_type="弱铺垫",
                        severity="warning",
                        message=f"真相「{truth_text}」在结局「{ending_name}」中揭示，但缺少前置铺垫",
                        line_numbers=[truth_line],
                        details="; ".join(detail_parts),
                        suggestion=f"在到达该结局的路径中，提前添加 @clue 标记来暗示「{truth_text}」相关的信息"
                    ))

    return issues


def _extract_keywords(text: str) -> List[str]:
    """
    从文本中提取关键词用于匹配：
    - 英文：提取连续2个以上字母的单词
    - 中文：滑动窗口提取所有2字组合（确保"母亲"能在"母亲是凶手"和"母亲衣服"中匹配）
    """
    import re
    keywords: Set[str] = set()

    # 英文单词
    for m in re.finditer(r'[a-zA-Z]{2,}', text):
        keywords.add(m.group(0))

    # 中文：滑动窗口取2字组合
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


def run_all_checks(outline: ParsedOutline) -> CheckReport:
    """运行所有检查并生成报告"""
    traversal = traverse_all_paths(outline)

    all_ending_nodes = outline.all_ending_nodes()
    all_ending_names = set()
    for node in all_ending_nodes:
        all_ending_names.update(node.endings)

    report = CheckReport(
        file_path=outline.file_path,
        total_endings=len(all_ending_names),
        reachable_endings=len(traversal.reachable_endings),
        total_paths=len(traversal.all_paths)
    )

    report.issues.extend(check_unreachable_endings(outline, traversal))
    report.issues.extend(check_conflicts(outline, traversal))
    report.issues.extend(check_weak_foreshadowing(outline, traversal))

    # 按严重程度排序: error > warning > info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    report.issues.sort(key=lambda i: (severity_order.get(i.severity, 99), i.issue_type, i.line_numbers))

    return report
