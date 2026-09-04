import re
from pathlib import Path

CATEGORY = "Thread-Safety"

LAZY_PATTERNS = [
    re.compile(r"\bif\s*\(\s*(\w+)\s*==\s*null\s*\)")
]

DOUBLE_CHECK_RE = re.compile(
    r"\bif\s*\(\s*(\w+)\s*==\s*null\s*\).*?synchronized\s*\(.*?\).*?if\s*\(\s*\1\s*==\s*null\s*\)",
    re.DOTALL,
)

FIELD_RE = re.compile(
    r"^(?:public|protected|private)?\s*(static\s+)?(volatile\s+)?(final\s+)?[\w<>\[\]\.]+(?:\s*<[^>]+>)?\s+(\w+)\s*(?:=[^;]*)?;"
)


def _collect_class_fields(text):
    fields = {}
    depth = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if depth == 1:
            m = FIELD_RE.match(stripped)
            if m:
                name = m.group(4)
                fields[name] = {
                    'is_static': bool(m.group(1)),
                    'is_volatile': bool(m.group(2)),
                    'is_final': bool(m.group(3)),
                    'line': lineno,
                }
        depth += line.count('{') - line.count('}')
    return fields


def scan_file(path):
    text = Path(path).read_text()
    findings = []

    fields = _collect_class_fields(text)

    for pattern in LAZY_PATTERNS:
        for m in pattern.finditer(text):
            field_name = m.group(1)
            field_info = fields.get(field_name)
            if not field_info:
                continue

            if field_info['is_volatile']:
                continue

            line_no = text.count('\n', 0, m.start()) + 1
            if DOUBLE_CHECK_RE.search(text):
                findings.append({
                    'file': str(path),
                    'line': line_no,
                    'category': CATEGORY,
                    'severity': 'High',
                    'reason': 'Unsafe double-checked locking or lazy initialization without volatile',
                    'code_snippet': '\n'.join(_extract_snippet(text, line_no)),
                })
                continue

            findings.append({
                'file': str(path),
                'line': line_no,
                'category': CATEGORY,
                'severity': 'Medium',
                'reason': 'Potential unsafe lazy initialization/singleton pattern without volatile or synchronization',
                'code_snippet': '\n'.join(_extract_snippet(text, line_no)),
            })

    return findings


def _extract_snippet(text, line_no):
    lines = text.splitlines()
    start = max(0, line_no - 3)
    end = min(len(lines), line_no + 2)
    return [f"{i+1}: {lines[i]}" for i in range(start, end)]


def scan_paths(paths):
    results = []
    for p in paths:
        results.extend(scan_file(p))
    return results
