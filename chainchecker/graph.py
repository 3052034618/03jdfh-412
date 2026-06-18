"""因果图与状态追踪 - 遍历所有可能路径并追踪游戏状态（支持路径片段和多文件）"""

from dataclasses import dataclass, field
from typing import List, Set, Dict, Tuple, Optional, FrozenSet
from collections import deque
from pathlib import Path

from .parser import ParsedOutline, Node
from .config import CheckerConfig


@dataclass(frozen=True)
class GameState:
    """不可变的游戏状态，用于路径追踪"""
    items: FrozenSet[str] = field(default_factory=frozenset)
    flags: FrozenSet[str] = field(default_factory=frozenset)
    config: Optional[CheckerConfig] = field(default=None, compare=False)

    def _resolve(self, name: str) -> str:
        if self.config:
            return self.config.resolve_item_name(name)
        return name

    def has_item(self, item: str) -> bool:
        resolved = self._resolve(item)
        for it in self.items:
            if self._resolve(it) == resolved:
                return True
        return False

    def has_flag(self, flag: str) -> bool:
        return flag in self.flags

    def with_item_added(self, item: str) -> 'GameState':
        return GameState(
            items=frozenset(self.items | {item}),
            flags=self.flags,
            config=self.config
        )

    def with_item_removed(self, item: str) -> 'GameState':
        resolved_remove = self._resolve(item)
        remaining = [it for it in self.items if self._resolve(it) != resolved_remove]
        return GameState(
            items=frozenset(remaining),
            flags=self.flags,
            config=self.config
        )

    def with_flag_set(self, flag: str) -> 'GameState':
        return GameState(
            items=self.items,
            flags=frozenset(self.flags | {flag}),
            config=self.config
        )

    def with_flag_cleared(self, flag: str) -> 'GameState':
        return GameState(
            items=self.items,
            flags=frozenset(self.flags - {flag}),
            config=self.config
        )

    def meets_condition(self, condition: str) -> bool:
        """检查条件是否满足。考虑同义词。"""
        if condition.startswith('item:'):
            return self.has_item(condition[5:])
        if condition.startswith('flag:'):
            return self.has_flag(condition[5:])
        if condition.startswith('!'):
            negated = condition[1:]
            if negated.startswith('item:'):
                return not self.has_item(negated[5:])
            if negated.startswith('flag:'):
                return not self.has_flag(negated[5:])
            return not self.has_item(negated) and not self.has_flag(negated)
        return self.has_item(condition) or self.has_flag(condition)

    def meets_all_conditions(self, conditions: Set[str]) -> bool:
        return all(self.meets_condition(c) for c in conditions)


@dataclass
class ChoicePoint:
    """路径上的选择点记录"""
    node_id: str
    line_number: int
    source_file: str
    label: str  # 选择标签
    branch_taken: str  # 实际选择的分支文本（子节点的显示文本）

    def format(self) -> str:
        fname = Path(self.source_file).name
        return f"[{fname}:{self.line_number}] 选择「{self.label}」→ {self.branch_taken}"


