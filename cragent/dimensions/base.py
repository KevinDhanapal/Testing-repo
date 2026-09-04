"""Pluggable dimension framework.

A dimension subclasses :class:`Dimension`, declares which languages it supports
and implements ``analyze_file`` (per file) and/or ``analyze_repo`` (cross-file).
Subclasses register themselves automatically, so adding a dimension or a
language rule set never requires editing the engine.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Type

from cragent.engine.config import Config
from cragent.engine.languages import JAVA, JAVASCRIPT, PYTHON, language_label
from cragent.engine.models import Finding, FileContext

ALL_LANGUAGES = (JAVA, PYTHON, JAVASCRIPT)

REGISTRY: Dict[str, Type["Dimension"]] = {}


class NotMeasurable(Exception):
    """Raised by a dimension when it has no evidence to score on.

    The engine reports the dimension as N/A with this reason rather than
    inventing a score from a weak proxy signal.
    """


class Dimension:
    key: str = ""
    label: str = ""
    supported_languages: tuple = ALL_LANGUAGES
    na_reasons: Dict[str, str] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.key:
            REGISTRY[cls.key] = cls

    def __init__(self, config: Config):
        self.config = config
        self.thresholds = config.thresholds(self.key)

    # -- capability ---------------------------------------------------
    def supports(self, language: str) -> bool:
        return language in self.supported_languages

    def na_reason(self, language: str) -> str:
        return self.na_reasons.get(
            language, f"{self.label} rules are not defined for {language_label(language)}"
        )

    # -- analysis hooks -----------------------------------------------
    def analyze_file(self, ctx: FileContext) -> List[Finding]:
        """Per-file rules. Dispatches to ``rules_<language>`` when present."""
        handler: Optional[Callable[[FileContext], List[Finding]]] = getattr(
            self, f"rules_{ctx.language}", None
        )
        if handler is None:
            return []
        return handler(ctx) or []

    def analyze_repo(self, contexts: List[FileContext]) -> List[Finding]:
        """Cross-file rules (duplication, test coverage ratios, ...)."""
        return []

    # -- scoring ------------------------------------------------------
    def score(self, findings: List[Finding], contexts: List[FileContext]) -> Optional[float]:
        """Penalties scaled against a size-aware budget so large repos are not floored at 0."""
        penalty = sum(self.config.penalty(finding.severity) for finding in findings)
        if self.config.scoring_mode != "density":
            return max(0.0, min(100.0, 100.0 - penalty))
        kloc = max(sum(ctx.line_count for ctx in contexts) / 1000.0, self.config.min_kloc)
        budget = self.config.penalty_budget_per_kloc * kloc
        if budget <= 0:
            return max(0.0, min(100.0, 100.0 - penalty))
        return max(0.0, min(100.0, 100.0 - 100.0 * penalty / budget))

    # -- helpers for rule authors -------------------------------------
    def finding(
        self,
        ctx: FileContext,
        rule: str,
        line: int,
        severity: str,
        issue: str,
        fix: str,
        snippet: str = "",
    ) -> Finding:
        return Finding(
            dimension=self.key,
            rule=rule,
            file=ctx.rel_path,
            language=ctx.language,
            line=line,
            severity=severity,
            issue=issue,
            fix=fix,
            snippet=snippet or ctx.snippet(line),
        )

    def threshold(self, name: str, default):
        value = self.thresholds.get(name, default)
        return value if value is not None else default


def build_dimensions(config: Config) -> List[Dimension]:
    """Instantiate every enabled dimension in configuration order."""
    from cragent import dimensions as _  # noqa: F401  ensures modules are imported

    built: List[Dimension] = []
    for key in config.dimension_keys():
        implementation = REGISTRY.get(key)
        if implementation is None:
            continue
        built.append(implementation(config))
    return built


def missing_implementations(config: Config) -> List[str]:
    from cragent import dimensions as _  # noqa: F401

    return [key for key in config.dimension_keys() if key not in REGISTRY]
