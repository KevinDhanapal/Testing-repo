import re
from pathlib import Path

CATEGORY = "Thread-Safety"

EXECUTOR_NEW = re.compile(
    r"\b(?:new\s+(?:ThreadPoolExecutor|ScheduledThreadPoolExecutor|ForkJoinPool|ExecutorService)|Executors\.(?:newFixedThreadPool|newCachedThreadPool|newSingleThreadExecutor|newScheduledThreadPool|newWorkStealingPool))\b"
)
EXECUTOR_SUBMIT = re.compile(r"\b(?:submit|execute|schedule|submitAsync)\s*\(")
SHUTDOWN_RE = re.compile(r"\b(?:shutdown|shutdownNow|awaitTermination|close)\s*\(")
TRY_WITH_RESOURCES = re.compile(r"\btry\s*\([^\)]*(?:ExecutorService|ThreadPoolExecutor|ScheduledExecutorService)[^\)]*\)")
METHOD_START = re.compile(r"^(?:public|protected|private|static|final|synchronized|\s)+[\w<>,\[\]\s]+\s+\w+\s*\([^\)]*\)\s*\{")


def scan_file(path):
    text = Path(path).read_text()
    lines = text.splitlines()
    findings = []
    in_method = False
    brace_count = 0
    method_start = 0
    method_buffer = []

    def flush_method():
        nonlocal in_method, brace_count, method_buffer, method_start
        if not in_method:
            return
        body = '\n'.join(method_buffer)
        if not TRY_WITH_RESOURCES.search(body):
            creation_lines = [idx for idx, line in enumerate(method_buffer, start=method_start) if EXECUTOR_NEW.search(line)]
            if creation_lines and not SHUTDOWN_RE.search(body):
                idx = creation_lines[0]
                findings.append({
                    'file': str(path),
                    'line': idx,
                    'category': CATEGORY,
                    'severity': 'Medium',
                    'reason': 'ExecutorService created without matching shutdown/termination in the same method',
                    'code_snippet': '\n'.join(_extract_snippet(lines, idx)),
                })
        for idx, line in enumerate(method_buffer, start=method_start):
            if EXECUTOR_SUBMIT.search(line) and ('Runnable' in line or '() ->' in line or '->' in line):
                body_segment = _collect_block(lines, idx)
                if body_segment and 'catch' not in body_segment:
                    findings.append({
                        'file': str(path),
                        'line': idx,
                        'category': CATEGORY,
                        'severity': 'Medium',
                        'reason': 'Potential fire-and-forget task may swallow exceptions',
                        'code_snippet': '\n'.join(_extract_snippet(lines, idx)),
                    })
        in_method = False
        brace_count = 0
        method_buffer = []
        method_start = 0

    for idx, line in enumerate(lines, start=1):
        if not in_method and METHOD_START.search(line):
            in_method = True
            brace_count = line.count('{') - line.count('}')
            method_start = idx
            method_buffer = [line]
            if brace_count <= 0:
                flush_method()
                continue
            continue

        if in_method:
            method_buffer.append(line)
            brace_count += line.count('{') - line.count('}')
            if brace_count <= 0:
                flush_method()

    if in_method:
        flush_method()

    return findings


def _collect_block(lines, start_idx):
    brace_count = 0
    body_lines = []
    for line in lines[start_idx-1:]:
        brace_count += line.count('{') - line.count('}')
        body_lines.append(line)
        if brace_count <= 0 and '{' in line:
            break
    return '\n'.join(body_lines)


def _extract_snippet(lines, line_no):
    start = max(1, line_no - 2)
    end = min(len(lines), line_no + 2)
    return [f"{i}: {lines[i-1]}" for i in range(start, end+1)]


def scan_paths(paths):
    results = []
    for p in paths:
        results.extend(scan_file(p))
    return results
