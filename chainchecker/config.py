"""配置文件管理 - 增强版：支持同义词、关键词、忽略列表、项目级规则、严重程度、到期时间"""

import json
import re
import fnmatch
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple, Any
from pathlib import Path
from datetime import datetime, date


DEFAULT_CONFIG_FILENAME = ".chaincheck.json"


@dataclass
class IgnoreRule:
    """单条忽略规则，支持通配符匹配和到期时间"""
    pattern: str
    expires: Optional[str] = None  # YYYY-MM-DD 格式的到期日期
    reason: str = ""
    issue_type: Optional[str] = None  # 只忽略特定问题类型

    def is_expired(self) -> bool:
        """规则是否已过期"""
        if not self.expires:
            return False
        try:
            exp_date = datetime.strptime(self.expires, "%Y-%m-%d").date()
            return date.today() > exp_date
        except ValueError:
            return False

    def matches(self, message: str, issue_type: str) -> bool:
        """检查是否匹配此规则（未过期时才匹配）"""
        if self.is_expired():
            return False
        if self.issue_type and self.issue_type != issue_type:
            return False
        return fnmatch.fnmatch(message, self.pattern) or fnmatch.fnmatch(issue_type, self.pattern)


@dataclass
class SeverityOverride:
    """严重程度覆盖规则"""
    issue_type: str  # 问题类型：不可达结局/条件冲突/弱铺垫
    pattern: str = "*"  # 对哪些问题消息生效
    new_severity: str = "info"  # 覆盖成什么级别


