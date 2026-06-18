"""配置文件管理 - 支持同义词、关键词、忽略列表等自定义"""

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple
from pathlib import Path


DEFAULT_CONFIG_FILENAME = ".chaincheck.json"


@dataclass
class CheckerConfig:
    """检查器配置"""

    item_synonyms: Dict[str, List[str]] = field(default_factory=dict)
    """物品同义词映射：主名称 -> 别名列表。例如 {'破损铃铛': ['铃铛碎片', '铜铃碎片']}"""

    truth_keywords: List[str] = field(default_factory=list)
    """真相相关关键词，用于线索匹配判断。例如 ['母亲', '井', '铃']"""

    ignore_issues: List[str] = field(default_factory=list)
    """需要忽略的问题模式，支持通配符。例如 ['物品「火柴」*获得后又失去', '*弱铺垫*']"""

    ignore_endings: List[str] = field(default_factory=list)
    """需要忽略的结局名称。例如 ['测试结局']"""

    ignore_items: List[str] = field(default_factory=list)
    """不需要检查冲突的一次性道具。例如 ['火柴', '一次性钥匙']"""

    clue_match_threshold: int = 1
    """关键词匹配阈值，达到多少个关键词匹配才算有铺垫"""

    _item_synonym_reverse: Dict[str, str] = field(default_factory=dict, init=False)
    """反向映射：别名 -> 主名称"""

    def __post_init__(self):
        self._build_reverse_mapping()

    def _build_reverse_mapping(self) -> None:
        self._item_synonym_reverse = {}
        for main_name, aliases in self.item_synonyms.items():
            self._item_synonym_reverse[main_name] = main_name
            for alias in aliases:
                self._item_synonym_reverse[alias] = main_name

    def resolve_item_name(self, item_name: str) -> str:
        """将物品名解析为标准名称，考虑同义词"""
        return self._item_synonym_reverse.get(item_name, item_name)

    def items_match(self, item_a: str, item_b: str) -> bool:
        """判断两个物品名是否为同一个（考虑同义词）"""
        return self.resolve_item_name(item_a) == self.resolve_item_name(item_b)

    def should_ignore_issue(self, message: str, issue_type: str) -> bool:
        """判断是否应该忽略某个问题"""
        import fnmatch
        for pattern in self.ignore_issues:
            if fnmatch.fnmatch(message, pattern):
                return True
            if fnmatch.fnmatch(issue_type, pattern):
                return True
        return False

    def should_ignore_ending(self, ending_name: str) -> bool:
        """判断是否应该忽略某个结局"""
        import fnmatch
        for pattern in self.ignore_endings:
            if fnmatch.fnmatch(ending_name, pattern):
                return True
        return False

    def is_disposable_item(self, item_name: str) -> bool:
        """判断是否为一次性道具（add->remove 不报冲突）"""
        import fnmatch
        resolved = self.resolve_item_name(item_name)
        for pattern in self.ignore_items:
            if fnmatch.fnmatch(resolved, pattern) or fnmatch.fnmatch(item_name, pattern):
                return True
        return False

    @classmethod
    def load(cls, path: Optional[str] = None) -> 'CheckerConfig':
        """加载配置文件。如果未指定路径，按当前目录->上级目录->默认的顺序查找"""
        if path:
            config_path = Path(path)
            if not config_path.exists():
                raise FileNotFoundError(f"找不到配置文件: {path}")
            return cls._load_from_file(config_path)

        # 查找默认配置
        search_dirs = [Path.cwd()]
        search_dirs.extend(Path.cwd().parents)
        search_dirs.append(Path(__file__).parent.parent)  # 项目根目录

        for d in search_dirs:
            candidate = d / DEFAULT_CONFIG_FILENAME
            if candidate.exists():
                return cls._load_from_file(candidate)

        return cls()

    @classmethod
    def _load_from_file(cls, path: Path) -> 'CheckerConfig':
        data = json.loads(path.read_text(encoding='utf-8'))
        return cls(
            item_synonyms=data.get('item_synonyms', {}),
            truth_keywords=data.get('truth_keywords', []),
            ignore_issues=data.get('ignore_issues', []),
            ignore_endings=data.get('ignore_endings', []),
            ignore_items=data.get('ignore_items', []),
            clue_match_threshold=data.get('clue_match_threshold', 1),
        )

    def save(self, path: str) -> None:
        """保存配置到文件"""
        data = {
            "item_synonyms": self.item_synonyms,
            "truth_keywords": self.truth_keywords,
            "ignore_issues": self.ignore_issues,
            "ignore_endings": self.ignore_endings,
            "ignore_items": self.ignore_items,
            "clue_match_threshold": self.clue_match_threshold,
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    @classmethod
    def create_default(cls, path: str) -> None:
        """创建默认配置文件模板"""
        default = cls(
            item_synonyms={
                "破损铃铛": ["铃铛碎片", "铜铃", "铜铃碎片"],
                "旧日记": ["日记", "灰烬日记", "残页"]
            },
            truth_keywords=["母亲", "井", "铃", "凶手", "真相"],
            ignore_issues=[],
            ignore_endings=["*测试*", "*草稿*"],
            ignore_items=["火柴", "打火机", "一次性钥匙"],
            clue_match_threshold=1,
        )
        default.save(path)