@dataclass
class PathRecord:
    """一条完整路径的记录"""
    node_ids: List[str] = field(default_factory=list)
    line_numbers: List[int] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)
    state: GameState = field(default_factory=GameState)
    reached_endings: Set[str] = field(default_factory=set)

    # 线索收集：区分路径中收集的和结局现场收集的
    clues_found_before_ending: Set[str] = field(default_factory=set)
    clues_at_ending: Set[str] = field(default_factory=set)
    truths_found: Set[str] = field(default_factory=set)

    # 历史记录
    item_history: List[Tuple[str, str, int, str]] = field(default_factory=list)  # (action, item, line, file)
    flag_history: List[Tuple[str, str, int, str]] = field(default_factory=list)  # (action, flag, line, file)

    # 选择点序列
    choice_points: List[ChoicePoint] = field(default_factory=list)

    # 上一个节点是否为选择节点，用于记录分支走向
    _last_was_choice: bool = False
    _pending_choice_label: Optional[str] = None
    _pending_choice_node_id: Optional[str] = None
    _pending_choice_line: int = 0
    _pending_choice_file: str = ""

    def clone(self) -> 'PathRecord':
        return PathRecord(
            node_ids=list(self.node_ids),
            line_numbers=list(self.line_numbers),
            source_files=list(self.source_files),
            state=self.state,
            reached_endings=set(self.reached_endings),
            clues_found_before_ending=set(self.clues_found_before_ending),
            clues_at_ending=set(self.clues_at_ending),
            truths_found=set(self.truths_found),
            item_history=list(self.item_history),
            flag_history=list(self.flag_history),
            choice_points=list(self.choice_points),
            _last_was_choice=self._last_was_choice,
            _pending_choice_label=self._pending_choice_label,
            _pending_choice_node_id=self._pending_choice_node_id,
            _pending_choice_line=self._pending_choice_line,
            _pending_choice_file=self._pending_choice_file,
        )

    def get_unique_files(self) -> List[str]:
        """获取路径访问过的所有文件，按顺序去重"""
        seen: Set[str] = set()
        result: List[str] = []
        for f in self.source_files:
            if f not in seen:
                seen.add(f)
                result.append(f)
        return result

    def crosses_files(self) -> bool:
        """路径是否跨多个文件"""
        return len(set(self.source_files)) > 1

    def get_path_segment_from_last_choice(self, outline: ParsedOutline) -> List[Tuple[str, str, int, str]]:
        """
        获取从最后一个选择点到当前路径末尾的完整片段。
        返回 [(node_id, display_text, line_number, source_file), ...]
        """
        segment: List[Tuple[str, str, int, str]] = []
        start_idx = 0

        # 找出最后一个选择点之后的节点
        if self.choice_points:
            last_choice_nid = self.choice_points[-1].node_id
            for i, nid in enumerate(self.node_ids):
                if nid == last_choice_nid:
                    start_idx = i
                    break

        for i in range(start_idx, len(self.node_ids)):
            nid = self.node_ids[i]
            node = outline.get_node(nid)
            if node:
                segment.append((
                    nid,
                    node.get_display_text(),
                    self.line_numbers[i],
                    self.source_files[i]
                ))

        return segment

    def format_path_segment(self, outline: ParsedOutline) -> str:
        """格式化路径片段为可读字符串"""
        segment = self.get_path_segment_from_last_choice(outline)
        parts = []
        for _, text, line, fpath in segment:
            fname = Path(fpath).name
            parts.append(f"  ↳ [{fname}:{line}] {text}")
        return "\n".join(parts)

    def format_choice_chain(self) -> str:
        """格式化选择链为可读字符串"""
        if not self.choice_points:
            return "  （无选择点，直线路径）"
        return "\n".join(f"  {cp.format()}" for cp in self.choice_points)


@dataclass
class TraversalResult:
    """遍历完成后的结果"""
    all_paths: List[PathRecord] = field(default_factory=list)
    reachable_endings: Set[str] = field(default_factory=set)
    reachable_ending_nodes: Dict[str, List[PathRecord]] = field(default_factory=dict)  # ending_name -> paths
    ending_file_map: Dict[str, Set[str]] = field(default_factory=dict)  # ending_name -> set of files in path

    def ending_is_reachable(self, ending_name: str) -> bool:
        return ending_name in self.reachable_endings

    def get_ending_files(self, ending_name: str) -> List[str]:
        """获取某个结局路径涉及的所有文件"""
        files = self.ending_file_map.get(ending_name, set())
        return sorted(files)


