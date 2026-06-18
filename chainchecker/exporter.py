"""报告导出器 - 支持 Markdown 和 HTML 格式，按结局/章节/问题类型分组"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict

from .checkers import CheckReport, Issue, FileReport
from .config import CheckerConfig
from .parser import ParsedOutline


def _escape_md(text: str) -> str:
    """转义 Markdown 特殊字符"""
    return (
        text.replace("|", "\\|")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("`", "\\`")
    )


def _severity_icon(severity: str) -> str:
    icons = {"error": "🔴", "warning": "🟡", "info": "🔵"}
    return icons.get(severity, "⚪")


def _severity_label_cn(severity: str) -> str:
    labels = {"error": "错误", "warning": "警告", "info": "提示"}
    return labels.get(severity, severity)


def _group_by_type(issues: List[Issue]) -> Dict[str, List[Issue]]:
    groups: Dict[str, List[Issue]] = defaultdict(list)
    for issue in issues:
        groups[issue.issue_type].append(issue)
    return dict(groups)


def _group_by_file(issues: List[Issue]) -> Dict[str, List[Issue]]:
    groups: Dict[str, List[Issue]] = defaultdict(list)
    for issue in issues:
        for f in issue.source_files or ["(未知文件)"]:
            groups[f].append(issue)
    return dict(groups)


def _format_issue_md(issue: Issue, idx: int, collapsible: bool = True) -> str:
    """格式化单条问题为 Markdown（支持折叠）"""
    icon = _severity_icon(issue.severity)
    sev_label = _severity_label_cn(issue.severity)

    loc_parts = []
    if issue.source_files:
        fnames = ", ".join(Path(f).name for f in issue.source_files)
        loc_parts.append(fnames)
    if issue.line_numbers:
        loc_parts.append("L" + ",".join(str(l) for l in issue.line_numbers))
    location = f" ({', '.join(loc_parts)})" if loc_parts else ""

    header = f"### {idx}. {icon} [{sev_label}] {_escape_md(issue.issue_type)}{location}\n\n"
    header += f"**问题描述**：{_escape_md(issue.message)}\n\n"
    if issue.details:
        header += f"**详细信息**：{_escape_md(issue.details)}\n\n"
    if issue.suggestion:
        header += f"**修复建议**：{_escape_md(issue.suggestion)}\n\n"

    # 折叠部分：选择链 + 路线片段
    has_details = issue.choice_chain or issue.path_segment

    if has_details and collapsible:
        body = "<details>\n"
        body += "<summary>展开查看完整路径上下文（点击展开/收起）</summary>\n\n"
        if issue.choice_chain:
            body += "**玩家选择链**：\n\n"
            body += "```text\n"
            body += issue.choice_chain
            body += "\n```\n\n"
        if issue.path_segment:
            body += "**完整路线片段**：\n\n"
            body += "```text\n"
            body += issue.path_segment
            body += "\n```\n\n"
        body += "</details>\n"
    elif has_details and not collapsible:
        body = ""
        if issue.choice_chain:
            body += "**玩家选择链**：\n\n```text\n" + issue.choice_chain + "\n```\n\n"
        if issue.path_segment:
            body += "**完整路线片段**：\n\n```text\n" + issue.path_segment + "\n```\n\n"
    else:
        body = ""

    return header + body + "\n---\n\n"


def export_markdown(
    report: CheckReport,
    output_path: str,
    group_by: str = "type",  # type, file, ending
    outline: Optional[ParsedOutline] = None,
    config: Optional[CheckerConfig] = None,
) -> None:
    """导出为 Markdown 格式报告

    Args:
        report: 检查报告
        output_path: 输出文件路径
        group_by: 分组方式 - "type"（按问题类型）、"file"（按章节文件）、"ending"（按结局）
        outline: 可选，用于提取更多结局信息
        config: 可选，显示使用的配置摘要
    """
    md_lines: List[str] = []
    md_lines.append("# 因果链检查报告\n")
    md_lines.append(f"> 生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    md_lines.append(f"> 检查对象：`{report.file_path}`\n")

    # ===== 摘要卡片 =====
    md_lines.append("## 📊 总览\n")
    summary_table = "| 指标 | 数值 |\n|------|------|\n"
    summary_table += f"| 结局总数 | {report.total_endings} |\n"
    summary_table += f"| ✅ 可达结局 | {report.reachable_endings} |\n"
    summary_table += f"| ❌ 不可达结局 | {report.total_endings - report.reachable_endings} |\n"
    summary_table += f"| 有效路径数 | {report.total_paths} |\n"
    summary_table += f"| 🔴 错误 | {len(report.errors)} |\n"
    summary_table += f"| 🟡 警告 | {len(report.warnings)} |\n"
    summary_table += f"| 🔵 提示 | {len(report.infos)} |\n"
    summary_table += f"| **问题合计** | **{len(report.issues)}** |\n"
    md_lines.append(summary_table + "\n")

    # ===== 结局跨章节总览 =====
    if report.is_multi_file and report.ending_file_map:
        md_lines.append("## 🗂️ 结局跨章节分布\n")
        ending_table = "| 结局名称 | 涉及章节 | 跨越章节数 |\n|----------|----------|------------|\n"
        for ending in sorted(report.ending_file_map.keys()):
            files = [Path(f).name for f in report.ending_file_map[ending]]
            ending_table += f"| {_escape_md(ending)} | {' → '.join(_escape_md(f) for f in files)} | {len(files)} |\n"
        md_lines.append(ending_table + "\n")

    # ===== 各章节问题汇总表 =====
    if report.is_multi_file and report.file_reports:
        md_lines.append("## 📁 各章节问题汇总\n")
        file_table = "| 章节文件 | 错误 | 警告 | 提示 | 合计 |\n|----------|------|------|------|------|\n"
        for fp in sorted(report.file_reports.keys()):
            fr = report.file_reports[fp]
            fname = Path(fp).name
            errs = sum(1 for i in fr.issues if i.severity == "error")
            warns = sum(1 for i in fr.issues if i.severity == "warning")
            infos = sum(1 for i in fr.issues if i.severity == "info")
            file_table += f"| {_escape_md(fname)} | {errs} | {warns} | {infos} | {len(fr.issues)} |\n"
        md_lines.append(file_table + "\n")

    # ===== 问题详情分组 =====
    md_lines.append("## 🔍 问题详情\n")

    if not report.issues:
        md_lines.append("🎉 **未发现问题，大纲逻辑完整！**\n")
    else:
        issue_groups: Dict[str, List[Issue]] = {}
        group_title_prefix = ""

        if group_by == "type":
            issue_groups = _group_by_type(report.issues)
            group_title_prefix = "类型"
        elif group_by == "file":
            issue_groups = _group_by_file(report.issues)
            group_title_prefix = "章节"
        elif group_by == "ending":
            # 按结局分组：从消息中提取结局名
            ending_groups: Dict[str, List[Issue]] = defaultdict(list)
            for issue in report.issues:
                import re
                m = re.search(r'[「『]([^」』]+)[』」]', issue.message)
                key = m.group(1) if m else issue.issue_type
                ending_groups[key].append(issue)
            issue_groups = dict(ending_groups)
            group_title_prefix = "结局"

        global_idx = 1
        for group_key in sorted(issue_groups.keys()):
            issues_in_group = issue_groups[group_key]
            # 显示分组标题，包含数量
            md_lines.append(f"### 📌 {group_title_prefix}：{_escape_md(group_key)} （{len(issues_in_group)} 条）\n")
            for sub_idx, issue in enumerate(issues_in_group, 1):
                md_lines.append(_format_issue_md(issue, global_idx, collapsible=True))
                global_idx += 1

    # ===== 配置摘要 =====
    if config:
        md_lines.append("## ⚙️ 配置摘要\n")
        md_lines.append("<details><summary>查看本次检查使用的配置（点击展开）</summary>\n\n")
        md_lines.append("```json\n")
        md_lines.append(json.dumps(config.to_dict(), ensure_ascii=False, indent=2))
        md_lines.append("\n```\n\n")
        md_lines.append("</details>\n")

    Path(output_path).write_text("\n".join(md_lines), encoding="utf-8")


def export_html(
    report: CheckReport,
    output_path: str,
    group_by: str = "type",
    outline: Optional[ParsedOutline] = None,
    config: Optional[CheckerConfig] = None,
) -> None:
    """导出为 HTML 格式报告（美观可分享，含交互折叠）"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>因果链检查报告</title>
