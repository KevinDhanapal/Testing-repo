import re
from pathlib import Path

CATEGORY = "Thread-Safety"

SYNCHRONIZED_BLOCK = re.compile(r"synchronized\s*\(\s*([^\)]+)\s*\)")
LOCK_CALL = re.compile(r"(\w+)\.lock\s*\(")
METHOD_DECL = re.compile(r"(?m)^(?:public|protected|private|static|final|synchronized|\s)+[\w<>,\[\]\s]+\s+\w+\s*\([^\)]*\)\s*\{")


def _ordered_lock_pairs(lock_list):
    pairs = set()
    seen = []
    for lock in lock_list:
        if lock in seen:
            continue
        for prev in seen:
            if prev != lock:
                pairs.add((prev, lock))
        seen.append(lock)
    return pairs


def scan_file(path):
    text = Path(path).read_text()
    lines = text.splitlines()
    findings = []
    methods = []
    current_method = None
    brace_count = 0

    for idx, line in enumerate(lines, start=1):
        if current_method is None and METHOD_DECL.search(line):
            current_method = {
                'start_line': idx,
                'name': line.strip(),
                'locks': [],
            }
            brace_count = line.count('{') - line.count('}')
            continue

        if current_method is not None:
            brace_count += line.count('{') - line.count('}')
            for lock in SYNCHRONIZED_BLOCK.findall(line):
                current_method['locks'].append(lock.strip())
            for lock in LOCK_CALL.findall(line):
                current_method['locks'].append(lock.strip())
            if brace_count <= 0:
                methods.append(current_method)
                current_method = None

    for i, m1 in enumerate(methods):
        pairs1 = _ordered_lock_pairs(m1['locks'])
        if not pairs1:
            continue
        for m2 in methods[i+1:]:
            pairs2 = _ordered_lock_pairs(m2['locks'])
            if not pairs2:
                continue
            for a, b in pairs1:
                if (b, a) in pairs2 and a != b:
                    reason = f"Inconsistent lock acquisition order: {a} then {b} vs {b} then {a}"
                    findings.append({
                        'file': str(path),
                        'line': m1['start_line'],
                        'category': CATEGORY,
                        'severity': 'High',
                        'reason': reason,
                        'code_snippet': '\n'.join(_extract_snippet(lines, m1['start_line'])),
                    })
                    findings.append({
                        'file': str(path),
                        'line': m2['start_line'],
                        'category': CATEGORY,
                        'severity': 'High',
                        'reason': reason,
                        'code_snippet': '\n'.join(_extract_snippet(lines, m2['start_line'])),
                    })
                    break
    return findings


def _extract_snippet(lines, line_no):
    start = max(1, line_no - 1)
    end = min(len(lines), line_no + 2)
    return [f"{i}: {lines[i-1]}" for i in range(start, end+1)]


def scan_paths(paths):
    results = []
    for p in paths:
        results.extend(scan_file(p))
    return results
