"""Language detection by file extension."""
from __future__ import annotations

import os
from typing import Dict, Optional

# Canonical language ids used across the engine.
JAVA = "java"
PYTHON = "python"
JAVASCRIPT = "javascript"

DEFAULT_EXTENSION_MAP: Dict[str, str] = {
    ".java": JAVA,
    ".py": PYTHON,
    ".pyi": PYTHON,
    ".js": JAVASCRIPT,
    ".jsx": JAVASCRIPT,
    ".mjs": JAVASCRIPT,
    ".cjs": JAVASCRIPT,
    ".ts": JAVASCRIPT,
    ".tsx": JAVASCRIPT,
}

LANGUAGE_LABELS = {
    JAVA: "Java",
    PYTHON: "Python",
    JAVASCRIPT: "JavaScript",
}

MARKDOWN_FENCE = {
    JAVA: "java",
    PYTHON: "python",
    JAVASCRIPT: "javascript",
}


def detect_language(path: str, extension_map: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Return the canonical language id for ``path`` or ``None`` when unsupported."""
    mapping = extension_map or DEFAULT_EXTENSION_MAP
    _, extension = os.path.splitext(path)
    return mapping.get(extension.lower())


def language_label(language: Optional[str]) -> str:
    return LANGUAGE_LABELS.get(language or "", (language or "unknown").title())
