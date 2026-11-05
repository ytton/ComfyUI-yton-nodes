"""Keyframe-only Add Guide integration across all three H3 generators."""

import types
import unittest

from test_h3_omni_variants import VARIANTS, expanded, variant_defaults
from test_h3_video_context import torch, execution, asyncio, DynamicPrompt
from video_context_test.omni_guide import YtonH3AnchorGuide
from comfy_extras.nodes_minimax_h3 import _empty_av_latent


class AddGuideTests(unittest.TestCase):
    def test_schemas_expose_only_keyframes(self):
        for cls in VARIANTS.values():
            schema = cls.INPUT_TYPES()
            self.assertFalse(schema["required"]["enable_add_guide"][1]["default"])
            self.assertEqual(schema["optional"]["anchor_images"][0], "YTON_H3_ANCHORS")
            self.assertTrue(schema["optional"]["anchor_images"][1]["lazy"])
            for name in ("guide_video", "guide_image", "guide_audio", "guide_frame_idx"):
                self.assertNotIn(name, schema["required"] | schema["optional"])

    def test_disabled_guide_has_no_branch(self):
        for cls in VARIANTS.values():
            graph = expanded(cls, anchor_images=["unused", 0])
            self.assertNotIn("main_add_guide", graph)
            self.assertNotIn("high_add_guide", graph)

    def test_context_offset_and_both_passes(self):
        for cls in VARIANTS.values():
            for sampling in ("单采", "二采"):
                for context in (False, True):
                    for extend in (False, True):
                        for mode in ("普通模式", "复刻模式"):
                            with self.subTest(plan=cls.SAMPLING_PLAN, sampling=sampling, context=context, extend=extend, mode=mode):
                                graph = expanded(cls, sampling_mode=sampling, enable_add_guide=True,
                                    anchor_images=["anchors", 1], enable_context=context,
                                    previous_video=["previous", 0], context_auto_extend=extend,
                                    mode=mode, video=["source", 0])
                                stages = ("main", "high") if sampling == "二采" and cls.SAMPLING_PLAN == "traditional" else ("main",)
                                for stage in stages:
                                    guide = graph[f"{stage}_add_guide"]
                                    self.assertEqual(guide["class_type"], "YtonH3AnchorGuide")
                                    self.assertEqual(guide["inputs"]["frame_offset"], 22 if context and extend else 0)
                                    self.assertEqual(guide["inputs"]["anchor_images"], ["anchors", 1])
                                    if context:
                                        self.assertTrue(guide["inputs"]["positive"][0].endswith(f"{stage}_context_add_guide_audio_feather"))

    def test_empty_keyframes_do_not_change_conditions(self):
        positive = [[torch.zeros(1, 1, 1), {}]]
        self.assertIs(YtonH3AnchorGuide.execute(positive, {}, None, []).result[0], positive)
        for cls in VARIANTS.values():
            with self.assertRaisesRegex(ValueError, "achorImages"):
                expanded(cls, enable_add_guide=True)

    def test_native_injection_keeps_separate_frame_positions_and_context(self):
        class Vae:
            def __init__(self): self.images = []
            def encode(self, images):
                self.images.append(images)
                return torch.zeros(1, 24, 1, 2, 2)
        vae = Vae()
        latent, _ = _empty_av_latent(32, 32, 56)
        existing = {"resolved_frame_index": 0, "latent": torch.zeros(1, 24, 7, 2, 2)}
        positive = [[torch.zeros(1, 1, 1), {"minimax_keyframes": [existing]}]]
        anchors = [{"frame": 0, "image": torch.zeros(1, 32, 32, 3)},
                   {"frame": 20, "image": torch.ones(1, 32, 32, 3)}]
        result = YtonH3AnchorGuide.execute(positive, latent, vae, anchors, 22).result[0]
        self.assertEqual([item["resolved_frame_index"] for item in result[0][1]["minimax_keyframes"]], [0, 22, 42])
        self.assertEqual(len(positive[0][1]["minimax_keyframes"]), 1)
        self.assertEqual([len(image) for image in vae.images], [1, 1])
        self.assertEqual(vae.images[0].mean(), 0)
        self.assertEqual(vae.images[1].mean(), 1)
        with self.assertRaisesRegex(ValueError, "outside"):
            YtonH3AnchorGuide.execute(positive, latent, vae, [{"frame": 100, "image": anchors[0]["image"]}])

    def test_lazy_keyframes_resolve_as_one_payload(self):
        anchors = [{"frame": 4, "image": torch.zeros(1, 32, 32, 3)}]
        for cls in VARIANTS.values():
            for enabled in (False, True):
                for payload in (anchors, []):
                    values = variant_defaults(cls, enable_add_guide=enabled, anchor_images=["media", 0])
                    dynprompt = DynamicPrompt({"omni": {"class_type": cls.__name__, "inputs": values}})
                    inputs, _, _ = execution.get_input_data(values, cls, "omni")
                    requested = asyncio.run(execution._async_map_node_over_list("guide-lazy", "omni", cls(), inputs, "check_lazy_status"))[0]
                    self.assertEqual(set(requested), {"anchor_images"} if enabled else set())
                    cache = execution.CacheEntry(ui={}, outputs=([payload],))
                    execution_list = types.SimpleNamespace(get_cache=lambda *args: cache)
                    inputs, _, _ = execution.get_input_data(values, cls, "omni", execution_list=execution_list, dynprompt=dynprompt)
                    result = asyncio.run(execution._async_map_node_over_list("guide-runtime", "omni", cls(), inputs, "generate"))[0]
                    graph = {key.split(".")[-1]: node for key, node in result["expand"].items()}
                    if enabled:
                        self.assertEqual(graph["main_add_guide"]["inputs"]["anchor_images"], ["media", 0])
                    else:
                        self.assertNotIn("main_add_guide", graph)


if __name__ == "__main__":
    unittest.main()
