"""Canonical print option values shared by the cloud and Windows print paths."""

from __future__ import annotations

from typing import Any, Dict, Optional


def normalize_duplex(value: Any) -> Optional[str]:
    """Return the local canonical duplex value used by Windows printing."""
    if value is None:
        return None
    raw = str(value).strip().casefold()
    if raw in {"", "default"}:
        return None
    if raw in {"", "default", "none", "simplex", "single", "one-sided", "one_sided", "单面"}:
        return "simplex"
    if raw in {"short", "shortedge", "short_edge", "duplextumble", "short-edge", "短边"}:
        return "shortedge"
    if raw in {
        "duplex",
        "long",
        "longedge",
        "long_edge",
        "duplexnotumble",
        "two-sided",
        "two_sided",
        "双面",
    }:
        return "longedge"
    return None


def normalize_color_mode(value: Any) -> Optional[str]:
    """Return the local canonical color value used by Windows printing."""
    if value is None:
        return None
    raw = str(value).strip().casefold()
    if raw in {"", "default"}:
        return None
    if raw in {"mono", "monochrome", "gray", "grayscale", "grey", "black", "黑白"}:
        return "mono"
    if raw in {"color", "colour", "rgb", "彩色"}:
        return "color"
    return None


def normalize_print_options(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize transport aliases without inventing missing values."""
    normalized = dict(options or {})
    duplex = normalized.get("duplex")
    if duplex is None:
        duplex = normalized.get("duplex_mode")
    canonical_duplex = normalize_duplex(duplex)
    if canonical_duplex is not None:
        normalized["duplex"] = canonical_duplex

    color = normalized.get("color_mode")
    if color is None:
        color = normalized.get("color_model")
    canonical_color = normalize_color_mode(color)
    if canonical_color is not None:
        normalized["color_mode"] = canonical_color
    return normalized


def to_cloud_duplex(value: Any) -> Optional[str]:
    """Map the local value to the cloud schema (single/duplex)."""
    canonical = normalize_duplex(value)
    if canonical is None:
        return None
    return "single" if canonical == "simplex" else "duplex"
