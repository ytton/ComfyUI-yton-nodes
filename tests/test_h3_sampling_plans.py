"""CPU Film 2× graph contracts and installed upscaler input checks."""

import importlib.util
import sys
import types
import unittest

from test_h3_video_context import PLUGIN, expanded, defaults, torch, YtonH3VideoContextOmniGenerate
from video_context_test.omni_sampling import FILM_MODEL, sampling_dimensions


class FilmSamplingTests(unittest.TestCase):
    def test_schema_defaults_to_film_second_pass_with_fixed_dimensions(self):
        required = YtonH3VideoContextOmniGenerate.INPUT_TYPES()["required"]
        self.assertEqual(required["sampling_mode"][1]["default"], "二采")
        self.assertEqual(required["film_model"][0], [FILM_MODEL])
        for name in ("sampling_plan", "first_pass_scale", "upscale_model",
                     "selflift_transition_step", "selflift_rho", "selflift_highres_tiling"):
            self.assertNotIn(name, required)

    def test_film_uses_half_dimensions_clean_endpoint_and_one_renoise(self):
        for width, height in ((1920, 1088), (1344, 768), (1280, 704)):
            with self.subTest(width=width, height=height):
                graph, _ = expanded(width=width, height=height, second_model=["custom_model", 0])
                self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]),
                                 (width // 2, height // 2))
                self.assertEqual((graph["high_reference"]["inputs"]["width"], graph["high_reference"]["inputs"]["height"]),
                                 (width, height))
                upscale = graph["upscale"]
                self.assertEqual(upscale["class_type"], "MiniMaxH3LatentUpscaleCombined")
                self.assertEqual(upscale["inputs"]["learned_model"], FILM_MODEL)
                self.assertEqual(upscale["inputs"]["samples"][1], 1)
                self.assertTrue(upscale["inputs"]["samples"][0].endswith("main"))
                self.assertEqual(upscale["inputs"]["model"], ["custom_model", 0])
                self.assertEqual(upscale["inputs"]["audio_denoise"], 0)
                self.assertEqual(graph["film_disable_noise"]["class_type"], "DisableNoise")
                self.assertTrue(graph["high_sample"]["inputs"]["noise"][0].endswith("film_disable_noise"))
                self.assertEqual(graph["high_sample"]["inputs"]["sigmas"], upscale["inputs"]["sigmas"])
                self.assertNotIn("positive", upscale["inputs"])

    def test_film_custom_sigma_is_shared_by_renoise_and_sampling(self):
        graph, _ = expanded(second_sigma_values=["custom_sigma", 0])
        self.assertNotIn("high_sigmas", graph)
        self.assertEqual(graph["upscale"]["inputs"]["sigmas"], ["custom_sigma", 0])
        self.assertEqual(graph["high_sample"]["inputs"]["sigmas"], ["custom_sigma", 0])

    def test_second_sigma_text_is_used_for_both_operations(self):
        graph, _ = expanded(second_sigma_values="0.35, 0.175, 0")
        self.assertEqual(graph["high_sigmas"]["inputs"]["sigmas"], "0.35, 0.175, 0")
        self.assertEqual(graph["upscale"]["inputs"]["sigmas"], graph["high_sample"]["inputs"]["sigmas"])

    def test_second_sigma_link_is_only_evaluated_in_second_pass(self):
        node = YtonH3VideoContextOmniGenerate()
        self.assertNotIn("second_sigmas", node.INPUT_TYPES()["optional"])
        self.assertEqual(node.INPUT_TYPES()["required"]["second_sigma_values"][0], "STRING,SIGMAS")
        self.assertTrue(node.INPUT_TYPES()["required"]["second_sigma_values"][1]["lazy"])
        for mode in ("单采", "二采"):
            inputs = {name: [value] for name, value in defaults(sampling_mode=mode).items()}
            inputs["second_sigma_values"] = [None]
            self.assertEqual("second_sigma_values" in node.check_lazy_status(**inputs), mode == "二采")

    def test_tensor_schedule_reaches_film_and_sampler_unchanged(self):
        sigmas = torch.tensor([0.35, 0.175, 0.0])
        graph, _ = expanded(second_sigma_values=sigmas)
        self.assertIs(graph["upscale"]["inputs"]["sigmas"], sigmas)
        self.assertIs(graph["high_sample"]["inputs"]["sigmas"], sigmas)

    def test_face_sigma_accepts_text_or_empty_for_scheduler(self):
        graph, _ = expanded(face_refine=True, face_sigmas="0.615, 0")
        self.assertEqual(graph["face_sigmas"]["inputs"]["sigmas"], "0.615, 0")
        self.assertTrue(graph["face_0_sample"]["inputs"]["sigmas"][0].endswith("face_sigmas"))
        self.assertNotIn("face_0_schedule", graph)
        graph, _ = expanded(face_refine=True, face_sigmas="")
        self.assertIn("face_0_schedule", graph)

    def test_face_sigma_link_is_lazy_while_face_refine_is_off(self):
        node = YtonH3VideoContextOmniGenerate()
        for enabled in (False, True):
            inputs = {name: [value] for name, value in defaults(face_refine=enabled).items()}
            inputs["face_sigmas"] = [None]
            self.assertEqual("face_sigmas" in node.check_lazy_status(**inputs), enabled)

    def test_video_context_and_face_refine_share_final_output(self):
        graph, _ = expanded(duration=7.5, enable_context=True,
                            previous_video=["previous_video", 0], face_refine=True)
        self.assertEqual(graph["reference"]["inputs"]["length"], 209)
        self.assertEqual(graph["trim"]["inputs"]["head_trim_frames"], 22)
        self.assertEqual(graph["trim"]["inputs"]["tail_trim_frames"], 7)
        for name in ("main_context_add_guide", "high_context_add_guide", "face_0_sample", "seamless_color_match"):
            self.assertIn(name, graph)

    def test_single_pass_uses_final_size_directly(self):
        graph, _ = expanded(sampling_mode="单采", width=960, height=544)
        self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]), (960, 544))
        self.assertEqual(graph["main"]["class_type"], "SamplerCustomAdvanced")
        self.assertNotIn("high_sample", graph)
        self.assertNotIn("upscale", graph)

    def test_dimensions_keep_exact_final_size_and_h3_alignment(self):
        self.assertEqual(sampling_dimensions(1920, 1088, "二采"), (1920, 1088, 960, 544))
        with self.assertRaisesRegex(ValueError, "64"):
            expanded(width=960, height=544)
        with self.assertRaisesRegex(ValueError, "32"):
            expanded(width=1920, height=1080)

    def test_expanded_inputs_match_installed_film_interface(self):
        package = types.ModuleType("film_sampling_test")
        package.__path__ = [str(PLUGIN.parent / "ComfyUI-MiniMaxH3_LatentUpscaler")]
        sys.modules[package.__name__] = package
        spec = importlib.util.spec_from_file_location(package.__name__ + ".nodes", PLUGIN.parent /
                                                     "ComfyUI-MiniMaxH3_LatentUpscaler/nodes.py")
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        graph, _ = expanded()
        schema = native.MiniMaxH3LatentUpscaleCombined.INPUT_TYPES()
        self.assertTrue(set(schema["required"]) <= set(graph["upscale"]["inputs"]))
        self.assertTrue(set(graph["upscale"]["inputs"]) <= set(schema["required"]) | set(schema.get("optional", {})))


if __name__ == "__main__":
    unittest.main()
