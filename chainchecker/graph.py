"""因果图与状态追踪 - 遍历所有可能路径并追踪游戏状态"""

from dataclasses import dataclass, field
from typing import List, Set, Dict, Tuple, Optional, FrozenSet
from collections import deque

from .parser import ParsedOutline, Node


@dataclass(frozen=True)
class GameState:
    """不可变的游戏状态，用于路径追踪"""
    items: FrozenSet[str] = field(default_factory=frozenset)
    flags: FrozenSet[str] = field(default_factory=frozenset)

    def has_item(self, item: str) -> bool:
        return item in self.items

    def has_flag(self, flag: str) -> bool:
        return flag in self.flags

    def with_item_added(self, item: str) -> 'GameState':
        return GameState(items=frozenset(self.items | {item}), flags=self.flags)

    def with_item_removed(self, item: str) -> 'GameState':
        return GameState(items=frozenset(self.items - {item}), flags=self.flags)

    def with_flag_set(self, flag: str) -> 'GameState':
        return GameState(items=self.items, flags=frozenset(self.flags | {flag}))

    def with_flag_cleared(self, flag: str) -> 'GameState':
        return GameState(items=self.items, flags=frozenset(self.flags - {flag}))

    def meets_condition(self, condition: str) -> bool:
        """检查条件是否满足。条件可以是 item:xxx 或 flag:xxx 或简单标记名"""
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
class PathRecord:
    """一条完整路径的记录"""
    node_ids: List[str] = field(default_factory=list)
    line_numbers: List[int] = field(default_factory=list)
    state: GameState = field(default_factory=GameState)
    reached_endings: Set[str] = field(default_factory=set)
    clues_found: Set[str] = field(default_factory=set)
    truths_found: Set[str] = field(default_factory=set)
    item_history: List[Tuple[str, str, int]] = field(default_factory=list)  # (action, item, line)
    flag_history: List[Tuple[str, str, int]] = field(default_factory=list)  # (action, flag, line)

    def clone(self) -> 'PathRecord':
        return PathRecord(
            node_ids=list(self.node_ids),
            line_numbers=list(self.line_numbers),
            state=self.state,
            reached_endings=set(self.reached_endings),
            clues_found=set(self.clues_found),
            truths_found=set(self.truths_found),
            item_history=list(self.item_history),
            flag_history=list(self.flag_history),
        )


@dataclass
class TraversalResult:
    """遍历完成后的结果"""
    all_paths: List[PathRecord] = field(default_factory=list)
    reachable_endings: Set[str] = field(default_factory=set)
    reachable_ending_nodes: Dict[str, List[PathRecord]] = field(default_factory=dict)  # ending_name -> paths

    def ending_is_reachable(self, ending_name: str) -> bool:
        return ending_name in self.reachable_endings


def _apply_node_state(node: Node, path: PathRecord) -> None:
    """将节点的状态变化应用到路径记录中"""
    for item in node.items_add:
        path.state = path.state.with_item_added(item)
        path.item_history.append(('add', item, node.line_number))
    for item in node.items_remove:
        path.state = path.state.with_item_removed(item)
        path.item_history.append(('remove', item, node.line_number))
    for flag in node.flags_set:
        path.state = path.state.with_flag_set(flag)
        path.flag_history.append(('set', flag, node.line_number))
    for flag in node.flags_clear:
        path.state = path.state.with_flag_cleared(flag)
        path.flag_history.append(('clear', flag, node.line_number))

    path.clues_found.update(node.clues)
    path.truths_found.update(node.truths)
    path.reached_endings.update(node.endings)


def traverse_all_paths(outline: ParsedOutline) -> TraversalResult:
    """
    BFS遍历所有可能的有效路径。
    每个节点如果有条件且不满足，则该路径在此终止（不进入此分支）。
    """
    result = TraversalResult()
    initial_state = GameState()

    queue: deque = deque()

    for root_id in outline.root_ids:
        root = outline.get_node(root_id)
        if root is None:
            continue
        path = PathRecord()
        path.node_ids.append(root_id)
        path.line_numbers.append(root.line_number)

        if not root.has_conditions or initial_state.meets_all_conditions(root.conditions):
            _apply_node_state(root, path)
            queue.append(path)

    visited: Set[Tuple[str, FrozenSet[str], FrozenSet[str]]] = set()

    max_paths = 10000
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
            _apply_node_state(child, new_path)
            queue.append(new_path)

    return result
