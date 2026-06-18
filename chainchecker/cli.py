"""命令行界面"""

import sys
import argparse
from pathlib import Path
from typing import List

from .parser import parse_outline
from .checkers import run_all_checks, CheckReport


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

缩进说明:
  使用缩进来表示父子关系（每级4空格或1个Tab）。
  子节点只有在父节点被访问后才能到达。

示例:
  第一章 老宅
      进入客厅 @item:+旧钥匙
      @choice:上二楼
          进入卧室
              打开抽屉 @item:+日记
      @choice:去地下室
          发现暗门 @cond:旧钥匙
              @ending:地下密室结局
""")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chaincheck",
        description="多结局因果链检查助手 - 检查恐怖游戏大纲的逻辑完整性",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  chaincheck outline.md\n  chaincheck chapters/story.md --json"
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="大纲文件路径（支持 .md .txt 等文本格式）"
    )
    parser.add_argument(
        "--help-syntax",
        action="store_true",
        help="显示标记语法说明"
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
    return parser


def _report_to_json(report: CheckReport) -> dict:
    return {
        "file_path": report.file_path,
        "summary": {
            "total_endings": report.total_endings,
            "reachable_endings": report.reachable_endings,
            "total_paths": report.total_paths,
            "issues_count": len(report.issues),
            "errors_count": len(report.errors),
            "warnings_count": len(report.warnings),
            "infos_count": len(report.infos),
        },
        "issues": [
            {
                "type": i.issue_type,
                "severity": i.severity,
                "message": i.message,
                "line_numbers": i.line_numbers,
                "details": i.details,
                "suggestion": i.suggestion,
            }
            for i in report.issues
        ]
    }


def main(argv: List[str] | None = None) -> int:
    """命令行入口，返回退出码"""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.help_syntax:
        print_help_syntax()
        return 0

    if not args.file:
        parser.print_help()
        return 1

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"[错误] 找不到文件: {file_path}", file=sys.stderr)
        return 2

    try:
        outline = parse_outline(str(file_path))
    except Exception as e:
        print(f"[错误] 解析文件失败: {e}", file=sys.stderr)
        return 2

    report = run_all_checks(outline)

    if args.quiet and not report.issues:
        return 0

    if args.json:
        import json
        print(json.dumps(_report_to_json(report), ensure_ascii=False, indent=2))
    else:
        print(report.format())

    # 退出码: 有错误返回1，严格模式有警告也返回1
    if report.errors:
        return 1
    if args.strict and report.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
