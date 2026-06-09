from __future__ import annotations

from typing import Any, Dict, Optional


def _capability_values(capabilities: Optional[Dict[str, Any]], *keys: str) -> list[str]:
    if not isinstance(capabilities, dict):
        return []
    values: list[str] = []
    for key in keys:
        raw_value = capabilities.get(key)
        if raw_value is None:
            continue
        if isinstance(raw_value, dict):
            items = raw_value.values()
        elif isinstance(raw_value, (list, tuple, set)):
            items = raw_value
        else:
            items = [raw_value]
        for item in items:
            text = str(item).strip()
            if text:
                values.append(text.lower())
    return values


def _capability_flag(capabilities: Optional[Dict[str, Any]], *keys: str) -> Optional[bool]:
    if not isinstance(capabilities, dict):
        return None
    for key in keys:
        raw_value = capabilities.get(key)
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, (int, float)) and raw_value in (0, 1):
            return bool(raw_value)
    return None


def _capability_tristate_from_duplex(capabilities: Optional[Dict[str, Any]]) -> Optional[bool]:
    direct = _capability_flag(capabilities, "duplex_supported", "duplex_support")
    if direct is not None:
        return direct

    values = _capability_values(capabilities, "duplex", "duplex_mode")
    if not values:
        return None

    positive_tokens = ("duplex", "longedge", "shortedge", "two-sided", "2-sided")
    negative_tokens = {"none", "simplex", "single"}

    if any(any(token in value for token in positive_tokens) for value in values):
        return True
    if any(value in negative_tokens for value in values):
        return False
    return None


def _capability_tristate_from_color(capabilities: Optional[Dict[str, Any]]) -> Optional[bool]:
    direct = _capability_flag(capabilities, "color_supported", "color_support")
    if direct is not None:
        return direct

    values = _capability_values(capabilities, "color_model", "color_mode", "color")
    if not values:
        return None

    positive_tokens = ("color", "colour", "rgb", "cmyk")
    negative_tokens = ("gray", "grey", "grayscale", "greyscale", "mono", "monochrome", "blackandwhite", "black")

    if any(any(token in value for token in positive_tokens) for value in values):
        return True
    if any(any(token in value for token in negative_tokens) for value in values):
        return False
    return None


def _capability_label(value: Optional[bool]) -> str:
    if value is True:
        return "支持"
    if value is False:
        return "不支持"
    return "未知"


def build_printer_capability_summary(capabilities: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    duplex_supported = _capability_tristate_from_duplex(capabilities)
    color_supported = _capability_tristate_from_color(capabilities)
    return {
        "duplex_supported": duplex_supported,
        "color_supported": color_supported,
        "capability_summary": f"单双面: {_capability_label(duplex_supported)}, 彩色: {_capability_label(color_supported)}",
    }
