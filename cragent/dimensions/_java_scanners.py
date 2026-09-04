"""Bridge to the existing Java concurrency/performance scanners.

Results are cached per (path, mtime) so thread_safety and performance do not
re-scan the same file twice, and any scanner failure is isolated.
"""
from __future__ import annotations

import os
from typing import Dict, List, Tuple

from cragent.engine.logging_setup import get_logger

LOGGER = get_logger("java_scanners")
_CACHE: Dict[Tuple[str, float], List[dict]] = {}
_SCANNER_MODULES = (
    "shared_state",
    "lazy_init",
    "async_blocking",
    "executor_service",
    "lock_order",
    "hot_path",
)


def scan_java_file(path: str) -> List[dict]:
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        key = (path, 0.0)
    if key in _CACHE:
        return _CACHE[key]

    findings: List[dict] = []
    for name in _SCANNER_MODULES:
        try:
            module = __import__(f"cragent.scanner.{name}", fromlist=["scan_file"])
            findings.extend(module.scan_file(path) or [])
        except Exception as exc:  # noqa: BLE001 - one scanner must not stop the rest
            LOGGER.warning("java scanner '%s' failed on %s: %s", name, path, exc)
    _CACHE[key] = findings
    return findings


def findings_for_category(path: str, category: str) -> List[dict]:
    return [item for item in scan_java_file(path) if item.get("category") == category]


_FIX_HINTS = (
    ("blocking call", "Move the blocking call off the async path, or use a non-blocking API."),
    ("executor", "Shut the executor down in a finally/@PreDestroy block and bound its queue."),
    ("lock", "Acquire locks in one documented global order to avoid deadlock."),
    ("lazy", "Use a static holder class or make the field volatile with double-checked locking."),
    ("mutable", "Guard the shared field with synchronization, or make it immutable/thread-confined."),
    ("loop", "Hoist the expensive work out of the loop and reuse the instance."),
    ("allocat", "Reuse the object instead of allocating on every iteration."),
)


def fix_hint(reason: str, default: str) -> str:
    lowered = (reason or "").lower()
    for keyword, hint in _FIX_HINTS:
        if keyword in lowered:
            return hint
    return default
