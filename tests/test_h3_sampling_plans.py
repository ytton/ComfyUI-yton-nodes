"""CPU Film 2× graph contracts and installed upscaler input checks."""

import importlib.util
import sys
import types
import unittest

from test_h3_video_context import PLUGIN, expanded, defaults, torch, YtonH3VideoContextOmniGenerate
from video_context_test.omni_sampling import FILM_MODEL, sampling_dimensions
from comfy_extras.nodes_custom_sampler import KarrasScheduler


class FilmSamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = types.ModuleType("film_sampling_test")
        package.__path__ = [str(PLUGIN.parent / "ComfyUI-MiniMaxH3_LatentUpscaler")]
        sys.modules[package.__name__] = package
        spec = importlib.util.spec_from_file_location(package.__name__ + ".nodes", PLUGIN.parent /
                                                     "ComfyUI-MiniMaxH3_LatentUpscaler/nodes.py")
        cls.native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.native)

    def test_schema_defaults_to_film_second_pass_with_fixed_dimensions(self):
        required = YtonH3VideoContextOmniGenerate.INPUT_TYPES()["required"]
        self.assertEqual(required["sampling_mode"][1]["default"], "二采")
        self.assertIn(FILM_MODEL, required["film_model"][0])
        self.assertEqual(required["film_method"][1]["default"], "learned model")
        self.assertEqual(required["film_audio_denoise"][1]["default"], 0.0)
        self.assertEqual(required["film_noise_resample"][1]["default"], "independent")
        self.assertEqual(required["film_match_stats"][1]["default"], 0.0)
        self.assertEqual(required["second_sampler"][1]["default"], "euler")
        self.assertEqual(required["second_sigma_values"][1]["default"], "")
        self.assertEqual(required["second_ff_chunks"][1]["default"], "8")
        for name in ("sampling_plan", "first_pass_scale", "upscale_model",
                     "selflift_transition_step", "selflift_rho", "selflift_highres_tiling"):
            self.assertNotIn(name, required)

    def test_film_uses_half_dimensions_clean_endpoint_and_one_renoise(self):
        for width, height in ((1920, 1088), (1344, 768), (1280, 704)):
            with self.subTest(width=width, height=height):
                graph, _ = expanded(width=width, height=height, second_model=["custom_model", 0])
                self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]),
                                 (width // 2, height // 2))
                upscale = graph["upscale"]
                self.assertEqual(upscale["class_type"], "MiniMaxH3LatentUpscaleCombined")
                self.assertEqual(upscale["inputs"]["learned_model"], FILM_MODEL)
                self.assertEqual(upscale["inputs"]["samples"][1], 1)
                self.assertTrue(upscale["inputs"]["samples"][0].endswith("main"))
                self.assertEqual(graph["high_ff_chunks"]["inputs"]["model"], ["custom_model", 0])
                self.assertEqual(graph["high_ff_chunks"]["inputs"]["chunks"], 8)
                self.assertEqual(upscale["inputs"]["model"], graph["high_guider"]["inputs"]["model"])
                self.assertEqual(upscale["inputs"]["audio_denoise"], 0)
                self.assertEqual(graph["film_disable_noise"]["class_type"], "DisableNoise")
                self.assertTrue(graph["high_sample"]["inputs"]["noise"][0].endswith("film_disable_noise"))
                self.assertEqual(graph["high_sample"]["inputs"]["sigmas"], upscale["inputs"]["sigmas"])
                self.assertEqual(upscale["inputs"]["positive"], graph["guider"]["inputs"]["conditioning"])
                self.assertTrue(graph["high_guider"]["inputs"]["conditioning"][0].endswith("upscale"))
                self.assertEqual(graph["high_guider"]["inputs"]["conditioning"][1], 1)

    def test_second_pass_chunking_is_optional_and_keeps_the_selected_model(self):
        graph, _ = expanded(second_model=["custom_model", 0], second_ff_chunks="16")
        self.assertEqual(graph["high_ff_chunks"]["class_type"], "MiniMaxChunkFeedForward")
        self.assertEqual(graph["high_ff_chunks"]["inputs"],
                         {"model": ["custom_model", 0], "chunks": 16, "seq_threshold": 4096})
        graph, _ = expanded(second_model=["custom_model", 0], second_ff_chunks="沿用模型")
        self.assertNotIn("high_ff_chunks", graph)
        self.assertEqual(graph["high_guider"]["inputs"]["model"], ["custom_model", 0])
        self.assertEqual(graph["upscale"]["inputs"]["model"], ["custom_model", 0])
        graph, _ = expanded(sampling_mode="单采")
        self.assertNotIn("high_ff_chunks", graph)

    def test_auto_schedule_keeps_raw_sigma_start_and_reaches_zero(self):
        for start in (0.25, 0.4, 0.45, 0.6):
            for steps in (1, 4, 8):
                graph, _ = expanded(second_sigma_values="  ", second_sigma_start=start, second_steps=steps)
                schedule = graph["high_sigmas"]
                self.assertEqual(schedule["class_type"], "KarrasScheduler")
                sigmas = KarrasScheduler.execute(**schedule["inputs"]).result[0]
                self.assertEqual(len(sigmas), steps + 1)
                self.assertAlmostEqual(float(sigmas[0]), start, places=6)
                self.assertEqual(float(sigmas[-1]), 0.0)
                self.assertTrue(torch.all(sigmas[:-1] >= sigmas[1:]))
                self.assertEqual(graph["high_sample"]["inputs"]["sigmas"], graph["upscale"]["inputs"]["sigmas"])

    def test_auto_curve_front_loads_denoising_and_preserves_step_budget(self):
        graph, _ = expanded()
        sigmas = KarrasScheduler.execute(**graph["high_sigmas"]["inputs"]).result[0]
        self.assertEqual(len(sigmas), 5)
        self.assertGreater(float(sigmas[0] - sigmas[1]), 0.2)
        self.assertLess(float(sigmas[2]), 0.05)

    def test_second_pass_preserves_all_reference_modes_and_prompt(self):
        for mode in ("普通模式", "复刻模式"):
            for context in (False, True):
                graph, _ = expanded(mode=mode, prompt="保留人物、动作与对白", image=["image", 0],
                                    video=["video", 0], audio=["audio", 0],
                                    enable_context=context, previous_video=["previous", 0])
                self.assertEqual(graph["reference"]["inputs"]["prompt"], "保留人物、动作与对白")
                self.assertEqual(sum(n["class_type"] == "YtonMiniMaxH3ReferenceToVideo" for n in graph.values()), 1)
                self.assertEqual(graph["upscale"]["inputs"]["positive"], graph["guider"]["inputs"]["conditioning"])
                self.assertTrue(graph["high_guider"]["inputs"]["conditioning"][0].endswith("upscale"))
                self.assertEqual(graph["high_guider"]["inputs"]["conditioning"][1], 1)

    def test_film_custom_sigma_is_shared_by_renoise_and_sampling(self):
        graph, _ = expanded(second_sigma_values=["custom_sigma", 0])
        self.assertNotIn("high_sigmas", graph)
        self.assertEqual(graph["upscale"]["inputs"]["sigmas"], ["custom_sigma", 0])
        self.assertEqual(graph["high_sample"]["inputs"]["sigmas"], ["custom_sigma", 0])

    def test_custom_upscaler_settings_reach_combined_node(self):
        for method in ("learned model", "bicubic", "bislerp"):
            with self.subTest(method=method):
                graph, _ = expanded(film_method=method, film_model="experiment.safetensors",
                                    film_audio_denoise=1.0, film_noise_resample="upscale", film_match_stats=0.65)
                inputs = graph["upscale"]["inputs"]
                self.assertEqual(inputs["method"], method)
                self.assertEqual(inputs["learned_model"], "experiment.safetensors")
                self.assertEqual(inputs["audio_denoise"], 1.0)
                self.assertEqual(inputs["noise_resample"], "upscale")
                self.assertEqual(inputs["match_stats"], 0.65)

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
        self.assertEqual(graph["face_0_schedule"]["inputs"]["steps"], 4)
        self.assertEqual(graph["face_0_schedule"]["inputs"]["denoise"], 0.4)
        self.assertEqual(graph["face_0_crop"]["inputs"]["detector"], "bbox\\face_yolov8m.pt")
        self.assertEqual(graph["face_0_crop"]["inputs"]["fallback_detector"], "none")
        self.assertEqual(graph["face_0_noise"]["inputs"]["noise_seed"], 42)
        self.assertEqual(graph["face_0_denoise"]["inputs"]["denoise_multiplier_large_face"], 0.35)

    def test_face_controls_only_expose_enable_count_sigmas_and_reverse(self):
        schema = YtonH3VideoContextOmniGenerate.INPUT_TYPES()
        exposed = {name for group in ("required", "optional") for name in schema[group]
                   if name.startswith("face_") and name != "face_model"}
        self.assertEqual(exposed, {"face_refine", "face_count", "face_sigmas", "face_reverse"})
        graph, _ = expanded(face_refine=True, face_count=2, face_reverse=True)
        self.assertIn("face_1_sample", graph)
        self.assertIn("face_reverse", graph)
        self.assertIn("face_restore_order", graph)

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
        for name in ("main_context_add_guide", "face_0_sample", "seamless_color_match"):
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
        graph, _ = expanded()
        schema = self.native.MiniMaxH3LatentUpscaleCombined.INPUT_TYPES()
        exposed = YtonH3VideoContextOmniGenerate.INPUT_TYPES()["required"]
        for name in ("method", "noise_resample"):
            self.assertLessEqual(set(exposed["film_" + name][0]), set(schema["required"][name][0]))
        for name, group in (("audio_denoise", "required"), ("match_stats", "optional")):
            self.assertEqual(exposed["film_" + name][0], schema[group][name][0])
            for option in ("min", "max", "step"):
                self.assertEqual(exposed["film_" + name][1][option], schema[group][name][1][option])
        self.assertTrue(set(schema["required"]) <= set(graph["upscale"]["inputs"]))
        self.assertTrue(set(graph["upscale"]["inputs"]) <= set(schema["required"]) | set(schema.get("optional", {})))

    def test_native_film_conditioning_scales_visual_refs_and_preserves_text_audio_and_timing(self):
        text, audio = torch.randn(1, 3, 8), torch.randn(1, 32, 2, 37)
        image, video = torch.randn(1, 24, 4, 6), torch.randn(1, 24, 7, 4, 6)
        metadata = {"minimax_refs": [
            {"kind": "image", "latent": image, "latent_h": 4, "latent_w": 6},
            {"kind": "video", "latent": video, "latent_h": 4, "latent_w": 6,
             "latent_t": 7, "audio_latent": audio},
            {"kind": "audio", "audio_latent": audio},
        ], "minimax_keyframes": [{"latent": video, "resolved_frame_index": 0,
                                  "audio_latent": audio, "audio_feather_ticks": 256}]}
        original = [[text, metadata]]
        result = self.native.upscale_minimax_conditioning(original, 2.0, "nearest-exact")
        self.assertIs(result[0][0], text)
        refs = result[0][1]["minimax_refs"]
        for ref in refs[:2]:
            self.assertEqual(ref["latent"].shape[-2:], (8, 12))
            self.assertEqual((ref["latent_h"], ref["latent_w"]), (8, 12))
        self.assertEqual(refs[1]["latent_t"], 7)
        self.assertIs(refs[1]["audio_latent"], audio)
        self.assertIs(refs[2]["audio_latent"], audio)
        keyframe = result[0][1]["minimax_keyframes"][0]
        self.assertEqual(keyframe["latent"].shape, (1, 24, 7, 8, 12))
        self.assertIs(keyframe["audio_latent"], audio)
        self.assertEqual(keyframe["resolved_frame_index"], 0)
        self.assertEqual(keyframe["audio_feather_ticks"], 256)
        self.assertIs(original[0][1], metadata)
        self.assertEqual(metadata["minimax_refs"][0]["latent"].shape, (1, 24, 4, 6))
        self.assertEqual(metadata["minimax_refs"][1]["latent_h"], 4)


if __name__ == "__main__":
    unittest.main()
