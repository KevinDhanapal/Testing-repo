"""Per-language parsers producing one uniform structure for every dimension.

Parsing never raises: on failure the returned :class:`ParsedModule` carries an
``error`` string and empty collections so dimensions degrade gracefully.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List, Optional

from cragent.engine.languages import JAVA, JAVASCRIPT, PYTHON

JAVA_METHOD_PATTERN = re.compile(
    r"(?m)^[ \t]*(?:(?:public|protected|private|static|final|abstract|synchronized|native|"
    r"strictfp|default)\s+)*[\w<>\[\],.?\s]+\s+([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*"
    r"(?:throws\s+[^{]+)?\{"
)
JAVA_CLASS_PATTERN = re.compile(
    r"(?m)^[ \t]*(?:(?:public|protected|private|static|final|abstract|sealed)\s+)*"
    r"(?:class|interface|enum|record)\s+([A-Za-z_]\w*)[^{;]*\{"
)
JAVA_CONTROL_NAMES = {"if", "for", "while", "switch", "catch", "try", "do", "synchronized", "return", "new"}
JAVA_FIELD_PATTERN = re.compile(
    r"(?m)^\s*(?:private|protected|public|static|final|transient|volatile)\s+[^();=]+;"
)

JS_FUNCTION_PATTERNS = (
    re.compile(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*\{"),
    re.compile(
        r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
        r"(?:async\s+)?(?:function\s*\*?\s*)?\(([^)]*)\)\s*(?:=>\s*)?\{"
    ),
    re.compile(r"(?m)^\s{2,}(?:static\s+)?(?:async\s+)?([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*\{"),
)
JS_CLASS_PATTERN = re.compile(r"(?m)^\s*(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][\w$]*)[^{]*\{")
JS_RESERVED = {"if", "for", "while", "switch", "catch", "return", "function", "constructor?"}

BRANCH_PATTERN = re.compile(r"\b(?:if|for|while|catch|case)\b|\?\s|&&|\|\|")


@dataclass
class FunctionInfo:
    name: str
    line: int
    end_line: int
    signature: str
    body: str
    params: List[str] = field(default_factory=list)
    complexity: int = 1
    documented: bool = False
    is_method: bool = False

    @property
    def line_count(self) -> int:
        return self.body.count("\n") + 1

    @property
    def nesting_depth(self) -> int:
        depth = 0
        maximum = 0
        for char in self.body:
            if char == "{":
                depth += 1
                maximum = max(maximum, depth)
            elif char == "}":
                depth = max(0, depth - 1)
        return max(0, maximum - 1)


@dataclass
class ClassInfo:
    name: str
    line: int
    end_line: int
    body: str
    field_count: int = 0
    method_count: int = 0

    @property
    def line_count(self) -> int:
        return self.body.count("\n") + 1


@dataclass
class ParsedModule:
    language: str
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    error: Optional[str] = None
    ast: object = None


def parse(ctx) -> ParsedModule:
    try:
        if ctx.language == PYTHON:
            return _parse_python(ctx.source)
        if ctx.language == JAVA:
            return _parse_java(ctx.source)
        if ctx.language == JAVASCRIPT:
            return _parse_javascript(ctx.source)
    except RecursionError as exc:  # pathological nesting
        return ParsedModule(language=ctx.language, error=f"parse aborted: {exc}")
    except Exception as exc:  # noqa: BLE001 - parsing must never kill a scan
        return ParsedModule(language=ctx.language, error=f"{type(exc).__name__}: {exc}")
    return ParsedModule(language=ctx.language, error="no parser for language")


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------
def _python_complexity(node: ast.AST) -> int:
    score = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With,
                              ast.AsyncWith, ast.Assert, ast.IfExp)):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
    return score


def _parse_python(source: str) -> ParsedModule:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ParsedModule(language=PYTHON, error=f"SyntaxError: line {exc.lineno}: {exc.msg}")

    module = ParsedModule(language=PYTHON, ast=tree)
    lines = source.splitlines()
    method_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_nodes.add(id(child))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            args = node.args
            params = [arg.arg for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)]
            module.functions.append(
                FunctionInfo(
                    name=node.name,
                    line=node.lineno,
                    end_line=end,
                    signature=lines[node.lineno - 1].strip() if node.lineno - 1 < len(lines) else node.name,
                    body="\n".join(lines[node.lineno - 1:end]),
                    params=params,
                    complexity=_python_complexity(node),
                    documented=ast.get_docstring(node) is not None,
                    is_method=id(node) in method_nodes,
                )
            )
        elif isinstance(node, ast.ClassDef):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            methods = [child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
            fields = [child for child in node.body if isinstance(child, (ast.Assign, ast.AnnAssign))]
            module.classes.append(
                ClassInfo(
                    name=node.name,
                    line=node.lineno,
                    end_line=end,
                    body="\n".join(lines[node.lineno - 1:end]),
                    field_count=len(fields),
                    method_count=len(methods),
                )
            )
    return module


# ---------------------------------------------------------------------------
# Brace-balanced languages (Java / JavaScript)
# ---------------------------------------------------------------------------
def _balanced_block(source: str, opening_brace: int) -> Optional[int]:
    """Return the index just past the matching ``}`` for ``opening_brace``."""
    depth = 0
    index = opening_brace
    length = len(source)
    while index < length:
        char = source[index]
        if char in "\"'`":
            quote = char
            index += 1
            while index < length:
                if source[index] == "\\":
                    index += 2
                    continue
                if source[index] == quote:
                    break
                index += 1
        elif char == "/" and index + 1 < length and source[index + 1] == "/":
            newline = source.find("\n", index)
            index = length if newline < 0 else newline
            continue
        elif char == "/" and index + 1 < length and source[index + 1] == "*":
            close = source.find("*/", index + 2)
            index = length if close < 0 else close + 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _split_params(raw: str) -> List[str]:
    raw = raw.strip()
    if not raw:
        return []
    parts, depth, current = [], 0, ""
    for char in raw:
        if char in "<([{":
            depth += 1
        elif char in ">)]}":
            depth -= 1
        if char == "," and depth <= 0:
            parts.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        parts.append(current.strip())
    return [part for part in parts if part]


def _regex_complexity(body: str) -> int:
    return len(BRANCH_PATTERN.findall(body)) + 1


def _has_doc_comment(source: str, start: int) -> bool:
    prefix = source[max(0, start - 400):start].rstrip()
    return prefix.endswith("*/") or prefix.rstrip().endswith("*/\n")


def _parse_java(source: str) -> ParsedModule:
    module = ParsedModule(language=JAVA)
    for match in JAVA_METHOD_PATTERN.finditer(source):
        name = match.group(1)
        if name in JAVA_CONTROL_NAMES:
            continue
        opening = source.find("{", match.start(), match.end() + 1)
        if opening < 0:
            continue
        end = _balanced_block(source, opening)
        if end is None:
            continue
        line = source.count("\n", 0, match.start()) + 1
        module.functions.append(
            FunctionInfo(
                name=name,
                line=line,
                end_line=source.count("\n", 0, end) + 1,
                signature=source[match.start():match.end()].strip(),
                body=source[opening:end],
                params=_split_params(match.group(2)),
                complexity=_regex_complexity(source[opening:end]),
                documented=_has_doc_comment(source, match.start()),
                is_method=True,
            )
        )

    for match in JAVA_CLASS_PATTERN.finditer(source):
        opening = source.find("{", match.start(), match.end() + 1)
        if opening < 0:
            continue
        end = _balanced_block(source, opening)
        if end is None:
            continue
        body = source[opening:end]
        line = source.count("\n", 0, match.start()) + 1
        module.classes.append(
            ClassInfo(
                name=match.group(1),
                line=line,
                end_line=source.count("\n", 0, end) + 1,
                body=body,
                field_count=len(JAVA_FIELD_PATTERN.findall(body)),
                method_count=sum(1 for fn in module.functions if opening <= source.find(fn.signature) < end),
            )
        )
    return module


def _parse_javascript(source: str) -> ParsedModule:
    module = ParsedModule(language=JAVASCRIPT)
    seen = set()
    for pattern in JS_FUNCTION_PATTERNS:
        for match in pattern.finditer(source):
            name = match.group(1)
            if name in JS_RESERVED or name in {"if", "for", "while", "switch", "catch"}:
                continue
            opening = source.find("{", match.start(), match.end() + 1)
            if opening < 0 or opening in seen:
                continue
            end = _balanced_block(source, opening)
            if end is None:
                continue
            seen.add(opening)
            line = source.count("\n", 0, match.start()) + 1
            module.functions.append(
                FunctionInfo(
                    name=name,
                    line=line,
                    end_line=source.count("\n", 0, end) + 1,
                    signature=source[match.start():match.end()].strip(),
                    body=source[opening:end],
                    params=_split_params(match.group(2)),
                    complexity=_regex_complexity(source[opening:end]),
                    documented=_has_doc_comment(source, match.start()),
                    is_method=pattern is JS_FUNCTION_PATTERNS[-1],
                )
            )
    module.functions.sort(key=lambda fn: fn.line)

    for match in JS_CLASS_PATTERN.finditer(source):
        opening = source.find("{", match.start(), match.end() + 1)
        if opening < 0:
            continue
        end = _balanced_block(source, opening)
        if end is None:
            continue
        body = source[opening:end]
        start_line = source.count("\n", 0, match.start()) + 1
        end_line = source.count("\n", 0, end) + 1
        module.classes.append(
            ClassInfo(
                name=match.group(1),
                line=start_line,
                end_line=end_line,
                body=body,
                field_count=len(re.findall(r"(?m)^\s*(?:static\s+)?#?[A-Za-z_$][\w$]*\s*=", body)),
                method_count=sum(1 for fn in module.functions if start_line <= fn.line <= end_line),
            )
        )
    return module


def strip_comments_and_strings(source: str, language: str) -> str:
    """Blank out comments and string literals so regex rules avoid false hits."""
    if language == PYTHON:
        source = re.sub(r"(?s)('''.*?'''|\"\"\".*?\"\"\")", lambda m: " " * len(m.group(0)), source)
        source = re.sub(r"#[^\n]*", "", source)
    else:
        source = re.sub(r"(?s)/\*.*?\*/", lambda m: " " * len(m.group(0)), source)
        source = re.sub(r"//[^\n]*", "", source)
    source = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", source)
    source = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', source)
    return source
