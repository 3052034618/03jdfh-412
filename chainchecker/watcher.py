"""Watch 模式 - 文件变动自动重新检查，只显示变化的问题，保留上次总览"""

import time
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field

from .parser import parse_outline, parse_chapter_directory
from .checkers import run_all_checks, CheckReport, Issue
from .config import CheckerConfig, DEFAULT_CONFIG_FILENAME


@dataclass
class FileSnapshot:
    """单个文件的快照信息"""
    path: str
    mtime: float
    size: int

    def has_changed(self, other: 'FileSnapshot') -> bool:
        return self.mtime != other.mtime or self.size != other.size


@dataclass
class WatchState:
    """watch 模式的状态"""
    snapshots: Dict[str, FileSnapshot] = field(default_factory=dict)
    last_report: Optional[CheckReport] = None
    last_issue_keys: Set[Tuple[str, str, str]] = field(default_factory=set)  # 用于比较问题差异
    run_count: int = 0

    @staticmethod
    def issue_key(issue: Issue) -> Tuple[str, str, str]:
        """生成问题的唯一标识键（用于比较新旧）"""
        lines_key = ",".join(str(l) for l in issue.line_numbers)
        files_key = ",".join(Path(f).name for f in issue.source_files) if issue.source_files else ""
        return (issue.issue_type, issue.severity, issue.message[:60] + "|" + lines_key + "|" + files_key)


def _collect_target_files(path: Path, pattern: str = "*.md") -> List[Path]:
    """收集需要监控的文件列表"""
    if path.is_file():
        return [path]
    files = list(path.glob(pattern))
    if not files:
        files = list(path.glob("*.txt"))
    # 也监控配置文件
    config_path = path / DEFAULT_CONFIG_FILENAME if path.is_dir() else path.parent / DEFAULT_CONFIG_FILENAME
    if config_path.exists():
        files.append(config_path)
    return sorted(files)


def _take_snapshots(files: List[Path]) -> Dict[str, FileSnapshot]:
    """对所有文件拍快照"""
    snaps: Dict[str, FileSnapshot] = {}
    for f in files:
        try:
            stat = f.stat()
            snaps[str(f)] = FileSnapshot(path=str(f), mtime=stat.st_mtime, size=stat.st_size)
        except OSError:
            pass
    return snaps


def _detect_changes(
    old_snaps: Dict[str, FileSnapshot],
    new_snaps: Dict[str, FileSnapshot]
) -> Tuple[bool, List[str]]:
    """检测文件是否有变化，返回(是否变化, 变化文件列表)"""
    changed: List[str] = []
    # 检查已存在文件的修改
    for p, new_snap in new_snaps.items():
        old_snap = old_snaps.get(p)
        if old_snap is None or old_snap.has_changed(new_snap):
            changed.append(p)
    # 检查文件数量变化（新增/删除）
    if set(old_snaps.keys()) != set(new_snaps.keys()):
        if not changed:
            changed = list(new_snaps.keys())
    return (len(changed) > 0, changed)


