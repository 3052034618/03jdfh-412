"""大纲文档解析器 - 解析章节文档中的标记并构建节点树（多文件版）"""

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
    source_file: str
    node_type: str = "normal"  # normal, choice, ending, conditional, goto
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
    goto_target: Optional[str] = None  # 跨文件跳转目标

    @property
    def is_ending(self) -> bool:
        return len(self.endings) > 0

    @property
    def is_choice(self) -> bool:
        return self.choice_label is not None

    @property
    def has_conditions(self) -> bool:
        return len(self.conditions) > 0

    @property
    def is_goto(self) -> bool:
        return self.goto_target is not None

    def get_display_text(self, max_len: int = 40) -> str:
        """获取用于路径显示的精简文本"""
        if self.is_ending:
            return f"结局:{next(iter(self.endings))}"
        if self.is_choice and self.choice_label:
            return f"选择:{self.choice_label}"
        if self.has_conditions:
            cond = next(iter(self.conditions))
            return f"条件:{cond}"
        # 移除标记，只保留纯文本
        clean = re.sub(r'@\w+:[^@\s]+', '', self.text).strip()
        clean = re.sub(r'@\w+:[^@]+?(?=@|$)', '', clean).strip()
        if len(clean) > max_len:
            clean = clean[:max_len-3] + "..."
        return clean or self.text[:max_len]


@dataclass
class ParsedOutline:
    """解析完成的大纲结构（可包含多个文件）"""
    nodes: Dict[str, Node] = field(default_factory=dict)
    root_ids: List[str] = field(default_factory=list)
    file_path: Optional[str] = None
    raw_lines: List[str] = field(default_factory=list)

    # 多文件支持
    is_multi_file: bool = False
    files: Dict[str, 'ParsedOutline'] = field(default_factory=dict)
    file_order: List[str] = field(default_factory=list)  # 文件名按章节顺序排列

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

    def get_node_file(self, node_id: str) -> Optional[str]:
        node = self.get_node(node_id)
        return node.source_file if node else None

    def get_file_nodes(self, file_path: str) -> List[Node]:
        return [n for n in self.nodes.values() if n.source_file == file_path]


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
PATTERN_GOTO = re.compile(r'@goto:([^@\s]+)')  # 跨文件跳转


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
    for m in PATTERN_GOTO.finditer(text):
        node.goto_target = m.group(1).strip()
        node.node_type = "goto"

    if node.is_ending:
        node.node_type = "ending"
    if node.has_conditions and not node.is_choice and not node.is_ending:
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


