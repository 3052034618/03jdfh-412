"""命令行界面（增强版）- 支持目录检查、配置文件、路径片段"""

import sys
import argparse
import json
from pathlib import Path
from typing import List

from .parser import parse_outline, parse_chapter_directory
from .checkers import run_all_checks, CheckReport, Issue
from .config import CheckerConfig, DEFAULT_CONFIG_FILENAME


def print_help_syntax() -> None:
    """打印标记语法帮助"""
    print("""
标记语法说明:
────────────────────────────────────────
  @item:+物品名       获得物品（如 @item:+破损铃铛）
  @item:-物品名       失去/消耗物品（如 @item:-日记）
  @flag:标记名        设置状态标记（如 @flag:已回头）
  @flag:!标记名       清除状态标记
  @cond:条件名        路径前置条件（如 @cond:破损铃铛）
                      支持 !条件 / item:xxx / flag:xxx
  @choice:选择描述    玩家选择分支点
  @ending:结局名      标记结局（如 @ending:进入井底结局）
  @clue:线索描述      铺垫线索（如 @clue:井底传来铃铛声）
  @truth:真相描述     关键真相（如 @truth:母亲是井中怨灵）
  @label:标签名       跨文件跳转定位锚点
  @goto:标签名        跳转到指定标签（跨文件跳转）

缩进说明:
  使用缩进来表示父子关系（每级4空格或1个Tab）。
  子节点只有在父节点被访问后才能到达。

跨文件说明:
  目录中的文件按文件名自然排序（chap1.md → chap2.md）。
  一个文件的非结局叶子节点会自动连接到下一个文件的根节点。
  可使用 @label 和 @goto 实现显式跳转。
""")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chaincheck",
        description="多结局因果链检查助手 - 检查恐怖游戏大纲的逻辑完整性",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  chaincheck outline.md                 # 检查单个文件
  chaincheck chapters/                  # 检查整个章节目录
  chaincheck chapters/ --json           # JSON格式输出
  chaincheck outline.md --no-details    # 简洁输出（无选择链/路线片段）
  chaincheck --init-config              # 生成默认配置文件
  chaincheck chapters/ --config my.json # 使用指定配置文件
"""
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="大纲文件或章节目录路径"
    )
    parser.add_argument(
        "--help-syntax",
        action="store_true",
        help="显示完整标记语法说明"
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        help=f"在当前目录生成默认配置文件 ({DEFAULT_CONFIG_FILENAME})"
    )
    parser.add_argument(
        "--config", "-c",
        metavar="FILE",
        help="指定配置文件路径"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出报告"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="静默模式，仅在有问题时输出"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="严格模式，将警告也视为错误（退出码非0）"
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="简洁模式，不显示选择链和路线片段"
    )
    parser.add_argument(
        "--pattern",
        default="*.md",
        help="目录扫描的文件匹配模式（默认: *.md）"
    )
    return parser


def _report_to_json(report: CheckReport) -> dict:
    """将报告转换为 JSON 格式"""
    def _issue_to_dict(issue: Issue) -> dict:
        return {
            "type": issue.issue_type,
            "severity": issue.severity,
            "message": issue.message,
            "line_numbers": issue.line_numbers,
            "source_files": issue.source_files,
            "details": issue.details,
            "suggestion": issue.suggestion,
            "choice_chain": issue.choice_chain,
            "path_segment": issue.path_segment,
        }

    result = {
        "path": report.file_path,
        "is_multi_file": report.is_multi_file,
        "summary": {
            "total_endings": report.total_endings,
            "reachable_endings": report.reachable_endings,
            "total_paths": report.total_paths,
            "issues_count": len(report.issues),
            "errors_count": len(report.errors),
            "warnings_count": len(report.warnings),
            "infos_count": len(report.infos),
        },
        "ending_file_map": report.ending_file_map,
        "file_reports": {
            fp: {
                "issues_count": len(fr.issues),
                "errors_count": fr.errors,
                "warnings_count": fr.warnings,
            }
            for fp, fr in report.file_reports.items()
        },
        "issues": [_issue_to_dict(i) for i in report.issues]
    }
    return result


def main(argv: List[str] | None = None) -> int:
    """命令行入口，返回退出码"""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.help_syntax:
        print_help_syntax()
        return 0

    if args.init_config:
        config_path = Path.cwd() / DEFAULT_CONFIG_FILENAME
        if config_path.exists():
            print(f"[警告] 配置文件已存在: {config_path}")
            response = input("是否覆盖? (y/N): ").strip().lower()
            if response != 'y':
                print("已取消。")
                return 0
        CheckerConfig.create_default(str(config_path))
        print(f"✅ 已生成默认配置文件: {config_path}")
        print("请根据需要修改同义词、关键词和忽略规则。")
        return 0

    if not args.path:
        parser.print_help()
        return 1

    input_path = Path(args.path)
    if not input_path.exists():
        print(f"[错误] 找不到路径: {input_path}", file=sys.stderr)
        return 2

    # 加载配置
    try:
        config = CheckerConfig.load(args.config) if args.config else CheckerConfig.load()
    except Exception as e:
        print(f"[警告] 加载配置文件失败: {e}", file=sys.stderr)
        config = CheckerConfig()

    # 解析大纲
    try:
        if input_path.is_dir():
            outline = parse_chapter_directory(str(input_path), args.pattern)
        else:
            outline = parse_outline(str(input_path))
    except Exception as e:
        print(f"[错误] 解析失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 2

    # 运行检查
    report = run_all_checks(outline, config)

    if args.quiet and not report.issues:
        return 0

    # 输出
    if args.json:
        import io
        # 确保输出 UTF-8 编码
        json_output = json.dumps(_report_to_json(report), ensure_ascii=False, indent=2)
        sys.stdout.reconfigure(encoding='utf-8')
        print(json_output)
    else:
        print(report.format(show_details=not args.no_details))

    # 退出码
    if report.errors:
        return 1
    if args.strict and report.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
