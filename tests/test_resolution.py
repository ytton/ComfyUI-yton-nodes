"""H3 dimensions are ready for AV generation without downstream alignment nodes."""

import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "resolution_node", Path(__file__).resolve().parents[1] / "nodes" / "resolution_node.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.selector = module.YtonResolutionSelector()

    def test_every_h3_preset_is_ready_for_spatial_patching(self):
        for ratio, preset in module.H3_RATIO_PRESETS:
            with self.subTest(ratio=ratio, preset=preset):
                width, height, _, longest, shortest, _, _ = self.selector.get_resolution(
                    "MiniMax H3 (Video)", ratio, preset
                )
                self.assertEqual(width % 32, 0)
                self.assertEqual(height % 32, 0)
                self.assertGreaterEqual(min(width, height), 32)
                self.assertEqual((longest, shortest), (max(width, height), min(width, height)))

    def test_landscape_portrait_and_1080p_outputs(self):
        for ratio, preset, expected in [
            ("16:9", "768p", (1344, 768)),
            ("9:16", "768p", (768, 1344)),
            ("16:9", "1080p", (1920, 1088)),
            ("1:1", "1080p", (1088, 1088)),
        ]:
            with self.subTest(ratio=ratio, preset=preset):
                actual = self.selector.get_resolution("MiniMax H3 (Video)", ratio, preset)
                self.assertEqual(actual[:2], expected)

    def test_h3_custom_and_calculated_dimensions_share_the_same_rule(self):
        custom = self.selector.get_resolution("MiniMax H3 (Video)", "16:9", "768p", 1360, 721)
        self.assertEqual(custom[:2], (1344, 704))
        tiny = self.selector.get_resolution("MiniMax H3 (Video)", "1:1", "768p", 1, 9)
        self.assertEqual(tiny[:2], (32, 32))
        calculated = self.selector.get_resolution("MiniMax H3 (Video)", "5:4", "1080p")
        self.assertEqual(calculated[0] % 32, 0)
        self.assertEqual(calculated[1] % 32, 0)

    def test_normal_dimensions_use_standard_presets_and_custom_sizes(self):
        self.assertEqual(self.selector.get_resolution("Normal (Standard Image/Video)", "16:9", "1080p")[:2], (1920, 1080))
        self.assertEqual(self.selector.get_resolution("Normal (Standard Image/Video)", "16:9", "768p", 1360, 721)[:2], (1360, 721))


class SimpleResolutionTests(unittest.TestCase):
    def test_simple_outputs_match_original_dimensions(self):
        simple = module.YtonResolutionSelectorSimple()
        self.assertEqual(simple.RETURN_NAMES, ("width", "height"))
        self.assertEqual(simple.RETURN_TYPES, ("INT", "INT"))
        for inputs, expected in [
            (("MiniMax H3 (Video)", "16:9", "1080p"), (1920, 1088)),
            (("MiniMax H3 (Video)", "9:16", "768p"), (768, 1344)),
            (("MiniMax H3 (Video)", "16:9", "768p", 1360, 721), (1344, 704)),
            (("Normal (Standard Image/Video)", "16:9", "1080p"), (1920, 1080)),
            (("Normal (Standard Image/Video)", "16:9", "1080p", 1360, 721), (1360, 721)),
        ]:
            with self.subTest(inputs=inputs):
                self.assertEqual(simple.get_resolution(*inputs), expected)


if __name__ == "__main__":
    unittest.main()
