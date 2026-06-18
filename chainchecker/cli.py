"""命令行界面（完整版）- 支持目录检查、配置、路径片段、watch、导出"""

import sys
import argparse
import json
from pathlib import Path
from typing import List

from .parser import parse_outline, parse_chapter_directory
from .checkers import run_all_checks, CheckReport, Issue, save_baseline, load_baseline, apply_baseline, BASELINE_FILENAME
from .config import CheckerConfig, DEFAULT_CONFIG_FILENAME
from .exporter import export_markdown, export_html
from .watcher import run_watch


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
  @entry              标记为独立入口（目录模式从这里也开始）

缩进说明:
  使用缩进来表示父子关系（每级4空格或1个Tab）。
  子节点只有在父节点被访问后才能到达。

跨文件说明:
  目录中的文件按文件名自然排序（chap1.md → chap2.md）。
  默认只从第一章（排序第一个文件）的根节点开始串完整路线。
  其他章节可使用 @entry 标记独立入口（适合支线、闪回）。
  一个文件的非结局叶子节点会自动连接到下一个文件的根节点。
  可使用 @label 和 @goto 实现显式跳转。

配置文件说明 (.chaincheck.json):
  item_synonyms    物品同义词（如 "破损铃铛" <-> "铃铛碎片"）
  truth_keywords   真相关键词列表（增强铺垫匹配）
  ignore_items     一次性道具列表（add->remove 不报冲突）
  ignore_rules     忽略规则（支持通配符 + 到期时间）
  severity_overrides  严重程度覆盖规则
  only_check_endings 只检查某些结局（草稿分批推进）
  only_check_files    只检查某些章节
  draft_mode/strict_mode  草稿/严格模式
""")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chaincheck",
        description="多结局因果链检查助手 - 检查恐怖游戏大纲的逻辑完整性",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  chaincheck outline.md                          检查单个文件
  chaincheck chapters/                           检查整个章节目录
  chaincheck chapters/ --watch                   Watch 模式，边写边检查
  chaincheck chapters/ --watch --draft           Watch 模式 + 草稿模式（参数持续生效）
  chaincheck chapters/ --export-md report.md     导出 Markdown 报告
  chaincheck chapters/ --export-html report.html 导出 HTML 报告发给同事
  chaincheck chapters/ --export-md report.md --review --group ending
                                                 导出审阅版报告，按结局分组
  chaincheck chapters/ --group ending            按结局分组显示问题
  chaincheck outline.md --no-details             简洁输出
  chaincheck --init-config                       生成默认配置文件
  chaincheck chapters/ --config my.json          使用指定配置文件
  chaincheck chapters/ --strict                  严格模式（警告=错误）
  chaincheck chapters/ --draft                   草稿模式（警告降级）
  chaincheck chapters/ --only-ending "*结局A*"   只检查某条结局线
  chaincheck chapters/ --save-baseline           保存当前问题为基线
  chaincheck chapters/ --compare-baseline        对比基线，只看新增问题
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
        "--draft",
        action="store_true",
        help="草稿模式，弱化警告为提示（适合大纲初期）"
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
    parser.add_argument(
        "--group",
        choices=["type", "file", "ending"],
        default="type",
        help="导出报告时的分组方式（默认:按问题类型）"
    )
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Watch 模式：文件变动自动重新检查，只显示变化的问题"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="Watch 模式轮询间隔秒数（默认 1.0）"
    )
    parser.add_argument(
        "--export-md",
        metavar="FILE",
        help="导出 Markdown 格式报告到指定文件"
    )
    parser.add_argument(
        "--export-html",
        metavar="FILE",
        help="导出 HTML 格式报告到指定文件（含交互折叠，适合分享）"
    )
    parser.add_argument(
        "--only-ending",
        action="append",
        default=[],
        metavar="PATTERN",
        help="只检查匹配的结局（可多次指定，支持通配符），适合分批推进"
    )
    parser.add_argument(
        "--only-file",
        action="append",
        default=[],
        metavar="PATTERN",
        help="只检查匹配的文件（可多次指定，支持通配符）"
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="审阅版输出/导出：只显示问题摘要、关联结局、章节和建议，适合发给编剧同事"
    )
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="将当前检查结果保存为基线（后续只把新增问题视为失败）"
    )
    parser.add_argument(
        "--compare-baseline",
        action="store_true",
        help="对比基线模式：只有新增问题会导致退出码非0，旧问题不影响"
    )
    parser.add_argument(
        "--baseline-file",
        metavar="FILE",
        default=None,
        help="指定基线文件路径（默认: .chaincheck.baseline.json）"
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
            "related_endings": issue.related_endings,
            "is_baseline": issue.is_baseline,
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
            "new_issues_count": len(report.new_issues),
            "baseline_issues_count": len(report.baseline_issues),
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
        print("请根据需要修改同义词、关键词、忽略规则和项目级设置。")
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

    # 应用 CLI 覆盖配置
    if args.strict:
        config.strict_mode = True
    if args.draft:
        config.draft_mode = True
    if args.only_ending:
        config.only_check_endings = list(config.only_check_endings) + args.only_ending
    if args.only_file:
        config.only_check_files = list(config.only_check_files) + args.only_file

    # Watch 模式
    if args.watch:
        run_watch(
            target=str(input_path),
            config_path=args.config,
            pattern=args.pattern,
            poll_interval=args.interval,
            show_details=not args.no_details,
            draft_mode=args.draft,
            strict_mode=args.strict,
            only_endings=args.only_ending if args.only_ending else None,
            only_files=args.only_file if args.only_file else None,
        )
        return 0

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

    # ===== 基线功能 =====
    baseline_path = args.baseline_file or str(Path.cwd() / BASELINE_FILENAME)

    if args.save_baseline:
        save_baseline(report, baseline_path)
        print(f"✅ 已保存基线到: {baseline_path}")
        print(f"   共 {len(report.issues)} 条问题已记录为基线")

    if args.compare_baseline:
        baseline_keys = load_baseline(baseline_path)
        if baseline_keys is None:
            print(f"[警告] 未找到基线文件: {baseline_path}", file=sys.stderr)
            print("   使用 --save-baseline 先保存基线")
        else:
            new_count, baseline_count = apply_baseline(report, baseline_keys)
            print(f"📊 基线对比：新增 {new_count} 条，基线旧问题 {baseline_count} 条")
            if new_count == 0:
                print("✅ 没有新增问题！")

    # 导出
    if args.export_md:
        export_markdown(report, args.export_md, args.group, outline, config, review_mode=args.review)
        print(f"✅ Markdown 报告已导出到: {args.export_md}")
    if args.export_html:
        export_html(report, args.export_html, args.group, outline, config, review_mode=args.review)
        print(f"✅ HTML 报告已导出到: {args.export_html}")

    if args.quiet and not report.issues and not args.json:
        return 0

    # 输出
    if args.json:
        # 确保 UTF-8
        json_output = json.dumps(_report_to_json(report), ensure_ascii=False, indent=2)
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
        print(json_output)
    else:
        print(report.format(show_details=not args.no_details))

    # 退出码
    if args.compare_baseline and report.new_issues:
        # 基线模式：只有新增问题导致非零退出码
        if any(i.severity == "error" for i in report.new_issues):
            return 1
        if args.strict and any(i.severity == "warning" for i in report.new_issues):
            return 1
        return 0
    else:
        if report.errors:
            return 1
        if args.strict and report.warnings:
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