def _parse_single_file(
    file_path: Path,
    global_node_counter: List[int],
    source_file_override: Optional[str] = None
) -> Tuple[ParsedOutline, Dict[str, str]]:
    """
    解析单个文件，返回解析结果和 goto 标签映射（label -> node_id）
    """
    if not file_path.exists():
        raise FileNotFoundError(f"找不到大纲文件: {file_path}")

    source_name = source_file_override or str(file_path)
    raw_lines = file_path.read_text(encoding='utf-8').splitlines()
    outline = ParsedOutline(file_path=str(file_path), raw_lines=raw_lines)

    stack: List[Tuple[int, str]] = []
    label_to_node: Dict[str, str] = {}

    for line_num, raw_line in enumerate(raw_lines, start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith('//') or stripped.startswith('#'):
            if not any(tag in stripped for tag in [
                '@item:', '@flag:', '@cond:', '@ending:',
                '@clue:', '@truth:', '@choice:', '@goto:', '@label:'
            ]):
                continue

        # 解析 @label 用于跨文件跳转定位
        label_match = re.search(r'@label:([^@\s]+)', stripped)
        if label_match:
            label_name = label_match.group(1).strip()

        indent = _calculate_indent(raw_line)
        global_node_counter[0] += 1
        node_id = f"node_{global_node_counter[0]}"

        node = Node(
            id=node_id,
            line_number=line_num,
            text=stripped,
            indent=indent,
            source_file=source_name
        )
        _parse_markers(stripped, node)
        outline.nodes[node_id] = node

        if label_match:
            label_to_node[label_name] = node_id

        while stack and stack[-1][0] >= indent:
            stack.pop()

        if stack:
            parent_id = stack[-1][1]
            node.parent = parent_id
            outline.nodes[parent_id].children.append(node_id)
        else:
            outline.root_ids.append(node_id)

        stack.append((indent, node_id))

    return outline, label_to_node


def parse_outline(file_path: str) -> ParsedOutline:
    """解析单个大纲文件（向后兼容）"""
    counter = [0]
    outline, _ = _parse_single_file(Path(file_path), counter)
    return outline


def parse_outline_text(text: str, source_name: str = "<text>") -> ParsedOutline:
    """从文本字符串解析大纲（主要用于测试）"""
    outline = ParsedOutline(file_path=source_name, raw_lines=text.splitlines())
    counter = [0]

    stack: List[Tuple[int, str]] = []

    for line_num, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith('//') or stripped.startswith('#'):
            if not any(tag in stripped for tag in [
                '@item:', '@flag:', '@cond:', '@ending:',
                '@clue:', '@truth:', '@choice:', '@goto:'
            ]):
                continue

        indent = _calculate_indent(raw_line)
        counter[0] += 1
        node_id = f"node_{counter[0]}"

        node = Node(
            id=node_id,
            line_number=line_num,
            text=stripped,
            indent=indent,
            source_file=source_name
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


def parse_chapter_directory(dir_path: str, file_pattern: str = "*.md") -> ParsedOutline:
    """
    解析一个章节目录下的所有文件。
    文件名按自然排序（chap1.md, chap2.md...）作为章节顺序。
    一个文件的叶子节点（无子节点且非结局）会自动连接到下一个文件的根节点，形成跨章节连续剧情。
    """
    dir_p = Path(dir_path)
    if not dir_p.is_dir():
        raise NotADirectoryError(f"不是目录: {dir_path}")

    # 查找所有符合模式的文件，按文件名排序
    files = sorted(dir_p.glob(file_pattern))
    if not files:
        files = sorted(dir_p.glob("*.txt"))
    if not files:
        raise FileNotFoundError(f"在 {dir_path} 中未找到大纲文件")

    multi_outline = ParsedOutline(is_multi_file=True, file_path=str(dir_p))
    counter = [0]
    all_labels: Dict[str, str] = {}

    # 先解析所有文件，收集标签
    file_outlines: List[Tuple[str, ParsedOutline, Dict[str, str]]] = []
    for fp in files:
        source_name = str(fp)
        multi_outline.file_order.append(source_name)
        outline, labels = _parse_single_file(fp, counter, source_name)
        file_outlines.append((source_name, outline, labels))
        multi_outline.files[source_name] = outline
        all_labels.update(labels)

    # 合并所有节点到 multi_outline
    for source_name, outline, _ in file_outlines:
        for nid, node in outline.nodes.items():
            multi_outline.nodes[nid] = node
        multi_outline.root_ids.extend(outline.root_ids)

    # 处理 @goto 跳转：连接 goto 节点到目标节点
    for nid, node in multi_outline.nodes.items():
        if node.is_goto and node.goto_target in all_labels:
            target_nid = all_labels[node.goto_target]
            node.children.append(target_nid)
            target_node = multi_outline.nodes[target_nid]
            if target_node.parent is None:
                target_node.parent = nid

    # 处理隐式跨章节连接：
    # 如果文件A的最后一个根路径下的叶子节点不是结局，连接到文件B的第一个根节点
    for i in range(len(file_outlines) - 1):
        source_name, outline_a, _ = file_outlines[i]
        next_name, outline_b, _ = file_outlines[i+1]

        # 找出 outline_a 中所有无子节点且非结局的节点
        leaf_nodes = [
            n for n in outline_a.nodes.values()
            if not n.children and not n.is_ending
        ]

        # 找出 outline_b 的根节点
        next_roots = outline_b.root_ids

        for leaf in leaf_nodes:
            if not leaf.is_goto:  # 已有显式 goto 的不覆盖
                for next_root in next_roots:
                    if next_root not in leaf.children:
                        leaf.children.append(next_root)

    return multi_outline
