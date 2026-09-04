import os
import re
from pathlib import Path

CATEGORY = "Performance"

LOOP_RE = re.compile(r"\b(?:for|while)\s*\(|\bdo\b")
NEW_RE = re.compile(r"\bnew\s+[A-Za-z_]\w*(?:<[^>]*>)?\s*\(")
HOT_ALLOC_TRIGGER_RE = re.compile(
    r"\b(?:Pattern\.compile|SimpleDateFormat|StringBuilder|StringBuffer|Calendar|new\s+Date|Matcher|split\()\b"
)
DB_CALL_RE = re.compile(
    r"\b(?:executeQuery|executeUpdate|findAll|findBy|queryForList|queryForObject|select|insert|update|delete)\b"
)


def _is_test_file(path):
    return "src/test/java" in str(path).replace(os.sep, '/')


def _is_mapper_file(path):
    normalized = str(path).replace(os.sep, '/').lower()
    return '/mapper/' in normalized or normalized.endswith('mapper.java')


def scan_file(path):
    text = Path(path).read_text()
    lines = text.splitlines()
    findings = []
    in_loop = False
    brace_count = 0
    loop_start = 0
    loop_body = []

    for idx, line in enumerate(lines, start=1):
        if not in_loop and LOOP_RE.search(line):
            in_loop = True
            brace_count = line.count('{') - line.count('}')
            loop_start = idx
            loop_body = [line]
            if brace_count <= 0:
                findings.extend(_analyze_loop(path, loop_start, lines, '\n'.join(loop_body)))
                in_loop = False
            continue

        if in_loop:
            loop_body.append(line)
            brace_count += line.count('{') - line.count('}')
            if brace_count <= 0:
                findings.extend(_analyze_loop(path, loop_start, lines, '\n'.join(loop_body)))
                in_loop = False

    return findings


def _analyze_loop(path, loop_start, lines, body):
    findings = []
    severity = 'Low' if _is_test_file(path) else 'Medium'
    is_mapper = _is_mapper_file(path)

    if DB_CALL_RE.search(body):
        findings.append({
            'file': str(path),
            'line': loop_start,
            'category': CATEGORY,
            'severity': severity,
            'reason': 'Potential N+1 DB/API call inside loop',
            'code_snippet': '\n'.join(_extract_snippet(lines, loop_start)),
        })

    if not is_mapper and NEW_RE.search(body) and HOT_ALLOC_TRIGGER_RE.search(body):
        findings.append({
            'file': str(path),
            'line': loop_start,
            'category': CATEGORY,
            'severity': severity,
            'reason': 'Potential hot-path allocation due to expensive operations inside loop',
            'code_snippet': '\n'.join(_extract_snippet(lines, loop_start)),
        })

    return findings


def _extract_snippet(lines, line_no):
    start = max(1, line_no - 1)
    end = min(len(lines), line_no + 3)
    return [f"{i}: {lines[i-1]}" for i in range(start, end+1)]


def scan_paths(paths):
    results = []
    for p in paths:
        results.extend(scan_file(p))
    return results
