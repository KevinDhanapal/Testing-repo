"""Core data model shared by every language and dimension plugin."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CRITICAL = "Critical"
MAJOR = "Major"
MINOR = "Minor"

SEVERITIES = (CRITICAL, MAJOR, MINOR)
SEVERITY_ORDER = {CRITICAL: 0, MAJOR: 1, MINOR: 2}

# Java scanners historically emit High/Medium/Low.
LEGACY_SEVERITY_MAP = {"High": CRITICAL, "Medium": MAJOR, "Low": MINOR}

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NA = "N/A"
STATUS_ERROR = "ERROR"


def normalize_severity(value: Optional[str]) -> str:
    if not value:
        return MINOR
    if value in SEVERITY_ORDER:
        return value
    return LEGACY_SEVERITY_MAP.get(str(value).title(), MINOR)


@dataclass
class Finding:
    """A single rule violation, identical in shape across languages."""

    dimension: str
    rule: str
    file: str
    language: str
    line: int
    severity: str
    issue: str
    fix: str
    snippet: str = ""

    def __post_init__(self) -> None:
        self.severity = normalize_severity(self.severity)
        self.line = max(0, int(self.line or 0))
        self.snippet = (self.snippet or "").strip()[:600]

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class FileContext:
    """One source file plus lazily parsed structure, shared by all dimensions."""

    path: str
    rel_path: str
    language: str
    source: str
    size_bytes: int = 0
    is_test: bool = False
    _cache: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def lines(self) -> List[str]:
        if "lines" not in self._cache:
            self._cache["lines"] = self.source.splitlines()
        return self._cache["lines"]

    @property
    def line_count(self) -> int:
        return len(self.lines)

    def snippet(self, line: int, context: int = 0) -> str:
        """Return source text around a 1-based line number."""
        if line <= 0:
            return ""
        start = max(0, line - 1 - context)
        end = min(len(self.lines), line + context)
        return "\n".join(self.lines[start:end]).strip()

    def parsed(self):
        """Return the language-specific parse result (cached, never raises)."""
        if "parsed" not in self._cache:
            from cragent.engine import parsers

            self._cache["parsed"] = parsers.parse(self)
        return self._cache["parsed"]

    def cached(self, key: str, factory):
        if key not in self._cache:
            self._cache[key] = factory()
        return self._cache[key]


@dataclass
class DimensionResult:
    key: str
    label: str
    weight: float
    status: str
    score: Optional[float] = None
    findings: List[Finding] = field(default_factory=list)
    reason: str = ""
    languages_evaluated: List[str] = field(default_factory=list)
    na_files: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "score": self.score,
            "status": self.status,
            "reason": self.reason,
            "languages_evaluated": sorted(self.languages_evaluated),
            "not_applicable": self.na_files,
            "findings_count": len(self.findings),
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass
class ScanError:
    stage: str
    path: str
    message: str
    dimension: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class SkippedFile:
    path: str
    reason: str
    # Routine skips (non-source, ignored) are aggregated instead of listed per file.
    routine: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "reason": self.reason}
