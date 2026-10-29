"""Targeted checks for the SelfLift continuation graph and context contract."""

import sys
import types
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
COMFY = PLUGIN.parents[1]
sys.path.insert(0, str(COMFY))
package = types.ModuleType("selflift_test_package")
package.__path__ = [str(PLUGIN / "h3_director")]
sys.modules[package.__name__] = package

from selflift_test_package import omni_selflift_context, omni_selflift_runtime


def defaults(**overrides):
    values = {}
    for name, definition in omni_selflift_runtime.YtonH3SelfLiftOmniGenerate.INPUT_TYPES()["required"].items():
        options = definition[1] if len(definition) > 1 else {}
        if "default" in options:
            values[name] = options["default"]
        elif isinstance(definition[0], list):
            values[name] = definition[0][0]
    values["model_loader"] = ["loader", 0]
    return dict(values, **overrides)


class SelfLiftGraphTests(unittest.TestCase):
    def expand(self, **overrides):
        result = omni_selflift_runtime.YtonH3SelfLiftOmniGenerate().generate(**defaults(**overrides))
        return {key.split(".")[-1]: value for key, value in result["expand"].items()}

    def test_first_segment_has_no_context_or_colour_match(self):
        graph = self.expand()
        self.assertNotIn("previous", graph)
        self.assertNotIn("seamless_color_match", graph)
        self.assertEqual(graph["save_context"]["class_type"], "YtonH3SaveSelfLiftContext")

    def test_continuation_uses_selflift_guides_and_colour_transfer(self):
        graph = self.expand(clip_index=2, sampling_mode="二采", face_refine=True)
        self.assertEqual(graph["previous"]["class_type"], "YtonH3LoadSelfLiftContext")
        self.assertEqual(graph["main_context_add_guide"]["class_type"], "MiniMaxH3AddGuide")
        self.assertEqual(graph["main_ctx_context_first_noise"]["inputs"]["strength"], 0.1)
        self.assertEqual(graph["main_ctx_context_last_exact"]["inputs"]["strength"], 0.0)
        self.assertEqual(graph["high_context_add_guide"]["class_type"], "MiniMaxH3AddGuide")
        self.assertNotIn("source_guide", graph)
        self.assertNotIn("high_source_guide", graph)
        self.assertEqual(graph["seamless_color_match"]["class_type"], "ColorTransfer")
        self.assertEqual(graph["seamless_reference_frame"]["inputs"]["num_frames"], 1)
        self.assertEqual(graph["seamless_color_match"]["inputs"]["method"], "mkl_lab")
        self.assertNotIn("H3ColorMatchSeamlessJoin", {node["class_type"] for node in graph.values()})
        self.assertNotIn("main_context", graph)
        self.assertNotIn("high_context", graph)

    def test_context_contract_is_separate(self):
        self.assertEqual(omni_selflift_context.CONTRACT, "yton-h3-selflift-context-v1")
        self.assertEqual(
            omni_selflift_runtime.YtonH3SelfLiftOmniGenerate.INPUT_TYPES()["required"]["latent_path"][1]["default"],
            "h3_context/SelfLift无缝接续",
        )
        self.assertEqual(omni_selflift_runtime.YtonH3SelfLiftOmniGenerate.INPUT_TYPES()["optional"]["video"][0], "VIDEO")
        self.assertEqual(omni_selflift_runtime.YtonH3SelfLiftOmniGenerate.INPUT_TYPES()["optional"]["audio"][0], "AUDIO")


if __name__ == "__main__":
    unittest.main()
