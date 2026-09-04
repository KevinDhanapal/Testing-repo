"""Shared helpers for dimension rule sets."""
from __future__ import annotations

import re
from typing import Iterator, List, Tuple

from cragent.engine.languages import JAVA, JAVASCRIPT, PYTHON
from cragent.engine.models import FileContext

LINE_COMMENT_PREFIX = {
    JAVA: ("//", "*", "/*"),
    JAVASCRIPT: ("//", "*", "/*"),
    PYTHON: ("#",),
}


def code_lines(ctx: FileContext) -> Iterator[Tuple[int, str]]:
    """Yield (1-based line number, text) skipping obvious comment lines."""
    prefixes = LINE_COMMENT_PREFIX.get(ctx.language, ("#",))
    for index, text in enumerate(ctx.lines, start=1):
        stripped = text.strip()
        if not stripped or stripped.startswith(prefixes):
            continue
        yield index, text


def clean_source(ctx: FileContext) -> str:
    """Source with comments and string literals blanked, cached per file."""
    from cragent.engine.parsers import strip_comments_and_strings

    return ctx.cached("clean_source", lambda: strip_comments_and_strings(ctx.source, ctx.language))


def loop_blocks(ctx: FileContext) -> List[Tuple[int, str]]:
    """Return (start_line, body_text) for each loop, per language."""
    def build() -> List[Tuple[int, str]]:
        blocks: List[Tuple[int, str]] = []
        if ctx.language == PYTHON:
            lines = ctx.lines
            for index, text in enumerate(lines):
                stripped = text.strip()
                if not (stripped.startswith("for ") or stripped.startswith("while ")):
                    continue
                indent = len(text) - len(text.lstrip())
                body: List[str] = []
                for follow in lines[index + 1:]:
                    if follow.strip() and (len(follow) - len(follow.lstrip())) <= indent:
                        break
                    body.append(follow)
                blocks.append((index + 1, "\n".join(body)))
            return blocks

        from cragent.engine.parsers import _balanced_block

        source = ctx.source
        for match in re.finditer(r"\b(?:for|while)\s*\(", source):
            opening = source.find("{", match.end())
            if opening < 0 or source[match.end():opening].count(";") > 3:
                continue
            end = _balanced_block(source, opening)
            if end is None:
                continue
            blocks.append((source.count("\n", 0, match.start()) + 1, source[opening:end]))
        return blocks

    return ctx.cached("loop_blocks", build)


SECRET_PATTERN = re.compile(
    r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?key|auth[_-]?token|"
    r"private[_-]?key|client[_-]?secret|token)\b\s*[:=]\s*[\"']([^\"']{4,})[\"']"
)
PLACEHOLDER_VALUES = re.compile(
    r"(?i)^(?:\s*|\$\{.*\}|<.*>|\*+|x+|changeme|placeholder|none|null|todo|example|test|dummy|"
    r"your[_-].*|.*\{\{.*\}\}.*|%s|\{\}|env\(.*\)|process\.env.*)$"
)
URL_PATTERN = re.compile(r"(?i)\b(?:https?|ftp|jdbc|mongodb|amqp|redis)://[^\s\"'<>)\]]+")
LOCAL_URL = re.compile(r"(?i)(?:localhost|127\.0\.0\.1|example\.com|schemas?\.|www\.w3\.org|xmlns)")
IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
ABSOLUTE_PATH = re.compile(r"[\"'](?:/(?:usr|home|var|opt|etc|tmp|mnt|data)/[^\"']*|[A-Za-z]:\\\\[^\"']*)[\"']")


def is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_VALUES.match(value.strip()))
