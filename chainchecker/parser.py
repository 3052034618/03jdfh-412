"""大纲文档解析器 - 解析章节文档中的标记并构建节点树"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Set, Tuple
from pathlib import Path


@dataclass
class Node:
    """大纲中的一个节点（段落、选择、结局等）"""
    id: str
    line_number: int
    text: str
    indent: int
    node_type: str = "normal"  # normal, choice, ending, conditional
    parent: Optional[str] = None
    children: List[str] = field(default_factory=list)

    # 解析出的标记
    items_add: Set[str] = field(default_factory=set)
    items_remove: Set[str] = field(default_factory=set)
    flags_set: Set[str] = field(default_factory=set)
    flags_clear: Set[str] = field(default_factory=set)
    conditions: Set[str] = field(default_factory=set)
    endings: Set[str] = field(default_factory=set)
    clues: Set[str] = field(default_factory=set)
    truths: Set[str] = field(default_factory=set)
    choice_label: Optional[str] = None

    @property
    def is_ending(self) -> bool:
        return len(self.endings) > 0

    @property
    def is_choice(self) -> bool:
        return self.choice_label is not None

    @property
    def has_conditions(self) -> bool:
        return len(self.conditions) > 0


@dataclass
class ParsedOutline:
    """解析完成的大纲结构"""
    nodes: Dict[str, Node] = field(default_factory=dict)
    root_ids: List[str] = field(default_factory=list)
    file_path: Optional[str] = None
    raw_lines: List[str] = field(default_factory=list)

    def get_node(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id)

    def all_ending_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values() if n.is_ending]

    def all_truths(self) -> Set[str]:
        truths = set()
        for n in self.nodes.values():
            truths.update(n.truths)
        return truths

    def all_clues(self) -> Set[str]:
        clues = set()
        for n in self.nodes.values():
            clues.update(n.clues)
        return clues


# 标记正则
PATTERN_ITEM_ADD = re.compile(r'@item:\+([^@\s]+)')
PATTERN_ITEM_REMOVE = re.compile(r'@item:-([^@\s]+)')
PATTERN_FLAG_SET = re.compile(r'@flag:([^@\s!][^@\s]*)')
PATTERN_FLAG_CLEAR = re.compile(r'@flag:!([^@\s]+)')
PATTERN_COND = re.compile(r'@cond:([^@\s]+)')
PATTERN_ENDING = re.compile(r'@ending:([^@\s]+(?:\s+[^@\s]+)*)')
PATTERN_CLUE = re.compile(r'@clue:([^@]+?)(?=@|$)')
PATTERN_TRUTH = re.compile(r'@truth:([^@]+?)(?=@|$)')
PATTERN_CHOICE = re.compile(r'@choice:([^@]+?)(?=@|$)')


def _parse_markers(text: str, node: Node) -> None:
    """从文本行中解析各类标记"""
    for m in PATTERN_ITEM_ADD.finditer(text):
        node.items_add.add(m.group(1).strip())
    for m in PATTERN_ITEM_REMOVE.finditer(text):
        node.items_remove.add(m.group(1).strip())
    for m in PATTERN_FLAG_SET.finditer(text):
        node.flags_set.add(m.group(1).strip())
    for m in PATTERN_FLAG_CLEAR.finditer(text):
        node.flags_clear.add(m.group(1).strip())
    for m in PATTERN_COND.finditer(text):
        node.conditions.add(m.group(1).strip())
    for m in PATTERN_ENDING.finditer(text):
        node.endings.add(m.group(1).strip())
    for m in PATTERN_CLUE.finditer(text):
        clue_text = m.group(1).strip()
        if clue_text:
            node.clues.add(clue_text)
    for m in PATTERN_TRUTH.finditer(text):
        truth_text = m.group(1).strip()
        if truth_text:
            node.truths.add(truth_text)
    for m in PATTERN_CHOICE.finditer(text):
        choice_text = m.group(1).strip()
        if choice_text:
            node.choice_label = choice_text
            node.node_type = "choice"

    if node.is_ending:
        node.node_type = "ending"
    if node.has_conditions:
        node.node_type = "conditional"


def _calculate_indent(line: str) -> int:
    """计算行的缩进级别（每4个空格或1个tab算一级）"""
    indent = 0
    for ch in line:
        if ch == '\t':
            indent += 1
        elif ch == ' ':
            indent += 0.25
        else:
            break
    return int(indent)


def parse_outline(file_path: str) -> ParsedOutline:
    """解析大纲文件"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"找不到大纲文件: {file_path}")

    raw_lines = path.read_text(encoding='utf-8').splitlines()
    outline = ParsedOutline(file_path=str(path), raw_lines=raw_lines)

    # 使用栈来管理父子关系（基于缩进）
    stack: List[Tuple[int, str]] = []  # (indent, node_id)
    node_counter = 0

    for line_num, raw_line in enumerate(raw_lines, start=1):
        # 跳过空行和纯注释
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith('//') or stripped.startswith('#'):
            if not any(tag in stripped for tag in ['@item:', '@flag:', '@cond:', '@ending:', '@clue:', '@truth:', '@choice:']):
                continue

        indent = _calculate_indent(raw_line)

        # 创建节点
        node_counter += 1
        node_id = f"node_{node_counter}"
        node = Node(
            id=node_id,
            line_number=line_num,
            text=stripped,
            indent=indent
        )
        _parse_markers(stripped, node)
        outline.nodes[node_id] = node

        # 确定父节点
        while stack and stack[-1][0] >= indent:
            stack.pop()

        if stack:
            parent_id = stack[-1][1]
            node.parent = parent_id
            outline.nodes[parent_id].children.append(node_id)
        else:
            outline.root_ids.append(node_id)

        stack.append((indent, node_id))

    return outline


def parse_outline_text(text: str, source_name: str = "<text>") -> ParsedOutline:
    """从文本字符串解析大纲（主要用于测试）"""
    outline = ParsedOutline(file_path=source_name, raw_lines=text.splitlines())

    stack: List[Tuple[int, str]] = []
    node_counter = 0

    for line_num, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith('//') or stripped.startswith('#'):
            if not any(tag in stripped for tag in ['@item:', '@flag:', '@cond:', '@ending:', '@clue:', '@truth:', '@choice:']):
                continue

        indent = _calculate_indent(raw_line)
        node_counter += 1
        node_id = f"node_{node_counter}"
        node = Node(
            id=node_id,
            line_number=line_num,
            text=stripped,
            indent=indent
        )
        _parse_markers(stripped, node)
        outline.nodes[node_id] = node

        while stack and stack[-1][0] >= indent:
            stack.pop()

        if stack:
            parent_id = stack[-1][1]
            node.parent = parent_id
            outline.nodes[parent_id].children.append(node_id)
        else:
            outline.root_ids.append(node_id)

        stack.append((indent, node_id))

    return outline