@dataclass
class CheckerConfig:
    """增强版检查器配置"""

    # ===== 原有基础配置 =====
    item_synonyms: Dict[str, List[str]] = field(default_factory=dict)
    truth_keywords: List[str] = field(default_factory=list)
    ignore_items: List[str] = field(default_factory=list)
    clue_match_threshold: int = 1

    # ===== 向后兼容的旧字段（迁移到 ignore_rules）=====
    ignore_issues: List[str] = field(default_factory=list)
    ignore_endings: List[str] = field(default_factory=list)

    # ===== 新增强：项目级规则 =====
    ignore_rules: List[IgnoreRule] = field(default_factory=list)
    """灵活的忽略规则列表，替代旧的 ignore_issues/ignore_endings"""

    severity_overrides: List[SeverityOverride] = field(default_factory=list)
    """严重程度覆盖规则"""

    only_check_endings: List[str] = field(default_factory=list)
    """只检查指定的结局路径（空=全部检查），支持通配符"""

    only_check_files: List[str] = field(default_factory=list)
    """只检查指定的文件（空=全部），支持通配符"""

    draft_mode: bool = False
    """草稿模式：仅报告严重问题，弱化警告"""

    strict_mode: bool = False
    """严格模式：将所有警告升级为错误"""

    # ===== 内部使用 =====
    _item_synonym_reverse: Dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self):
        self._build_reverse_mapping()
        # 兼容旧的 ignore_issues/ignore_endings -> 转为 IgnoreRule
        if not hasattr(self, 'ignore_issues'):
            self.ignore_issues: List[str] = []
        if not hasattr(self, 'ignore_endings'):
            self.ignore_endings: List[str] = []
        self._migrate_legacy_ignores()

    def _migrate_legacy_ignores(self) -> None:
        """将旧的 ignore_issues/ignore_endings 迁移到 ignore_rules"""
        for p in getattr(self, 'ignore_issues', []):
            if not any(r.pattern == p for r in self.ignore_rules):
                self.ignore_rules.append(IgnoreRule(pattern=p))
        for p in getattr(self, 'ignore_endings', []):
            if not any(r.pattern == p and r.issue_type == "__ending__" for r in self.ignore_rules):
                self.ignore_rules.append(IgnoreRule(pattern=p, issue_type="__ending__"))

    def _build_reverse_mapping(self) -> None:
        self._item_synonym_reverse = {}
        for main_name, aliases in self.item_synonyms.items():
            self._item_synonym_reverse[main_name] = main_name
            for alias in aliases:
                self._item_synonym_reverse[alias] = main_name

    # ===== 同义词 =====
    def resolve_item_name(self, item_name: str) -> str:
        return self._item_synonym_reverse.get(item_name, item_name)

    def items_match(self, item_a: str, item_b: str) -> bool:
        return self.resolve_item_name(item_a) == self.resolve_item_name(item_b)

    # ===== 一次性道具 =====
    def is_disposable_item(self, item_name: str) -> bool:
        resolved = self.resolve_item_name(item_name)
        for pattern in self.ignore_items:
            if fnmatch.fnmatch(resolved, pattern) or fnmatch.fnmatch(item_name, pattern):
                return True
        return False

    # ===== 忽略规则 =====
    def should_ignore_issue(self, message: str, issue_type: str) -> bool:
        """根据配置和到期时间判断是否忽略某条问题"""
        for rule in self.ignore_rules:
            if rule.issue_type == "__ending__":
                continue  # 结局忽略是单独的
            if rule.matches(message, issue_type):
                return True
        return False

    def should_ignore_ending(self, ending_name: str) -> bool:
        """判断是否应该忽略某个结局（考虑通配符和到期时间）"""
        for rule in self.ignore_rules:
            if rule.issue_type == "__ending__":
                if rule.is_expired():
                    continue
                if fnmatch.fnmatch(ending_name, rule.pattern):
                    return True
        return False

    # ===== 结局路径过滤 =====
    def should_check_ending(self, ending_name: str) -> bool:
        """是否需要检查指定结局（草稿阶段分批推进用）"""
        # 如果在 only_check_endings 中有匹配，通过
        if self.only_check_endings:
            matched = False
            for pattern in self.only_check_endings:
                if fnmatch.fnmatch(ending_name, pattern):
                    matched = True
                    break
            if not matched:
                return False
        return True

    # ===== 文件过滤 =====
    def should_check_file(self, file_path: str) -> bool:
        """是否需要检查指定文件"""
        if not self.only_check_files:
            return True
        for pattern in self.only_check_files:
            if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(Path(file_path).name, pattern):
                return True
        return False

    # ===== 严重程度覆盖 =====
    def override_severity(self, issue_type: str, message: str, default_severity: str) -> str:
        """根据规则覆盖严重程度"""
        result = default_severity

        # 草稿模式：警告降级
        if self.draft_mode and result == "warning":
            result = "info"
        # 严格模式：警告升级
        if self.strict_mode and result == "warning":
            result = "error"

        # 用户自定义覆盖
        for override in self.severity_overrides:
            if override.issue_type == issue_type or fnmatch.fnmatch(issue_type, override.issue_type):
                if override.pattern == "*" or fnmatch.fnmatch(message, override.pattern):
                    result = override.new_severity
                    break

        return result

    # ===== 序列化 =====
    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_synonyms": self.item_synonyms,
            "truth_keywords": self.truth_keywords,
            "ignore_items": self.ignore_items,
            "clue_match_threshold": self.clue_match_threshold,
            "ignore_rules": [
                {"pattern": r.pattern, "expires": r.expires, "reason": r.reason, "issue_type": r.issue_type}
                for r in self.ignore_rules
            ],
            "severity_overrides": [
                {"issue_type": o.issue_type, "pattern": o.pattern, "new_severity": o.new_severity}
                for o in self.severity_overrides
            ],
            "only_check_endings": self.only_check_endings,
            "only_check_files": self.only_check_files,
            "draft_mode": self.draft_mode,
            "strict_mode": self.strict_mode,
        }

    def save(self, path: str) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CheckerConfig':
        ignore_rules_data = data.get('ignore_rules', [])
        ignore_rules = [
            IgnoreRule(
                pattern=r.get('pattern', ''),
                expires=r.get('expires'),
                reason=r.get('reason', ''),
                issue_type=r.get('issue_type')
            )
            for r in ignore_rules_data
        ]

        severity_overrides_data = data.get('severity_overrides', [])
        severity_overrides = [
            SeverityOverride(
                issue_type=o.get('issue_type', ''),
                pattern=o.get('pattern', '*'),
                new_severity=o.get('new_severity', 'info')
            )
            for o in severity_overrides_data
        ]

        return cls(
            item_synonyms=data.get('item_synonyms', {}),
            truth_keywords=data.get('truth_keywords', []),
            ignore_items=data.get('ignore_items', []),
            clue_match_threshold=data.get('clue_match_threshold', 1),
            ignore_rules=ignore_rules,
            severity_overrides=severity_overrides,
            only_check_endings=data.get('only_check_endings', []),
            only_check_files=data.get('only_check_files', []),
            draft_mode=data.get('draft_mode', False),
            strict_mode=data.get('strict_mode', False),
            # 兼容旧字段
            ignore_issues=data.get('ignore_issues', []),
            ignore_endings=data.get('ignore_endings', []),
        )

    @classmethod
    def _load_from_file(cls, path: Path) -> 'CheckerConfig':
        data = json.loads(path.read_text(encoding='utf-8'))
        return cls.from_dict(data)

    @classmethod
    def load(cls, path: Optional[str] = None) -> 'CheckerConfig':
        if path:
            config_path = Path(path)
            if not config_path.exists():
                raise FileNotFoundError(f"找不到配置文件: {path}")
            return cls._load_from_file(config_path)

        search_dirs = [Path.cwd()]
        search_dirs.extend(Path.cwd().parents)
        search_dirs.append(Path(__file__).parent.parent)

        for d in search_dirs:
            candidate = d / DEFAULT_CONFIG_FILENAME
            if candidate.exists():
                return cls._load_from_file(candidate)

        return cls()

    @classmethod
    def create_default(cls, path: str) -> None:
        """创建增强版默认配置文件模板"""
        default = cls(
            item_synonyms={
                "破损铃铛": ["铃铛碎片", "铜铃", "铜铃碎片"],
                "旧日记": ["日记", "灰烬日记", "残页"]
            },
            truth_keywords=["母亲", "井", "铃", "凶手", "真相"],
            ignore_items=["火柴", "打火机", "一次性钥匙"],
            clue_match_threshold=1,
            ignore_rules=[
                IgnoreRule(pattern="*测试*", issue_type="__ending__", reason="忽略测试结局"),
                IgnoreRule(pattern="*草稿*", issue_type="__ending__", reason="忽略草稿结局"),
                IgnoreRule(pattern="*弱铺垫*", expires="2026-12-31", reason="草稿阶段暂时忽略铺垫检查，年底前补完"),
            ],
            severity_overrides=[
                SeverityOverride(issue_type="弱铺垫", pattern="*真相*", new_severity="error",
                                 reason="关键真相的铺垫检查必须严格"),
            ],
            only_check_endings=[],  # 空=检查全部
            only_check_files=[],    # 空=检查全部
            draft_mode=False,
            strict_mode=False,
        )
        default.save(path)
