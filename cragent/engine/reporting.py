"""Rendering. Markdown and JSON are both derived from the same report dict."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from cragent.engine.languages import MARKDOWN_FENCE
from cragent.engine.models import STATUS_ERROR, STATUS_NA, STATUS_PASS

STATUS_ICON = {"PASS": "PASS", "FAIL": "FAIL", "N/A": "N/A", "ERROR": "ERROR"}


def to_json(report: Dict[str, Any], indent: int = 2) -> str:
    return json.dumps(report, indent=indent, sort_keys=False, default=str)


def to_markdown(report: Dict[str, Any], max_findings_per_dimension: int = 25) -> str:
    lines: List[str] = []
    score = report.get("overall_score")
    lines.append("# Code Review Report")
    lines.append("")
    lines.append(f"- **Scan ID:** `{report.get('scan_id', '')}`")
    lines.append(f"- **Timestamp:** {report.get('timestamp', '')}")
    lines.append(f"- **Path:** `{report.get('path', '')}`")
    lines.append(f"- **Overall Score:** {'N/A' if score is None else f'{score}/100'}")
    lines.append(f"- **Quality Gate:** **{report.get('quality_gate', 'N/A')}** "
                 f"(threshold {report.get('quality_gate_threshold')})")
    lines.append(f"- **Dimensions Passed:** {report.get('dimensions_passed', 0)}/"
                 f"{report.get('dimensions_evaluated', 0)} evaluated")
    lines.append(f"- **Files Scanned:** {report.get('files_scanned', 0)} "
                 f"({_language_summary(report)}), skipped {report.get('files_skipped_count', 0)}")
    severities = report.get("findings_by_severity", {})
    lines.append(f"- **Findings:** {report.get('total_findings', 0)} "
                 f"(Critical {severities.get('Critical', 0)}, Major {severities.get('Major', 0)}, "
                 f"Minor {severities.get('Minor', 0)})")
    lines.append(f"- **Schema Version:** {report.get('schema_version', '')}")
    lines.append("")

    lines.append("## Dimension Summary")
    lines.append("")
    lines.append("| Dimension | Weight | Score | Status | Findings | Notes |")
    lines.append("| --- | ---: | ---: | :---: | ---: | --- |")
    for dimension in report.get("dimensions", []):
        dimension_score = dimension.get("score")
        note = dimension.get("reason") or ""
        if dimension.get("status") == STATUS_NA and dimension.get("not_applicable"):
            note = note or "; ".join(
                f"{language}: {reason}" for language, reason in dimension["not_applicable"].items()
            )
        lines.append(
            f"| {dimension['label']} | {dimension['weight']:g} | "
            f"{'-' if dimension_score is None else f'{dimension_score:g}'} | "
            f"{STATUS_ICON.get(dimension['status'], dimension['status'])} | "
            f"{dimension.get('findings_count', 0)} | {note} |"
        )
    lines.append("")

    lines.append("## Findings by Dimension")
    lines.append("")
    for dimension in report.get("dimensions", []):
        findings = dimension.get("findings", [])
        if not findings:
            if dimension.get("status") in (STATUS_NA, STATUS_ERROR):
                lines.append(f"### {dimension['label']} — {dimension['status']}")
                lines.append("")
                lines.append(f"{dimension.get('reason') or 'Not evaluated.'}")
                lines.append("")
            continue
        lines.append(f"### {dimension['label']} ({len(findings)} findings)")
        lines.append("")
        lines.append("| File | Language | Line | Severity | Issue | Recommended Fix |")
        lines.append("| --- | --- | ---: | --- | --- | --- |")
        for finding in findings[:max_findings_per_dimension]:
            lines.append(
                f"| `{finding['file']}` | {finding['language']} | {finding['line']} | "
                f"{finding['severity']} | {_escape(finding['issue'])} | {_escape(finding['fix'])} |"
            )
        if len(findings) > max_findings_per_dimension:
            lines.append(f"| ... | | | | {len(findings) - max_findings_per_dimension} more findings | |")
        lines.append("")
        top = findings[0]
        if top.get("snippet"):
            fence = MARKDOWN_FENCE.get(top.get("language", ""), "")
            lines.append(f"<details><summary>Example: {top['file']}:{top['line']}</summary>")
            lines.append("")
            lines.append(f"```{fence}")
            lines.append(top["snippet"])
            lines.append("```")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    warnings = report.get("warnings", [])
    errors = report.get("errors", [])
    if warnings or errors:
        lines.append("## Scan Diagnostics")
        lines.append("")
        for warning in warnings:
            lines.append(f"- WARNING: {warning}")
        for error in errors:
            scope = f" [{error.get('dimension')}]" if error.get("dimension") else ""
            lines.append(f"- ERROR{scope} `{error.get('path')}` ({error.get('stage')}): {error.get('message')}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _language_summary(report: Dict[str, Any]) -> str:
    counts = report.get("files_by_language", {})
    if not counts:
        return "no supported files"
    return ", ".join(f"{language} {count}" for language, count in sorted(counts.items()))


def _escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_report(report: Dict[str, Any], out_path: str) -> str:
    """Write JSON or Markdown based on the output extension."""
    directory = os.path.dirname(os.path.abspath(out_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    content = to_json(report) if out_path.lower().endswith(".json") else to_markdown(report)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return out_path
