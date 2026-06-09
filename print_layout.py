from __future__ import annotations

from typing import Any, Mapping, Optional


PAPER_SIZES_MM = {
    "A3": (297, 420),
    "A4": (210, 297),
    "A5": (148, 210),
    "B5": (176, 250),
    "Letter": (216, 279),
    "Legal": (216, 356),
    "Tabloid": (279, 432),
}

DEFAULT_IMAGE_DPI = 300.0


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_scale_mode(value: Any, default: str = "fit") -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in {"fit", "actual", "fill"} else default


def normalize_paper_size(paper_size: Optional[str]) -> str:
    value = str(paper_size or "").strip()
    if " (横向)" in value or " (landscape)" in value.lower():
        value = value.split(" (")[0].strip()
    return value


def paper_size_px(paper_size: Optional[str], dpi: int = 120) -> Optional[tuple[int, int]]:
    raw = str(paper_size or "").strip()
    is_landscape = (" (横向)" in raw) or ("(landscape)" in raw.lower())
    mm = PAPER_SIZES_MM.get(normalize_paper_size(paper_size))
    if not mm:
        return None
    if is_landscape:
        mm = (mm[1], mm[0])
    return int(mm[0] / 25.4 * dpi), int(mm[1] / 25.4 * dpi)


def paper_size_inches(paper_size: Optional[str]) -> Optional[tuple[float, float]]:
    raw = str(paper_size or "").strip()
    is_landscape = (" (妯悜)" in raw) or ("(landscape)" in raw.lower())
    mm = PAPER_SIZES_MM.get(normalize_paper_size(paper_size))
    if not mm:
        return None
    if is_landscape:
        mm = (mm[1], mm[0])
    return mm[0] / 25.4, mm[1] / 25.4


def image_size_inches(image: Any, default_dpi: float = DEFAULT_IMAGE_DPI) -> tuple[float, float]:
    dpi = getattr(image, "info", {}).get("dpi") or (default_dpi, default_dpi)
    try:
        dpi_x = float(dpi[0])
        dpi_y = float(dpi[1] if len(dpi) > 1 else dpi[0])
    except Exception:
        dpi_x = default_dpi
        dpi_y = default_dpi
    if dpi_x <= 0 or dpi_y <= 0:
        dpi_x = default_dpi
        dpi_y = default_dpi
    return image.width / dpi_x, image.height / dpi_y


def resolve_layout_options(
    options: Optional[Mapping[str, Any]] = None,
    settings: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    opts = dict(options or {})
    defaults = dict(settings or {})

    default_paper_size = defaults.get("default_paper_size") or "A4"
    paper_size = opts.get("paper_size") or opts.get("page_size") or opts.get("size") or default_paper_size
    if paper_size:
        paper_size = str(paper_size).strip()

    default_scale_mode = normalize_scale_mode(defaults.get("default_scale_mode"), "actual")
    scale_mode = normalize_scale_mode(opts.get("scale_mode"), default_scale_mode)

    default_max_upscale = safe_float(defaults.get("default_max_upscale"), 3.0)
    max_upscale = safe_float(opts.get("max_upscale"), default_max_upscale)
    if max_upscale <= 0:
        max_upscale = default_max_upscale if default_max_upscale > 0 else 3.0

    return {
        "paper_size": paper_size,
        "scale_mode": scale_mode,
        "max_upscale": max_upscale,
    }


def compute_scaled_size(
    src_w: int,
    src_h: int,
    dst_w: int,
    dst_h: int,
    scale_mode: str,
    max_upscale: float,
) -> tuple[int, int, float]:
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return 1, 1, 1.0

    fit_scale = min(dst_w / src_w, dst_h / src_h)
    fill_scale = max(dst_w / src_w, dst_h / src_h)

    if scale_mode == "actual":
        scale = min(1.0, fit_scale)
    elif scale_mode == "fill":
        scale = fill_scale
    else:
        scale = fit_scale

    if scale_mode != "actual":
        scale = min(scale, max_upscale)

    scale = max(scale, 1.0 / max(src_w, src_h))
    return max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale))), scale


def compute_physical_fit_rect(
    source_inches: tuple[float, float],
    target_dots: tuple[int, int],
    target_dpi: tuple[float, float],
) -> tuple[int, int, int, int, float]:
    source_w_in, source_h_in = source_inches
    target_w, target_h = target_dots
    dpi_x, dpi_y = target_dpi
    if source_w_in <= 0 or source_h_in <= 0 or target_w <= 0 or target_h <= 0 or dpi_x <= 0 or dpi_y <= 0:
        return 0, 0, 1, 1, 1.0

    natural_w = source_w_in * dpi_x
    natural_h = source_h_in * dpi_y
    scale = min(1.0, target_w / natural_w, target_h / natural_h)
    draw_w = max(1, int(round(natural_w * scale)))
    draw_h = max(1, int(round(natural_h * scale)))
    x = max(0, (target_w - draw_w) // 2)
    y = max(0, (target_h - draw_h) // 2)
    return x, y, draw_w, draw_h, scale
