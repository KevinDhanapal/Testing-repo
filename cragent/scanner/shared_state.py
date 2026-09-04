import re
from pathlib import Path

CATEGORY = "Thread-Safety"

FIELD_RE = re.compile(
    r"(?m)^(?:(?:public|protected|private|static|final|transient|volatile)\s+)*"
    r"([A-Za-z_][\w<>\[\]]*(?:\s*<[^>]+>)?(?:\s*\[\s*\])*)\s+"
    r"([A-Za-z_]\w*)\s*(?:=[^;]*)?;"
)
CLASS_RE = re.compile(r"(?m)^\s*(?:public|protected|private)?\s*class\s+([A-Za-z_]\w*)")
METHOD_DEF_RE = re.compile(
    r"(?m)^\s*(?:public|private|protected|static|final|synchronized|abstract|native|strictfp|\s)*"
    r"(?:[\w<>\[\],\s]+?\s+)?([A-Za-z_]\w*)\s*\([^\)]*\)\s*\{"
)
ANNOTATION_RE = re.compile(r"^\s*@([A-Za-z_][\w.]*)")


def _is_model_file(path):
    normalized = str(path).replace("\\", "/")
    return "/src/main/java/" in normalized and "/model/" in normalized


def _is_test_file(path):
    normalized = str(path).replace("\\", "/")
    return "/src/test/java/" in normalized


def _collect_class_fields(text):
    fields = []
    depth = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if depth == 1:
            m = FIELD_RE.match(stripped)
            if m and '(' not in stripped:
                name = m.group(2)
                flags = stripped.split()
                fields.append({
                    'name': name,
                    'is_static': 'static' in flags,
                    'is_volatile': 'volatile' in flags,
                    'is_final': 'final' in flags,
                    'line': lineno,
                })
        depth += line.count('{') - line.count('}')
    return fields


def _collect_methods(lines, class_name):
    methods = []
    pending_annotations = []
    pending_signature = []
    signature_start = None
    current = None
    brace_count = 0

    def flush_signature(signature_lines, annotations, start_line):
        full = ' '.join(signature_lines)
        m = METHOD_DEF_RE.match(full)
        if not m:
            return None
        name = m.group(1)
        if name == class_name:
            kind = 'constructor'
        elif 'PostConstruct' in annotations:
            kind = 'postconstruct'
        elif 'EventListener' in annotations:
            kind = 'eventlistener'
        else:
            kind = 'normal'
        return {'name': name, 'kind': kind, 'start': start_line, 'end': None}

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        ann = ANNOTATION_RE.match(stripped)
        if current is None:
            if ann and not pending_signature:
                pending_annotations.append(ann.group(1))
                continue

            if pending_signature:
                pending_signature.append(stripped)
                brace_count += stripped.count('{') - stripped.count('}')
                if '{' in stripped:
                    current = flush_signature(pending_signature, pending_annotations, signature_start)
                    pending_signature = []
                    pending_annotations = []
                    signature_start = None
                    if current:
                        if brace_count <= 0:
                            current['end'] = lineno
                            methods.append(current)
                            current = None
                        else:
                            methods.append(current)
                continue

            if '(' in stripped and not stripped.endswith(';'):
                pending_signature = [stripped]
                signature_start = lineno
                brace_count = stripped.count('{') - stripped.count('}')
                if '{' in stripped:
                    current = flush_signature(pending_signature, pending_annotations, signature_start)
                    pending_signature = []
                    pending_annotations = []
                    signature_start = None
                    if current:
                        if brace_count <= 0:
                            current['end'] = lineno
                            methods.append(current)
                            current = None
                        else:
                            methods.append(current)
                continue

            if stripped and not stripped.startswith('//'):
                pending_annotations = []
        else:
            brace_count += stripped.count('{') - stripped.count('}')
            if brace_count <= 0:
                current['end'] = lineno
                current = None
    return methods


def _method_for_line(methods, line_no):
    for method in methods:
        if method['start'] <= line_no <= (method['end'] or method['start']):
            return method
    return None


def _is_getter_setter(method_name, field_name):
    if not method_name or not field_name:
        return False
    capital = field_name[0].upper() + field_name[1:]
    return method_name in {f'get{capital}', f'set{capital}', f'is{capital}'}


def scan_file(path):
    if _is_model_file(path) or _is_test_file(path):
        return []

    text = Path(path).read_text()
    lines = text.splitlines()
    findings = []

    fields = _collect_class_fields(text)
    if not fields:
        return findings

    class_match = CLASS_RE.search(text)
    class_name = class_match.group(1) if class_match else None
    methods = _collect_methods(lines, class_name)

    for f in fields:
        if f['is_final'] or f['is_volatile']:
            continue

        access_re = re.compile(rf"\b(?:this\.)?{re.escape(f['name'])}\b")
        assign_re = re.compile(rf"\b(?:this\.)?{re.escape(f['name'])}\s*=")

        reads = []
        writes = []
        for lineno, line in enumerate(lines, start=1):
            if lineno == f['line']:
                continue
            method = _method_for_line(methods, lineno)
            method_name = method['name'] if method else None
            if assign_re.search(line):
                writes.append((lineno, line.strip(), method))
            elif access_re.search(line):
                reads.append((lineno, line.strip(), method))

        if len(reads) + len(writes) < 2:
            continue

        if all(_is_getter_setter(item[2]['name'] if item[2] else None, f['name']) for item in reads + writes):
            continue

        writes_in_constructor = [item for item in writes if item[2] and item[2]['kind'] == 'constructor']
        writes_in_postconstruct = [item for item in writes if item[2] and item[2]['kind'] == 'postconstruct']
        writes_in_eventlistener = [item for item in writes if item[2] and item[2]['kind'] == 'eventlistener']
        writes_elsewhere = [item for item in writes if not item[2] or item[2]['kind'] == 'normal']

        if writes_elsewhere or writes_in_eventlistener:
            shared_access = True
        else:
            shared_access = False

        if not shared_access:
            continue

        severity = 'High' if f['is_static'] else 'Medium'
        if f['name'] == 'client' and re.search(r'WebClient\s+client', text):
            reason = 'singleton stores a request-specific mutable WebClient field; concurrent requests can overwrite shared client state'
        else:
            reason = 'static mutable field accessed without synchronization' if f['is_static'] else 'shared mutable field accessed without synchronization'
        unique_lines = {}
        for ln, code, _ in reads + writes:
            if ln not in unique_lines:
                unique_lines[ln] = code
        snippet = [f"{ln}: {unique_lines[ln]}" for ln in sorted(unique_lines)[:4]]

        findings.append({
            'file': str(path),
            'line': f['line'],
            'category': CATEGORY,
            'severity': severity,
            'reason': reason,
            'code_snippet': '\n'.join(snippet),
        })

    return findings


def scan_paths(paths):
    results = []
    for p in paths:
        results.extend(scan_file(p))
    return results
