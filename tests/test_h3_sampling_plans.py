"""CPU graph contracts and native SelfLift/Film input checks; no generation queue."""

import importlib.util
import sys
import types
import unittest

from test_h3_video_context import PLUGIN, expanded, torch, defaults, YtonH3VideoContextOmniGenerate
from video_context_test.omni_sampling import FILM, FILM_MODEL, SELFLIFT, TRADITIONAL, sampling_dimensions


def installed_nodes(directory, alias):
    package = types.ModuleType(alias)
    package.__path__ = [str(PLUGIN.parent / directory)]
    sys.modules[alias] = package
    spec = importlib.util.spec_from_file_location(alias + ".nodes", PLUGIN.parent / directory / "nodes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SamplingPlanTests(unittest.TestCase):
    def test_traditional_respects_manual_scale_and_final_target(self):
        graph, _ = expanded(sampling_mode="二采", sampling_plan=TRADITIONAL,
                            width=1920, height=1088, first_pass_scale=0.7)
        self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]), (1344, 768))
        self.assertEqual(graph["upscale"]["class_type"], "easy minimaxH3LatentUpscaler")
        self.assertEqual((graph["upscale"]["inputs"]["mode.width"], graph["upscale"]["inputs"]["mode.height"]), (1920, 1088))

    def test_film_ignores_external_scale_and_uses_clean_endpoint(self):
        for scale in (0.2, 0.7, 1.0):
            with self.subTest(scale=scale):
                graph, _ = expanded(sampling_mode="二采", sampling_plan=FILM, width=1920,
                                    height=1088, first_pass_scale=scale, second_model=["custom_model", 0])
                self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]), (960,544))
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
                self.assertNotIn("positive", upscale["inputs"], "high conditions were already encoded at target dimensions")
                self.assertNotIn("split_main", graph)

    def test_film_custom_sigma_is_shared_by_renoise_and_sampling(self):
        graph, _ = expanded(sampling_mode="二采", sampling_plan=FILM, second_sigmas=["custom_sigma", 0])
        self.assertNotIn("high_sigmas", graph)
        self.assertEqual(graph["upscale"]["inputs"]["sigmas"], ["custom_sigma", 0])
        self.assertEqual(graph["high_sample"]["inputs"]["sigmas"], ["custom_sigma", 0])

    def test_selflift_runs_one_complete_schedule_at_target_size(self):
        graph, _ = expanded(sampling_mode="二采", sampling_plan=SELFLIFT, width=1920, height=1088,
                            first_pass_scale=0.7, second_model=["hires_model", 0],
                            second_sigmas=["unused_second", 0], sampler_name="sa_solver")
        self.assertEqual(graph["main"]["class_type"], "SelfLiftH3Sampler")
        self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]), (1920,1088))
        self.assertEqual(graph["main"]["inputs"]["lowres_scale"], 0.7)
        self.assertEqual(graph["main"]["inputs"]["transition_step"], 2)
        self.assertEqual(graph["main"]["inputs"]["model_hires"], ["hires_model", 0])
        self.assertEqual(graph["main"]["inputs"]["cfg"], 1.0)
        self.assertEqual(graph["sampler"]["inputs"]["sampler_name"], "euler")
        for unused in ("high_reference", "high_sample", "upscale", "high_sigmas"):
            self.assertNotIn(unused, graph)
        for node in graph.values():
            self.assertNotIn(["unused_second", 0], node["inputs"].values())

    def test_selflift_uses_custom_main_sigma_without_an_extra_scheduler(self):
        graph, _ = expanded(sampling_mode="二采", sampling_plan=SELFLIFT, sigmas=["full_schedule", 0])
        self.assertNotIn("schedule", graph)
        self.assertEqual(graph["main"]["inputs"]["sigmas"], ["full_schedule", 0])

    def test_second_sigma_link_is_only_evaluated_by_plans_that_use_it(self):
        node = YtonH3VideoContextOmniGenerate()
        self.assertTrue(node.INPUT_TYPES()["optional"]["second_sigmas"][1]["lazy"])
        for plan in (TRADITIONAL, FILM, SELFLIFT):
            for mode in ("单采", "二采"):
                inputs = {name: [value] for name,value in defaults(sampling_mode=mode, sampling_plan=plan).items()}
                inputs["second_sigmas"] = [None]
                requested = node.check_lazy_status(**inputs)
                self.assertEqual("second_sigmas" in requested, mode == "二采" and plan != SELFLIFT)

    def test_video_context_and_face_refine_survive_every_plan(self):
        for plan in (TRADITIONAL, FILM, SELFLIFT):
            with self.subTest(plan=plan):
                graph, _ = expanded(sampling_mode="二采", sampling_plan=plan, duration=7.5,
                                    enable_context=True, previous_video=["previous_video", 0], face_refine=True)
                self.assertEqual(graph["reference"]["inputs"]["length"], 209)
                self.assertEqual(graph["trim"]["inputs"]["head_trim_frames"], 22)
                self.assertEqual(graph["trim"]["inputs"]["tail_trim_frames"], 7)
                self.assertIn("main_context_add_guide", graph)
                if plan != SELFLIFT:
                    self.assertIn("high_context_add_guide", graph)
                self.assertIn("face_0_sample", graph)
                self.assertIn("seamless_color_match", graph)

    def test_single_pass_never_uses_a_second_plan(self):
        for plan in (TRADITIONAL, FILM, SELFLIFT):
            graph, _ = expanded(sampling_plan=plan, width=960, height=544)
            self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]), (960,544))
            self.assertEqual(graph["main"]["class_type"], "SamplerCustomAdvanced")
            self.assertNotIn("high_sample", graph)

    def test_invalid_dimensions_and_selflift_steps_fail_before_expansion(self):
        with self.assertRaisesRegex(ValueError, "64"):
            expanded(sampling_mode="二采", sampling_plan=FILM, width=960, height=544)
        with self.assertRaisesRegex(ValueError, "低分步数"):
            expanded(sampling_mode="二采", sampling_plan=SELFLIFT, steps=2)
        with self.assertRaisesRegex(ValueError, "0.25"):
            expanded(sampling_mode="二采", sampling_plan=SELFLIFT, first_pass_scale=0.2)
        for scale in (float("nan"), float("inf"), 0.0):
            with self.assertRaises(ValueError):
                sampling_dimensions(1920,1088,"二采",TRADITIONAL,scale)

    def test_expanded_inputs_match_installed_sampler_interfaces(self):
        film = installed_nodes("ComfyUI-MiniMaxH3_LatentUpscaler", "film_sampling_test")
        selflift = installed_nodes("comfyui-SelfLift", "selflift_sampling_test")
        for plan, node_type, cls in ((FILM,"MiniMaxH3LatentUpscaleCombined",film.MiniMaxH3LatentUpscaleCombined),
                                    (SELFLIFT,"SelfLiftH3Sampler",selflift.SelfLiftH3Sampler)):
            graph, _ = expanded(sampling_mode="二采", sampling_plan=plan)
            node = next(n for n in graph.values() if n["class_type"] == node_type)
            schema = cls.INPUT_TYPES()
            self.assertTrue(set(schema["required"]) <= set(node["inputs"]))
            self.assertTrue(set(node["inputs"]) <= set(schema["required"]) | set(schema.get("optional", {})))

    def test_selflift_schedule_validates_custom_tensors_and_transition_bounds(self):
        native = installed_nodes("comfyui-SelfLift", "selflift_schedule_test")
        native._validate_schedule(torch.tensor([1.0, 0.8, 0.5, 0.2, 0]), 2)
        for values, boundary in (([1.0,0.6,0],2), ([1.0,1.0,0],1), ([1.0,0.3,0.6,0],1)):
            with self.assertRaises(ValueError):
                native._validate_schedule(torch.tensor(values), boundary)


if __name__ == "__main__":
    unittest.main()
