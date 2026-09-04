"""File discovery: ignore rules, size/count limits and safe decoding."""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from cragent.engine.config import Config
from cragent.engine.languages import detect_language
from cragent.engine.logging_setup import get_logger
from cragent.engine.models import FileContext, SkippedFile

LOGGER = get_logger("discovery")
REVIEWIGNORE = ".reviewignore"
_BINARY_SNIFF_BYTES = 4096


@dataclass
class FileRef:
    path: str
    rel_path: str
    language: str
    size_bytes: int


class IgnoreSpec:
    """gitignore-flavoured matcher: globs, directory rules and negations."""

    def __init__(self, patterns: Iterable[str]):
        self.rules: List[Tuple[str, bool, bool]] = []
        for raw in patterns:
            pattern = (raw or "").strip()
            if not pattern or pattern.startswith("#"):
                continue
            negated = pattern.startswith("!")
            if negated:
                pattern = pattern[1:].strip()
            directory_only = pattern.endswith("/")
            pattern = pattern.rstrip("/").lstrip("/")
            if pattern:
                self.rules.append((pattern, negated, directory_only))

    @classmethod
    def load(cls, root: str, config: Config) -> "IgnoreSpec":
        patterns = list(config.ignore_patterns)
        ignore_file = os.path.join(root, REVIEWIGNORE) if os.path.isdir(root) else None
        if ignore_file and os.path.exists(ignore_file):
            try:
                with open(ignore_file, "r", encoding="utf-8", errors="replace") as handle:
                    patterns.extend(handle.read().splitlines())
                LOGGER.info("loaded %s", ignore_file)
            except OSError as exc:
                LOGGER.warning("could not read %s: %s", ignore_file, exc)
        return cls(patterns)

    def matches(self, rel_path: str, is_dir: bool = False) -> bool:
        rel_path = rel_path.replace(os.sep, "/").lstrip("./")
        segments = rel_path.split("/")
        ignored = False
        for pattern, negated, directory_only in self.rules:
            if directory_only and not is_dir and pattern not in segments[:-1]:
                continue
            hit = (
                fnmatch.fnmatch(rel_path, pattern)
                or fnmatch.fnmatch(rel_path, f"*/{pattern}")
                or fnmatch.fnmatch(rel_path, f"{pattern}/*")
                or fnmatch.fnmatch(rel_path, f"*/{pattern}/*")
                or any(fnmatch.fnmatch(segment, pattern) for segment in segments)
            )
            if hit:
                ignored = not negated
        return ignored


def is_test_path(rel_path: str, config: Config) -> bool:
    normalized = rel_path.replace(os.sep, "/")
    name = os.path.basename(normalized)
    for pattern in config.test_patterns:
        pattern = pattern.replace(os.sep, "/")
        if pattern.endswith("/"):
            if f"/{pattern}" in f"/{normalized}" or normalized.startswith(pattern):
                return True
        elif fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(normalized, f"*{pattern}*"):
            return True
    return False


def discover_files(
    root: str,
    config: Config,
    explicit_files: Optional[List[str]] = None,
) -> Tuple[List[FileRef], List[SkippedFile], List[str]]:
    """Return (files, skipped, warnings). Never raises for unreadable entries."""
    warnings: List[str] = []
    skipped: List[SkippedFile] = []
    files: List[FileRef] = []
    extension_map = config.extension_map()
    root = os.path.abspath(root)
    base = root if os.path.isdir(root) else os.path.dirname(root)
    ignore = IgnoreSpec.load(base, config)

    def consider(path: str) -> None:
        rel = os.path.relpath(path, base)
        language = detect_language(path, extension_map)
        if language is None:
            skipped.append(SkippedFile(rel, "unsupported file type", routine=True))
            return
        if ignore.matches(rel):
            skipped.append(SkippedFile(rel, "excluded by ignore rules", routine=True))
            return
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            skipped.append(SkippedFile(rel, f"unreadable: {exc}"))
            return
        if size == 0:
            skipped.append(SkippedFile(rel, "empty file"))
            return
        if size > config.max_file_size_bytes:
            skipped.append(SkippedFile(rel, f"exceeds max_file_size_bytes ({size} bytes)"))
            return
        files.append(FileRef(path=path, rel_path=rel.replace(os.sep, "/"), language=language, size_bytes=size))

    if explicit_files:
        for path in explicit_files:
            consider(os.path.abspath(path))
    elif os.path.isfile(root):
        consider(root)
    elif os.path.isdir(root):
        for current, directories, filenames in os.walk(root):
            rel_dir = os.path.relpath(current, base)
            directories[:] = [
                name
                for name in sorted(directories)
                if not ignore.matches(os.path.join(rel_dir, name) if rel_dir != "." else name, is_dir=True)
            ]
            for name in sorted(filenames):
                consider(os.path.join(current, name))
                if len(files) >= config.max_files:
                    break
            if len(files) >= config.max_files:
                break
    else:
        warnings.append(f"path does not exist: {root}")
        return [], skipped, warnings

    if len(files) >= config.max_files:
        message = f"file limit reached ({config.max_files}); remaining files were not scanned"
        LOGGER.warning(message)
        warnings.append(message)

    LOGGER.info("discovered %d files, skipped %d under %s", len(files), len(skipped), root)
    return files, skipped, warnings


def read_context(ref: FileRef, config: Config) -> Tuple[Optional[FileContext], Optional[SkippedFile]]:
    """Read and decode a file, returning a skip record instead of raising."""
    try:
        with open(ref.path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        return None, SkippedFile(ref.rel_path, f"unreadable: {exc}")

    if b"\x00" in raw[:_BINARY_SNIFF_BYTES]:
        return None, SkippedFile(ref.rel_path, "binary content")
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            source = raw.decode("latin-1")
            LOGGER.warning("%s is not valid UTF-8; decoded as latin-1", ref.rel_path)
        except Exception:  # noqa: BLE001
            return None, SkippedFile(ref.rel_path, "not decodable as text")
    if not source.strip():
        return None, SkippedFile(ref.rel_path, "empty file")

    return (
        FileContext(
            path=ref.path,
            rel_path=ref.rel_path,
            language=ref.language,
            source=source,
            size_bytes=ref.size_bytes,
            is_test=is_test_path(ref.rel_path, config),
        ),
        None,
    )


def language_counts(files: Iterable[FileRef]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for ref in files:
        counts[ref.language] = counts.get(ref.language, 0) + 1
    return counts
