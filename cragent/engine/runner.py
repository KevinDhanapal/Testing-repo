"""Scan orchestration: discovery -> per-file dimensions -> scoring -> report."""
from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from cragent.engine import SCHEMA_VERSION
from cragent.engine.config import Config
from cragent.engine.discovery import discover_files, language_counts, read_context
from cragent.engine.languages import language_label
from cragent.engine.logging_setup import get_logger, setup_logging
from cragent.engine.models import (
    DimensionResult,
    FileContext,
    Finding,
    ScanError,
    STATUS_ERROR,
    STATUS_FAIL,
    STATUS_NA,
    STATUS_PASS,
    SkippedFile,
)
from cragent.dimensions.base import (
    Dimension,
    NotMeasurable,
    build_dimensions,
    missing_implementations,
)

LOGGER = get_logger("runner")

ProgressCallback = Callable[[int, int, str], None]


def scan(
    path: str = ".",
    config: Optional[Config] = None,
    config_path: Optional[str] = None,
    explicit_files: Optional[List[str]] = None,
    verbose: bool = False,
    progress: Optional[ProgressCallback] = None,
    log_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a full review and return the standardized JSON-serializable report."""
    started = time.time()
    config = config or Config.load(config_path)
    setup_logging(log_file if log_file is not None else config.log_file, config.log_level, verbose)
    LOGGER.info("scan started path=%s config=%s", path, config.source)

    errors: List[ScanError] = []
    for key in missing_implementations(config):
        errors.append(ScanError(stage="registry", path="<config>", dimension=key,
                                message=f"no implementation registered for dimension '{key}'"))

    files, skipped, warnings = discover_files(path, config, explicit_files)
    dimensions = build_dimensions(config)

    contexts: List[FileContext] = []
    findings_by_dimension: Dict[str, List[Finding]] = {dim.key: [] for dim in dimensions}
    error_counts: Dict[str, int] = {dim.key: 0 for dim in dimensions}
    applicable_counts: Dict[str, int] = {dim.key: 0 for dim in dimensions}
    languages_seen: Dict[str, set] = {dim.key: set() for dim in dimensions}
    production_only = set(config.production_only_dimensions)

    def applies(dimension, ctx: FileContext) -> bool:
        if not dimension.supports(ctx.language):
            return False
        return not (ctx.is_test and dimension.key in production_only)

    total = len(files)
    completed = 0
    workers = min(config.max_workers, max(1, total)) if total else 1

    def process(ref):
        ctx, skip = read_context(ref, config)
        if ctx is None:
            return None, skip, [], []
        local_findings: List[Finding] = []
        local_errors: List[ScanError] = []
        parsed = ctx.parsed()
        if parsed.error:
            local_errors.append(ScanError(stage="parse", path=ctx.rel_path, message=parsed.error))
        for dimension in dimensions:
            if not applies(dimension, ctx):
                continue
            try:
                local_findings.extend(dimension.analyze_file(ctx) or [])
            except Exception as exc:  # noqa: BLE001 - isolate each dimension
                LOGGER.error("dimension %s failed on %s: %s", dimension.key, ctx.rel_path, exc)
                local_errors.append(ScanError(stage="dimension", path=ctx.rel_path,
                                              dimension=dimension.key,
                                              message=f"{type(exc).__name__}: {exc}"))
        return ctx, None, local_findings, local_errors

    def absorb(result):
        nonlocal completed
        ctx, skip, local_findings, local_errors = result
        completed += 1
        if skip is not None:
            skipped.append(skip)
        if ctx is not None:
            contexts.append(ctx)
            for dimension in dimensions:
                if applies(dimension, ctx):
                    applicable_counts[dimension.key] += 1
                    languages_seen[dimension.key].add(ctx.language)
            for finding in local_findings:
                findings_by_dimension.setdefault(finding.dimension, []).append(finding)
        for error in local_errors:
            errors.append(error)
            if error.dimension:
                error_counts[error.dimension] = error_counts.get(error.dimension, 0) + 1
        if progress:
            progress(completed, total, ctx.rel_path if ctx else (skip.path if skip else ""))

    if total and workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process, ref): ref for ref in files}
            for future in as_completed(futures):
                ref = futures[future]
                try:
                    absorb(future.result())
                except Exception as exc:  # noqa: BLE001
                    LOGGER.error("worker failed on %s: %s", ref.rel_path, exc)
                    errors.append(ScanError(stage="file", path=ref.rel_path,
                                            message=f"{type(exc).__name__}: {exc}"))
    else:
        for ref in files:
            try:
                absorb(process(ref))
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("worker failed on %s: %s", ref.rel_path, exc)
                errors.append(ScanError(stage="file", path=ref.rel_path,
                                        message=f"{type(exc).__name__}: {exc}"))

    # Cross-file rules.
    for dimension in dimensions:
        supported = [ctx for ctx in contexts if applies(dimension, ctx)]
        if not supported:
            continue
        try:
            findings_by_dimension.setdefault(dimension.key, []).extend(
                dimension.analyze_repo(supported) or []
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("dimension %s repo pass failed: %s", dimension.key, exc)
            errors.append(ScanError(stage="dimension-repo", path="<repository>",
                                    dimension=dimension.key,
                                    message=f"{type(exc).__name__}: {exc}"))
            error_counts[dimension.key] = error_counts.get(dimension.key, 0) + 1

    results = _score_dimensions(dimensions, contexts, findings_by_dimension,
                               applicable_counts, error_counts, languages_seen, config, errors)
    overall = _overall_score(results)
    gate = STATUS_PASS if overall is not None and overall >= config.quality_gate_threshold else STATUS_FAIL
    if overall is None:
        gate = STATUS_NA

    report = {
        "schema_version": SCHEMA_VERSION,
        "scan_id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "path": os.path.abspath(path),
        "config_source": config.source,
        "duration_seconds": round(time.time() - started, 3),
        "overall_score": None if overall is None else round(overall, 1),
        "quality_gate": gate,
        "quality_gate_threshold": config.quality_gate_threshold,
        "dimension_pass_threshold": config.dimension_pass_threshold,
        "dimensions": [result.to_dict() for result in results],
        "files_scanned": len(contexts),
        "files_by_language": {
            language_label(language): count for language, count in language_counts(files).items()
        },
        "files_skipped": [item.to_dict() for item in skipped if not item.routine],
        "files_skipped_count": len(skipped),
        "files_skipped_by_reason": _skip_reason_totals(skipped),
        "total_findings": sum(len(result.findings) for result in results),
        "findings_by_severity": _severity_totals(results),
        "dimensions_passed": sum(1 for result in results if result.status == STATUS_PASS),
        "dimensions_evaluated": sum(
            1 for result in results if result.status in (STATUS_PASS, STATUS_FAIL)
        ),
        "warnings": warnings,
        "errors": [error.to_dict() for error in errors],
    }
    LOGGER.info(
        "scan finished score=%s gate=%s files=%d findings=%d errors=%d",
        report["overall_score"], gate, report["files_scanned"],
        report["total_findings"], len(errors),
    )
    return report


def _score_dimensions(
    dimensions: List[Dimension],
    contexts: List[FileContext],
    findings_by_dimension: Dict[str, List[Finding]],
    applicable_counts: Dict[str, int],
    error_counts: Dict[str, int],
    languages_seen: Dict[str, set],
    config: Config,
    errors: List[ScanError],
) -> List[DimensionResult]:
    present_languages = {ctx.language for ctx in contexts}
    results: List[DimensionResult] = []
    limit = config.max_findings_per_dimension

    for dimension in dimensions:
        findings = sorted(
            findings_by_dimension.get(dimension.key, []),
            key=lambda item: ({"Critical": 0, "Major": 1, "Minor": 2}.get(item.severity, 3),
                              item.file, item.line),
        )
        truncated = len(findings) > limit
        if truncated:
            findings = findings[:limit]

        na_map = {
            language_label(language): dimension.na_reason(language)
            for language in sorted(present_languages)
            if not dimension.supports(language)
        }
        applicable = applicable_counts.get(dimension.key, 0)
        result = DimensionResult(
            key=dimension.key,
            label=dimension.label,
            weight=config.weight(dimension.key),
            status=STATUS_NA,
            findings=findings,
            languages_evaluated=[language_label(item) for item in languages_seen.get(dimension.key, set())],
            na_files=na_map,
        )

        failed = error_counts.get(dimension.key, 0)
        if applicable == 0:
            result.status = STATUS_NA
            if not present_languages:
                result.reason = "no files were scanned"
            elif dimension.key in set(config.production_only_dimensions) and any(
                ctx.is_test and dimension.supports(ctx.language) for ctx in contexts
            ):
                result.reason = (
                    "only test files were scanned; this dimension measures "
                    "production structure and does not apply to test code"
                )
            else:
                result.reason = "no scanned file uses a language supported by this dimension"
        elif failed and failed >= applicable:
            result.status = STATUS_ERROR
            result.reason = f"all {applicable} applicable file(s) failed this check"
        else:
            try:
                production_only = set(config.production_only_dimensions)
                scored_contexts = [
                    ctx for ctx in contexts
                    if dimension.supports(ctx.language)
                    and not (ctx.is_test and dimension.key in production_only)
                ]
                score = dimension.score(findings, scored_contexts)
            except NotMeasurable as exc:
                result.status = STATUS_NA
                result.reason = str(exc)
                results.append(result)
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append(ScanError(stage="score", path="<repository>",
                                        dimension=dimension.key,
                                        message=f"{type(exc).__name__}: {exc}"))
                score = None
            if score is None:
                result.status = STATUS_ERROR
                result.reason = "score could not be computed"
            else:
                result.score = round(float(score), 1)
                result.status = (
                    STATUS_PASS if result.score >= config.dimension_pass_threshold else STATUS_FAIL
                )
                notes = []
                if failed:
                    notes.append(f"{failed} file(s) errored and were excluded")
                if truncated:
                    notes.append(f"findings truncated to {limit}")
                result.reason = "; ".join(notes)
        results.append(result)
    return results


def _overall_score(results: List[DimensionResult]) -> Optional[float]:
    scored = [item for item in results if item.score is not None and item.weight > 0]
    total_weight = sum(item.weight for item in scored)
    if not total_weight:
        return None
    return sum(item.score * item.weight for item in scored) / total_weight


def _severity_totals(results: List[DimensionResult]) -> Dict[str, int]:
    totals = {"Critical": 0, "Major": 0, "Minor": 0}
    for result in results:
        for finding in result.findings:
            totals[finding.severity] = totals.get(finding.severity, 0) + 1
    return totals


def _skip_reason_totals(skipped: List[SkippedFile]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for item in skipped:
        # Collapse reasons that embed per-file detail (sizes, OS errors).
        key = item.reason.split(":")[0].split(" (")[0]
        totals[key] = totals.get(key, 0) + 1
    return dict(sorted(totals.items()))