<style>
  :root {{
    --error-color: #e53935;
    --warning-color: #f9a825;
    --info-color: #1e88e5;
    --success-color: #43a047;
    --bg: #fafafa;
    --card-bg: #ffffff;
    --text: #212121;
    --muted: #757575;
    --border: #e0e0e0;
    --accent: #6a1b9a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    background: var(--bg); color: var(--text);
    margin: 0; padding: 24px; line-height: 1.6;
  }}
  h1 {{ color: var(--accent); border-bottom: 3px solid var(--accent); padding-bottom: 8px; }}
  h2 {{ margin-top: 32px; color: #424242; }}
  h3 {{ color: #616161; }}
  .meta {{ color: var(--muted); font-size: 0.9em; margin-bottom: 24px; }}
  .summary-grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px; margin: 20px 0;
  }}
  .summary-card {{
    background: var(--card-bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }}
  .summary-card .num {{ font-size: 1.8em; font-weight: bold; }}
  .summary-card .label {{ font-size: 0.85em; color: var(--muted); }}
  .num.error {{ color: var(--error-color); }}
  .num.warning {{ color: var(--warning-color); }}
  .num.info {{ color: var(--info-color); }}
  .num.ok {{ color: var(--success-color); }}
  table {{
    width: 100%; border-collapse: collapse; margin: 16px 0;
    background: var(--card-bg); border-radius: 8px; overflow: hidden;
  }}
  th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ background: #f5f5f5; font-weight: 600; }}
  tr:hover td {{ background: #fafafa; }}
  .issue-card {{
    background: var(--card-bg); border: 1px solid var(--border);
    border-left: 4px solid #9e9e9e;
    border-radius: 6px; padding: 16px; margin: 14px 0;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
  }}
  .issue-card.error {{ border-left-color: var(--error-color); }}
  .issue-card.warning {{ border-left-color: var(--warning-color); }}
  .issue-card.info {{ border-left-color: var(--info-color); }}
  .issue-title {{ font-size: 1.1em; font-weight: 600; margin-bottom: 8px; }}
  .issue-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 0.75em; font-weight: 600; margin-right: 8px;
    color: white;
  }}
  .badge-error {{ background: var(--error-color); }}
  .badge-warning {{ background: var(--warning-color); }}
  .badge-info {{ background: var(--info-color); }}
  .issue-loc {{ color: var(--muted); font-size: 0.85em; font-family: monospace; }}
  .issue-field {{ margin: 6px 0; }}
  .issue-field b {{ color: #424242; }}
  details {{ margin-top: 12px; }}
  summary {{
    cursor: pointer; padding: 6px 0; font-weight: 500;
    color: var(--accent); user-select: none;
  }}
  summary:hover {{ text-decoration: underline; }}
  pre {{
    background: #263238; color: #eceff1; padding: 12px;
    border-radius: 6px; overflow-x: auto; font-size: 0.88em;
    white-space: pre-wrap; word-break: break-all;
  }}
  .group-section {{
    background: #fff; border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; margin: 20px 0;
  }}
  .group-title {{
    display: flex; justify-content: space-between; align-items: center;
    font-size: 1.15em; font-weight: 600; color: #424242;
    padding-bottom: 10px; border-bottom: 2px solid #f0f0f0; margin-bottom: 10px;
  }}
  .group-count {{ background: #eeeeee; padding: 2px 10px; border-radius: 10px; font-size: 0.8em; }}
  .success-box {{
    background: #e8f5e9; color: #2e7d32;
    padding: 20px; border-radius: 8px; text-align: center;
    font-size: 1.15em; font-weight: 600; margin: 20px 0;
  }}
  .tab-bar {{ display: flex; gap: 8px; margin: 16px 0; }}
  .tab-btn {{
    padding: 8px 18px; border: 1px solid var(--border);
    background: white; border-radius: 20px; cursor: pointer;
    font-size: 0.9em; transition: all 0.15s;
  }}
  .tab-btn:hover {{ background: #f5f5f5; }}
  .tab-btn.active {{ background: var(--accent); color: white; border-color: var(--accent); }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
  .config-section {{ margin-top: 20px; }}
</style>
</head>
<body>
<h1>🔗 因果链检查报告</h1>
<div class="meta">
  🕒 生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
  &nbsp;|&nbsp; 📂 检查对象：<code>{report.file_path}</code>
  {f"&nbsp;|&nbsp; ⚙️ 使用配置文件" if config else ""}
</div>

<h2>📊 总览</h2>
<div class="summary-grid">
  <div class="summary-card"><div class="num">{report.total_endings}</div><div class="label">结局总数</div></div>
  <div class="summary-card"><div class="num ok">{report.reachable_endings}</div><div class="label">✅ 可达结局</div></div>
  <div class="summary-card"><div class="num error">{report.total_endings - report.reachable_endings}</div><div class="label">❌ 不可达</div></div>
  <div class="summary-card"><div class="num">{report.total_paths}</div><div class="label">有效路径</div></div>
  <div class="summary-card"><div class="num error">{len(report.errors)}</div><div class="label">🔴 错误</div></div>
  <div class="summary-card"><div class="num warning">{len(report.warnings)}</div><div class="label">🟡 警告</div></div>
  <div class="summary-card"><div class="num info">{len(report.infos)}</div><div class="label">🔵 提示</div></div>
  <div class="summary-card"><div class="num" style="color:var(--accent);">{len(report.issues)}</div><div class="label">问题合计</div></div>
</div>
"""

    # 结局跨章节总览
    if report.is_multi_file and report.ending_file_map:
        html += "<h2>🗂️ 结局跨章节分布</h2>\n<table>\n"
        html += "<tr><th>结局名称</th><th>跨越章节</th><th>章节数</th></tr>\n"
        for ending in sorted(report.ending_file_map.keys()):
            files = [Path(f).name for f in report.ending_file_map[ending]]
            chain = " &nbsp;→&nbsp; ".join(f'<code>{f}</code>' for f in files)
            html += f'<tr><td><b>{ending}</b></td><td>{chain}</td><td>{len(files)}</td></tr>\n'
        html += "</table>\n"

    # 各章节问题汇总
    if report.is_multi_file and report.file_reports:
        html += "<h2>📁 各章节问题汇总</h2>\n<table>\n"
        html += "<tr><th>章节文件</th><th>🔴 错误</th><th>🟡 警告</th><th>🔵 提示</th><th>合计</th></tr>\n"
        for fp in sorted(report.file_reports.keys()):
            fr = report.file_reports[fp]
            fname = Path(fp).name
            errs = sum(1 for i in fr.issues if i.severity == "error")
            warns = sum(1 for i in fr.issues if i.severity == "warning")
            infos = sum(1 for i in fr.issues if i.severity == "info")
            html += f'<tr><td><code>{fname}</code></td><td>{errs}</td><td>{warns}</td><td>{infos}</td><td><b>{len(fr.issues)}</b></td></tr>\n'
        html += "</table>\n"

    html += """
<h2>🔍 问题详情</h2>
<div class="tab-bar">
  <button class="tab-btn active" onclick="switchGroup('type')">按问题类型</button>
  <button class="tab-btn" onclick="switchGroup('file')">按章节文件</button>
  <button class="tab-btn" onclick="switchGroup('ending')">按结局</button>
</div>
"""

    if not report.issues:
        html += '<div class="success-box">🎉 未发现问题，大纲逻辑完整！太棒了！</div>\n'
    else:
        # 生成分组内容
        groups_config = {
            "type": _group_by_type(report.issues),
            "file": _group_by_file(report.issues),
        }
        # ending 分组
        import re
        ending_groups: Dict[str, List[Issue]] = defaultdict(list)
        for issue in report.issues:
            m = re.search(r'[「『]([^」』]+)[』」]', issue.message)
            key = m.group(1) if m else issue.issue_type
            ending_groups[key].append(issue)
        groups_config["ending"] = dict(ending_groups)

        for group_name, issue_groups in groups_config.items():
            display = "active" if group_name == "type" else ""
            html += f'<div id="group-{group_name}" class="tab-content {display}">\n'

            global_idx = 1
            for gkey in sorted(issue_groups.keys()):
                issues_g = issue_groups[gkey]
                html += '<div class="group-section">\n'
                gtitle = {
                    "type": "类型",
                    "file": "章节",
                    "ending": "结局",
                }.get(group_name, "分组")
                display_key = gkey
                if group_name == "file":
                    display_key = Path(gkey).name
                html += f'<div class="group-title"><span>📌 {gtitle}：{display_key}</span><span class="group-count">{len(issues_g)} 条</span></div>\n'

                for sub_idx, issue in enumerate(issues_g, 1):
                    badge_class = f"badge-{issue.severity}"
                    badge_text = _severity_label_cn(issue.severity)
                    loc_parts = []
                    if issue.source_files:
                        loc_parts.append(", ".join(Path(f).name for f in issue.source_files))
                    if issue.line_numbers:
                        loc_parts.append("L" + ",".join(str(l) for l in issue.line_numbers))
                    location = f' <span class="issue-loc">({", ".join(loc_parts)})</span>' if loc_parts else ""

                    html += f'<div class="issue-card {issue.severity}">\n'
                    html += f'<div class="issue-title"><span class="issue-badge {badge_class}">{badge_text}</span>{issue.issue_type}{location} · #{global_idx}</div>\n'
                    html += f'<div class="issue-field"><b>问题描述：</b>{issue.message}</div>\n'
                    if issue.details:
                        html += f'<div class="issue-field"><b>详细信息：</b>{issue.details}</div>\n'
                    if issue.suggestion:
                        html += f'<div class="issue-field"><b>修复建议：</b>{issue.suggestion}</div>\n'

                    if issue.choice_chain or issue.path_segment:
                        html += "<details>\n<summary>📜 展开完整路径上下文（点击展开/收起）</summary>\n"
                        if issue.choice_chain:
                            html += f'<p><b>玩家选择链：</b></p>\n<pre>{issue.choice_chain}</pre>\n'
                        if issue.path_segment:
                            html += f'<p><b>完整路线片段：</b></p>\n<pre>{issue.path_segment}</pre>\n'
                        html += "</details>\n"

                    html += "</div>\n"
                    global_idx += 1

                html += "</div>\n"
            html += "</div>\n"

    # 配置摘要
    if config:
        config_json = json.dumps(config.to_dict(), ensure_ascii=False, indent=2)
        html += f"""
<div class="config-section">
  <details>
    <summary>⚙️ 查看本次检查使用的配置（点击展开）</summary>
    <pre>{config_json}</pre>
  </details>
</div>
"""

    html += """
<script>
function switchGroup(name) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('group-' + name).classList.add('active');
  event.target.classList.add('active');
}
</script>
</body>
</html>
"""

    Path(output_path).write_text(html, encoding="utf-8")
