"""Configuration loading. Every weight/threshold/limit is data, not code."""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG_FILENAMES = ("config.yaml", "config.yml", "config.json")


class ConfigError(Exception):
    """Raised when a configuration file cannot be read or is invalid."""


def _package_default_path() -> str:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(here, "config.yaml")


def _load_raw(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc

    if path.endswith(".json"):
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ConfigError(f"invalid JSON config {path}: {exc}") from exc
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ConfigError("PyYAML is required to read YAML config files") from exc
    try:
        data = yaml.safe_load(text) or {}
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"invalid YAML config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a mapping in {path}")
    return data


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class Config:
    """Typed accessors over the raw configuration mapping."""

    def __init__(self, data: Dict[str, Any], source: str = "<defaults>"):
        self.data = data
        self.source = source
        self._validate()

    # -- construction -------------------------------------------------
    @classmethod
    def load(cls, path: Optional[str] = None, overrides: Optional[Dict[str, Any]] = None) -> "Config":
        default_path = _package_default_path()
        base = _load_raw(default_path) if os.path.exists(default_path) else {}
        source = default_path

        if path:
            if os.path.isdir(path):
                candidates = [os.path.join(path, name) for name in DEFAULT_CONFIG_FILENAMES]
                path = next((item for item in candidates if os.path.exists(item)), None)
            if path:
                base = _deep_merge(base, _load_raw(path))
                source = path
        if overrides:
            base = _deep_merge(base, overrides)
        return cls(base, source)

    def _validate(self) -> None:
        if not self.dimension_keys():
            raise ConfigError("configuration defines no dimensions")
        for key, spec in self.data.get("dimensions", {}).items():
            weight = spec.get("weight", 0)
            if not isinstance(weight, (int, float)) or weight < 0:
                raise ConfigError(f"dimension '{key}' has an invalid weight: {weight!r}")
        for name, penalty in self.severity_penalties.items():
            if not isinstance(penalty, (int, float)):
                raise ConfigError(f"severity penalty for '{name}' must be numeric")

    # -- accessors ----------------------------------------------------
    @property
    def limits(self) -> Dict[str, Any]:
        return self.data.get("limits", {})

    @property
    def max_files(self) -> int:
        return int(self.limits.get("max_files", 5000))

    @property
    def max_file_size_bytes(self) -> int:
        return int(self.limits.get("max_file_size_bytes", 1024 * 1024))

    @property
    def max_workers(self) -> int:
        return max(1, int(self.limits.get("max_workers", 8)))

    @property
    def max_findings_per_dimension(self) -> int:
        return int(self.limits.get("max_findings_per_dimension", 200))

    @property
    def quality_gate_threshold(self) -> float:
        return float(self.data.get("thresholds", {}).get("quality_gate", 80))

    @property
    def dimension_pass_threshold(self) -> float:
        return float(self.data.get("thresholds", {}).get("dimension_pass", 80))

    @property
    def severity_penalties(self) -> Dict[str, float]:
        return self.data.get("severity_penalties", {"Critical": 15, "Major": 7, "Minor": 2})

    def penalty(self, severity: str) -> float:
        return float(self.severity_penalties.get(severity, 2))

    @property
    def scoring(self) -> Dict[str, Any]:
        return self.data.get("scoring", {}) or {}

    @property
    def scoring_mode(self) -> str:
        """'density' scales the penalty budget with code size; 'absolute' does not."""
        return str(self.scoring.get("mode", "density")).lower()

    @property
    def penalty_budget_per_kloc(self) -> float:
        return float(self.scoring.get("penalty_budget_per_kloc", 30))

    @property
    def min_kloc(self) -> float:
        return float(self.scoring.get("min_kloc", 1.0))

    @property
    def production_only_dimensions(self) -> List[str]:
        """Dimensions whose thresholds describe production structure only."""
        configured = self.data.get("ignore", {}).get("production_only_dimensions")
        if configured is None:
            return ["modularity", "maintainability"]
        return [str(item) for item in configured]

    @property
    def enabled_languages(self) -> List[str]:
        return [
            name
            for name, spec in self.data.get("languages", {}).items()
            if (spec or {}).get("enabled", True)
        ]

    def extension_map(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for name, spec in self.data.get("languages", {}).items():
            if not (spec or {}).get("enabled", True):
                continue
            for extension in (spec or {}).get("extensions", []):
                mapping[str(extension).lower()] = name
        return mapping

    @property
    def ignore_patterns(self) -> List[str]:
        return list(self.data.get("ignore", {}).get("patterns", []))

    @property
    def test_patterns(self) -> List[str]:
        return list(self.data.get("ignore", {}).get("test_patterns", []))

    def dimension_keys(self) -> List[str]:
        return [
            key
            for key, spec in self.data.get("dimensions", {}).items()
            if (spec or {}).get("enabled", True)
        ]

    def weight(self, key: str) -> float:
        return float(self.data.get("dimensions", {}).get(key, {}).get("weight", 0))

    def thresholds(self, key: str) -> Dict[str, Any]:
        return dict(self.data.get("dimensions", {}).get(key, {}).get("thresholds", {}) or {})

    @property
    def log_file(self) -> str:
        return str(self.data.get("logging", {}).get("file", "code-review-agent.log"))

    @property
    def log_level(self) -> str:
        return str(self.data.get("logging", {}).get("level", "INFO"))
