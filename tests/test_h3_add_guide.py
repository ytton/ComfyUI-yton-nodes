"""Native Add Guide integration across the three H3 generators."""

from fractions import Fraction
import types
import unittest

from test_h3_omni_variants import VARIANTS, expanded, variant_defaults
from test_h3_video_context import torch, execution, asyncio, DynamicPrompt
from video_context_test.omni_guide import YtonH3GuideMedia
from comfy_api.latest import InputImpl, Types
from comfy_extras.nodes_minimax_h3 import MiniMaxH3AddGuide, _empty_av_latent


class AddGuideTests(unittest.TestCase):
    def test_all_schemas_expose_optional_media_and_disabled_by_default(self):
        for cls in VARIANTS.values():
            schema = cls.INPUT_TYPES()
            self.assertFalse(schema["required"]["enable_add_guide"][1]["default"])
            self.assertEqual(schema["required"]["guide_frame_idx"][1]["min"], -9999)
            for name, kind in (("guide_video", "VIDEO"), ("guide_image", "IMAGE"), ("guide_audio", "AUDIO")):
                self.assertEqual(schema["optional"][name][0], kind)
                self.assertTrue(schema["optional"][name][1]["lazy"])

    def test_disabled_guide_creates_no_media_or_conditioning_branch(self):
        for cls in VARIANTS.values():
            graph = expanded(cls, guide_video=["unused", 0], guide_image=["unused", 1], guide_audio=["unused", 2])
            self.assertNotIn("guide_media", graph)
            self.assertNotIn("main_add_guide", graph)
            self.assertNotIn("high_add_guide", graph)

    def test_guide_reaches_main_and_traditional_second_pass_and_preserves_context(self):
        for cls in VARIANTS.values():
            for sampling in ("单采", "二采"):
                for context in (False, True):
                    with self.subTest(plan=cls.SAMPLING_PLAN, sampling=sampling, context=context):
                        graph = expanded(cls, sampling_mode=sampling, enable_add_guide=True,
                            guide_video=["guide", 0], guide_frame_idx=-39, enable_context=context,
                            previous_video=["previous", 0])
                        self.assertEqual(graph["guide_media"]["inputs"], {"video": ["guide", 0]})
                        stages = ("main", "high") if sampling == "二采" and cls.SAMPLING_PLAN == "traditional" else ("main",)
                        for stage in stages:
                            guide = graph[f"{stage}_add_guide"]
                            self.assertEqual(guide["class_type"], "MiniMaxH3AddGuide")
                            self.assertEqual(guide["inputs"]["frame_idx"], -39)
                            self.assertEqual(guide["inputs"]["vae"], ["video_vae", 0])
                            self.assertTrue(guide["inputs"]["image"][0].endswith("guide_media"))
                            if context:
                                self.assertTrue(guide["inputs"]["positive"][0].endswith(f"{stage}_context_add_guide_audio_feather"))
                            if cls.SAMPLING_PLAN == "selflift" and sampling == "二采":
                                conditioning = graph["main"]["inputs"]["positive"]
                            else:
                                guider = "guider" if stage == "main" else "high_guider"
                                conditioning = graph[guider]["inputs"]["conditioning"]
                            self.assertTrue(conditioning[0].endswith(f"{stage}_add_guide"))

    def test_replica_can_use_only_the_guide_video_without_a_video_reference(self):
        for cls in VARIANTS.values():
            graph = expanded(cls, mode="复刻模式", enable_add_guide=True, guide_video=["guide", 0])
            self.assertEqual(graph["replica"]["inputs"]["video"], ["guide", 0])
            self.assertNotIn("video", graph["reference"]["inputs"])
            graph = expanded(cls, mode="复刻模式", video=["reference", 0], enable_add_guide=True, guide_video=["guide", 0])
            self.assertEqual(graph["replica"]["inputs"]["video"], ["reference", 0])

    def test_video_resamples_to_24fps_and_explicit_audio_overrides_its_soundtrack(self):
        frames = torch.arange(30).reshape(30, 1, 1, 1).expand(-1, 4, 4, 3).float()
        sound = {"waveform": torch.zeros(1, 1, 48000), "sample_rate": 48000}
        video = InputImpl.VideoFromComponents(Types.VideoComponents(images=frames, audio=sound, frame_rate=Fraction(30)))
        override = {"waveform": torch.ones(1, 1, 48000), "sample_rate": 48000}
        result = YtonH3GuideMedia.execute(video=[None, video], image=[torch.zeros(1, 4, 4, 3)], audio=[override])
        self.assertEqual(len(result.result[0]), 24)
        self.assertEqual(result.result[0][-1, 0, 0, 0], 28)
        self.assertIs(result.result[1], override)
        self.assertIs(YtonH3GuideMedia.execute(video=[video]).result[1], sound)

    def test_image_and_audio_only_and_missing_media(self):
        frames = torch.zeros(22, 32, 32, 3)
        sound = {"waveform": torch.zeros(1, 1, 48000), "sample_rate": 48000}
        self.assertIs(YtonH3GuideMedia.execute(image=[None, frames]).result[0], frames)
        self.assertEqual(YtonH3GuideMedia.execute(audio=[sound]).result, (None, sound))
        with self.assertRaisesRegex(ValueError, "请连接注入"):
            YtonH3GuideMedia.execute(video=[], image=[None])
        for cls in VARIANTS.values():
            with self.assertRaisesRegex(ValueError, "请连接注入"):
                expanded(cls, enable_add_guide=True)

    def test_native_add_guide_encodes_at_the_requested_position_and_preserves_existing_conditions(self):
        class Vae:
            def encode(self, images):
                self.images = images
                return torch.zeros(1, 24, 7, 2, 2)

        vae = Vae()
        latent, length = _empty_av_latent(32, 32, 56)
        existing = {"resolved_frame_index": 0, "latent": torch.zeros(1, 24, 7, 2, 2)}
        positive = [[torch.zeros(1, 1, 1), {"minimax_keyframes": [existing]}]]
        frames = torch.ones(22, 32, 32, 3)
        output = MiniMaxH3AddGuide.execute(positive, latent, -22, vae=vae, image=frames).result[0]
        self.assertEqual(output[0][1]["minimax_keyframes"][1]["resolved_frame_index"], length - 22)
        self.assertIs(output[0][1]["minimax_keyframes"][0], existing)
        self.assertEqual(len(positive[0][1]["minimax_keyframes"]), 1)
        self.assertEqual(vae.images.shape, frames.shape)
        with self.assertRaisesRegex(ValueError, "does not fit"):
            MiniMaxH3AddGuide.execute(positive, latent, 45, vae=vae, image=frames)

    def test_lazy_inputs_and_runtime_preserve_media_links_only_when_enabled(self):
        frames = torch.zeros(1, 32, 32, 3)
        for cls in VARIANTS.values():
            for enabled in (False, True):
                values = variant_defaults(cls, enable_add_guide=enabled, guide_image=["media", 0],
                    guide_video=["media", 1], guide_audio=["media", 2])
                dynprompt = DynamicPrompt({"omni": {"class_type": cls.__name__, "inputs": values}})
                inputs, _, _ = execution.get_input_data(values, cls, "omni")
                requested = asyncio.run(execution._async_map_node_over_list("guide-lazy", "omni", cls(), inputs, "check_lazy_status"))[0]
                self.assertEqual(set(requested), {"guide_video", "guide_image", "guide_audio"} if enabled else set())
                cache = execution.CacheEntry(ui={}, outputs=([frames], [], []))
                execution_list = types.SimpleNamespace(get_cache=lambda *args: cache)
                inputs, _, _ = execution.get_input_data(values, cls, "omni", execution_list=execution_list, dynprompt=dynprompt)
                result = asyncio.run(execution._async_map_node_over_list("guide-runtime", "omni", cls(), inputs, "generate"))[0]
                graph = {key.split(".")[-1]: node for key, node in result["expand"].items()}
                if enabled:
                    self.assertEqual(graph["guide_media"]["inputs"], {"image": ["media", 0]})
                else:
                    self.assertNotIn("guide_media", graph)


if __name__ == "__main__":
    unittest.main()