def _apply_node_state(node: Node, path: PathRecord, outline: ParsedOutline) -> None:
    """将节点的状态变化应用到路径记录中"""
    source_file = node.source_file

    # 处理选择点：如果当前节点是选择节点的第一个子节点，记录选择分支
    if path._last_was_choice and path._pending_choice_label:
        path.choice_points.append(ChoicePoint(
            node_id=path._pending_choice_node_id,
            line_number=path._pending_choice_line,
            source_file=path._pending_choice_file,
            label=path._pending_choice_label,
            branch_taken=node.get_display_text()
        ))
        path._last_was_choice = False
        path._pending_choice_label = None

    # 物品变化
    for item in node.items_add:
        path.state = path.state.with_item_added(item)
        path.item_history.append(('add', item, node.line_number, source_file))
    for item in node.items_remove:
        path.state = path.state.with_item_removed(item)
        path.item_history.append(('remove', item, node.line_number, source_file))

    # 标记变化
    for flag in node.flags_set:
        path.state = path.state.with_flag_set(flag)
        path.flag_history.append(('set', flag, node.line_number, source_file))
    for flag in node.flags_clear:
        path.state = path.state.with_flag_cleared(flag)
        path.flag_history.append(('clear', flag, node.line_number, source_file))

    # 线索：结局节点的线索单独存放，不算作前文铺垫
    if node.is_ending:
        path.clues_at_ending.update(node.clues)
    else:
        path.clues_found_before_ending.update(node.clues)

    path.truths_found.update(node.truths)
    path.reached_endings.update(node.endings)

    # 如果当前节点是选择节点，标记下一个子节点为选择分支
    if node.is_choice and node.choice_label:
        path._last_was_choice = True
        path._pending_choice_label = node.choice_label
        path._pending_choice_node_id = node.id
        path._pending_choice_line = node.line_number
        path._pending_choice_file = source_file


def traverse_all_paths(
    outline: ParsedOutline,
    config: Optional[CheckerConfig] = None
) -> TraversalResult:
    """
    BFS遍历所有可能的有效路径。
    多文件模式下优先使用 entry_node_ids（第一章根 + @entry 节点）作为起点。
    每个节点如果有条件且不满足，则该路径在此终止（不进入此分支）。
    """
    result = TraversalResult()
    initial_state = GameState(config=config)

    queue: deque = deque()

    # ===== 确定起点：优先用 entry_node_ids，否则回退 root_ids =====
    start_ids: List[str] = []
    if outline.is_multi_file and outline.entry_node_ids:
        start_ids = list(outline.entry_node_ids)
    else:
        for root_id in outline.root_ids:
            root = outline.get_node(root_id)
            if root is None:
                continue
            # 单文件 / 向后兼容：只遍历真正起点（没有父节点的）
            if outline.is_multi_file and root.parent is not None:
                continue
            start_ids.append(root_id)

    for start_id in start_ids:
        root = outline.get_node(start_id)
        if root is None:
            continue

        path = PathRecord()
        path.node_ids.append(start_id)
        path.line_numbers.append(root.line_number)
        path.source_files.append(root.source_file)

        if not root.has_conditions or initial_state.meets_all_conditions(root.conditions):
            _apply_node_state(root, path, outline)
            queue.append(path)

    visited: Set[Tuple[str, FrozenSet[str], FrozenSet[str]]] = set()

    max_paths = 50000
    paths_count = 0

    while queue and paths_count < max_paths:
        current = queue.popleft()
        paths_count += 1

        if not current.node_ids:
            continue

        last_node_id = current.node_ids[-1]
        last_node = outline.get_node(last_node_id)
        if last_node is None:
            continue

        state_key = (last_node_id, current.state.items, current.state.flags)
        if state_key in visited:
            continue
        visited.add(state_key)

        if last_node.is_ending:
            result.all_paths.append(current)
            for ending in last_node.endings:
                result.reachable_endings.add(ending)
                if ending not in result.reachable_ending_nodes:
                    result.reachable_ending_nodes[ending] = []
                result.reachable_ending_nodes[ending].append(current)
                if ending not in result.ending_file_map:
                    result.ending_file_map[ending] = set()
                result.ending_file_map[ending].update(current.get_unique_files())
            continue

        if not last_node.children:
            result.all_paths.append(current)
            continue

        for child_id in last_node.children:
            child = outline.get_node(child_id)
            if child is None:
                continue

            if child.has_conditions and not current.state.meets_all_conditions(child.conditions):
                continue

            new_path = current.clone()
            new_path.node_ids.append(child_id)
            new_path.line_numbers.append(child.line_number)
            new_path.source_files.append(child.source_file)
            _apply_node_state(child, new_path, outline)
            queue.append(new_path)

    return result
