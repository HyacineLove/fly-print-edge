import os
import sys
import unittest

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from print_layout import (
    compute_physical_fit_rect,
    compute_scaled_size,
    image_size_inches,
    paper_size_px,
    resolve_layout_options,
)


class PrintLayoutTests(unittest.TestCase):
    def test_resolve_layout_options_prefers_request_over_settings(self):
        layout = resolve_layout_options(
            {
                "paper_size": "Letter",
                "scale_mode": "actual",
                "max_upscale": "9",
            },
            {
                "default_paper_size": "A4",
                "default_scale_mode": "fill",
                "default_max_upscale": 2,
            },
        )

        self.assertEqual(
            {"paper_size": "Letter", "scale_mode": "actual", "max_upscale": 9.0},
            layout,
        )

    def test_default_scale_mode_is_actual_size_shrink_only(self):
        layout = resolve_layout_options({}, {})

        self.assertEqual("actual", layout["scale_mode"])

    def test_paper_size_px_preserves_landscape_suffix(self):
        portrait = paper_size_px("A4", dpi=120)
        landscape = paper_size_px("A4 (横向)", dpi=120)

        self.assertEqual((992, 1403), portrait)
        self.assertEqual((1403, 992), landscape)

    def test_compute_scaled_size_is_shared_fit_fill_actual_contract(self):
        self.assertEqual((500, 250, 0.5), compute_scaled_size(1000, 500, 500, 500, "fit", 3.0))
        self.assertEqual((1000, 500, 1.0), compute_scaled_size(1000, 500, 500, 500, "fill", 3.0))
        self.assertEqual((500, 250, 0.5), compute_scaled_size(1000, 500, 500, 500, "actual", 3.0))
        self.assertEqual((600, 300, 6.0), compute_scaled_size(100, 50, 1000, 1000, "fit", 6.0))

    def test_physical_fit_rect_does_not_upscale_content_smaller_than_a4(self):
        rect = compute_physical_fit_rect(
            source_inches=(4.0, 6.0),
            target_dots=(2480, 3507),
            target_dpi=(300, 300),
        )

        self.assertEqual((640, 853, 1200, 1800, 1.0), rect)

    def test_physical_fit_rect_shrinks_content_larger_than_a4(self):
        rect = compute_physical_fit_rect(
            source_inches=(11.0, 17.0),
            target_dots=(2480, 3507),
            target_dpi=(300, 300),
        )

        self.assertEqual((105, 0, 2269, 3507, 0.6876470588235294), rect)

    def test_image_size_inches_uses_embedded_dpi_or_fixed_default(self):
        with_dpi = Image.new("RGB", (600, 300), "white")
        with_dpi.info["dpi"] = (100, 100)
        without_dpi = Image.new("RGB", (600, 300), "white")

        self.assertEqual((6.0, 3.0), image_size_inches(with_dpi))
        self.assertEqual((2.0, 1.0), image_size_inches(without_dpi))


if __name__ == "__main__":
    unittest.main()
