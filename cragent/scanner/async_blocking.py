import re
from pathlib import Path

CATEGORY = "Thread-Safety"

ASYNC_ANNOTATION = re.compile(r"^\s*@(?:Async|Scheduled|Transactional)\b")
ASYNC_METHOD_HINT = re.compile(r"\b(?:CompletableFuture|CompletionStage|Future|Mono|Flux|Publisher|ExecutorService|@Async)\b")
METHOD_START = re.compile(r"^(?:public|protected|private|static|final|synchronized|\s)+[\w<>,\[\]\s]+\s+\w+\s*\([^\)]*\)\s*\{")
BLOCKING_PATTERNS = {
    'Thread.sleep': re.compile(r"\bThread\.sleep\s*\("),
    'synchronous wait': re.compile(r"\b(?:\.get\s*\(|\.join\s*\(|\.block\s*\(|\.blockLast\s*\()"),
    'JDBC query/update': re.compile(r"\b(?:executeQuery|executeUpdate|prepareStatement|createStatement|execute\s*\()\b"),
    'blocking I/O': re.compile(r"\b(?:FileInputStream|FileOutputStream|Files\.(?:readAllLines|readAllBytes|write|copy|walk|list)|BufferedReader|BufferedWriter|InputStreamReader|OutputStreamWriter|Reader|Writer|new\s+File\()\b"),
}


def scan_file(path):
    text = Path(path).read_text()
    lines = text.splitlines()
    findings = []
    pending_async = False
    in_method = False
    brace_count = 0
    method_start_line = 0
    method_buffer = []

    def flush_method():
        nonlocal in_method, brace_count, method_buffer, method_start_line
        if not in_method:
            return
        body = '\n'.join(method_buffer)
        for label, pattern in BLOCKING_PATTERNS.items():
            for m in pattern.finditer(body):
                line_offset = body[:m.start()].count('\n')
                line_no = method_start_line + line_offset
                snippet = _extract_snippet(lines, line_no)
                findings.append({
                    'file': str(path),
                    'line': line_no,
                    'category': CATEGORY,
                    'severity': 'High' if label in ('Thread.sleep', 'JDBC query/update', 'synchronous wait') else 'Medium',
                    'reason': f'Blocking call "{label}" inside async/reactive method',
                    'code_snippet': '\n'.join(snippet),
                })
        in_method = False
        brace_count = 0
        method_buffer = []
        method_start_line = 0

    for idx, line in enumerate(lines, start=1):
        if ASYNC_ANNOTATION.search(line):
            pending_async = True

        if not in_method and METHOD_START.search(line):
            async_context = pending_async or ASYNC_METHOD_HINT.search(line)
            if async_context:
                in_method = True
                brace_count = line.count('{') - line.count('}')
                method_start_line = idx
                method_buffer = [line]
                pending_async = False
                continue

        if in_method:
            method_buffer.append(line)
            brace_count += line.count('{') - line.count('}')
            if brace_count <= 0:
                flush_method()

    if in_method:
        flush_method()

    return findings


def _extract_snippet(lines, line_no):
    start = max(1, line_no - 2)
    end = min(len(lines), line_no + 1)
    return [f"{i}: {lines[i-1]}" for i in range(start, end+1)]


def scan_paths(paths):
    results = []
    for p in paths:
        results.extend(scan_file(p))
    return results