def _run_check(target_path: Path, config_path: Optional[str], pattern: str) -> Optional[CheckReport]:
    """运行一次检查"""
    try:
        config = CheckerConfig.load(config_path) if config_path else CheckerConfig.load()
        if target_path.is_dir():
            outline = parse_chapter_directory(str(target_path), pattern)
        else:
            outline = parse_outline(str(target_path))
        return run_all_checks(outline, config)
    except Exception as e:
        print(f"\n⚠️  检查出错: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return None


def _format_summary_line(report: CheckReport) -> str:
    """格式化摘要行（保留在终端顶部）"""
    errs = len(report.errors)
    warns = len(report.warnings)
    infos = len(report.infos)
    parts = [
        f"结局 {report.reachable_endings}/{report.total_endings}",
        f"路径 {report.total_paths}",
    ]
    if errs:
        parts.append(f"🔴{errs}")
    if warns:
        parts.append(f"🟡{warns}")
    if infos:
        parts.append(f"🔵{infos}")
    if not errs and not warns and not infos:
        parts.append("✅ 无问题")
    return " | ".join(parts)


def _print_diff_report(
    new_report: CheckReport,
    old_keys: Set[Tuple[str, str, str]],
    state: WatchState,
    changed_files: List[str],
    show_details: bool = True,
) -> None:
    """打印差异报告：只显示新增/变化的问题，保留上次总览"""

    new_keys = {WatchState.issue_key(i): i for i in new_report.issues}

    added = [i for k, i in new_keys.items() if k not in old_keys]
    fixed = [k for k in old_keys if k not in new_keys]

    timestamp = time.strftime("%H:%M:%S")
    changed_names = ", ".join(Path(f).name for f in changed_files) if changed_files else "(配置变动)"

    # 分隔线 + 摘要
    print("\n" + "=" * 70)
    print(f"⏰ [{timestamp}] 第{state.run_count}次检查 · 检测到文件变动: {changed_names}")
    print(f"📊 最新总览: {_format_summary_line(new_report)}")
    if state.last_report:
        print(f"📊 上次总览: {_format_summary_line(state.last_report)}")

    # 统计变化
    delta_e = len(new_report.errors) - len(state.last_report.errors) if state.last_report else len(new_report.errors)
    delta_w = len(new_report.warnings) - len(state.last_report.warnings) if state.last_report else len(new_report.warnings)
    delta_sign = lambda x: f"(+{x})" if x > 0 else f"({x})" if x < 0 else "(=)"
    if delta_e or delta_w:
        print(f"📈 变化: 错误{delta_sign(delta_e)} 警告{delta_sign(delta_w)}")

    # 修复的问题
    if fixed:
        print(f"\n🎉 已修复 ({len(fixed)} 条问题消失):")
        for k in list(fixed)[:10]:
            print(f"   ✔ {k[0]}: {k[2].split('|')[0]}")
        if len(fixed) > 10:
            print(f"   ... 还有 {len(fixed)-10} 条问题已修复")

    # 新增的问题
    if added:
        print(f"\n🔥 新增/变化问题 ({len(added)} 条):")
        for idx, issue in enumerate(added, 1):
            print(f"   {idx}. {issue.format(show_path_segment=show_details, show_choice_chain=show_details)}")
    elif not fixed and new_report.issues:
        print(f"\nℹ️  暂无新增问题（共 {len(new_report.issues)} 条未处理）")

    if not added and not fixed and new_report.issues:
        print(f"\nℹ️  仍有 {len(new_report.issues)} 条问题待处理（无变化）")

    print("-" * 70)
    print("💡 继续编辑文件将自动重新检查 · 按 Ctrl+C 退出 watch 模式")


def run_watch(
    target: str,
    config_path: Optional[str] = None,
    pattern: str = "*.md",
    poll_interval: float = 1.0,
    show_details: bool = True,
) -> None:
    """
    运行 watch 模式，轮询文件变化自动重检。

    Args:
        target: 文件或目录路径
        config_path: 可选配置文件路径
        pattern: 目录下的文件匹配模式
        poll_interval: 轮询间隔秒数
        show_details: 是否显示选择链和路线片段
    """
    target_path = Path(target)
    if not target_path.exists():
        print(f"[错误] 找不到路径: {target}", file=sys.stderr)
        return

    state = WatchState()

    print("=" * 70)
    print("👁️  因果链检查 Watch 模式启动")
    print(f"   监控对象: {target}")
    print(f"   文件模式: {pattern}")
    print(f"   轮询间隔: {poll_interval}s")
    print("   💡 修改大纲文件后将自动重新检查")
    print("   💡 按 Ctrl+C 退出 watch 模式")
    print("=" * 70)

    # 首次运行（完整报告）
    print("\n▶ 首次检查...")
    report = _run_check(target_path, config_path, pattern)
    if report:
        state.run_count += 1
        state.last_report = report
        state.last_issue_keys = {WatchState.issue_key(i) for i in report.issues}
        state.snapshots = _take_snapshots(_collect_target_files(target_path, pattern))
        # 首次运行显示完整报告
        print(report.format(show_details=show_details))
    else:
        state.snapshots = _take_snapshots(_collect_target_files(target_path, pattern))

    # 监控循环
    try:
        while True:
            time.sleep(poll_interval)
            files = _collect_target_files(target_path, pattern)
            new_snaps = _take_snapshots(files)
            changed, changed_list = _detect_changes(state.snapshots, new_snaps)
            if changed:
                # 稍微等一下，确保文件写入完成
                time.sleep(0.2)
                report = _run_check(target_path, config_path, pattern)
                if report:
                    state.run_count += 1
                    _print_diff_report(
                        report, state.last_issue_keys, state, changed_list, show_details
                    )
                    state.last_issue_keys = {WatchState.issue_key(i) for i in report.issues}
                    state.last_report = report
                state.snapshots = new_snaps

    except KeyboardInterrupt:
        print("\n\n👋 Watch 模式已退出。感谢使用因果链检查助手！")
        if state.last_report:
            print(f"\n📊 最终总览: {_format_summary_line(state.last_report)}")
            print(f"🔍 总计执行 {state.run_count} 次检查")
