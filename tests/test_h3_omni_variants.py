"""CPU contracts for three generators sharing VIDEO continuation and face refinement."""
import importlib.util
import sys
import types
import unittest

from test_h3_video_context import PLUGIN, torch, DynamicPrompt, execution, asyncio
from comfy_execution.graph_utils import is_link
from video_context_test import omni_runtime
from video_context_test.omni_video_context_graph import build_video_context_graph
from video_context_test.omni_video_context_runtime import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS


VARIANTS = {name: cls for name, cls in NODE_CLASS_MAPPINGS.items() if name != "YtonH3VideoTail"}


def variant_defaults(cls, **overrides):
    values = {}
    for name, definition in cls.INPUT_TYPES()["required"].items():
        options = definition[1] if len(definition) > 1 else {}
        if "default" in options:
            values[name] = options["default"]
        elif isinstance(definition[0], list):
            values[name] = definition[0][0]
    values.update(model=["model", 0], clip=["clip", 0], vae=["video_vae", 0], audio_vae=["audio_vae", 0])
    values.update(overrides)
    return values


def expanded(cls, **overrides):
    result = build_video_context_graph(sampling_plan=cls.SAMPLING_PLAN, **variant_defaults(cls, **overrides))
    return {key.split(".")[-1]: value for key, value in result["expand"].items()}


class OmniVariantTests(unittest.TestCase):
    def test_debug_keeps_context_without_changing_sampling_or_tail_trimming(self):
        def comparable(cls, **options):
            graph = expanded(cls, **options)
            for node in graph.values():
                for name, value in node["inputs"].items():
                    if is_link(value):
                        node["inputs"][name] = [value[0].split(".")[-1], value[1]]
            return graph

        for cls in VARIANTS.values():
            self.assertFalse(cls.INPUT_TYPES()["required"]["debug_keep_context"][1]["default"])
            for sampling in ("单采", "二采"):
                for mode in ("普通模式", "复刻模式"):
                    for extend in (True, False):
                        with self.subTest(plan=cls.SAMPLING_PLAN, sampling=sampling, mode=mode, extend=extend):
                            options = dict(sampling_mode=sampling, mode=mode, duration=141 / 24,
                                           video=["source", 0], enable_context=True,
                                           previous_video=["previous", 0], context_auto_extend=extend)
                            normal = comparable(cls, **options)
                            debug = comparable(cls, **options, debug_keep_context=True)
                            self.assertEqual(set(debug), set(normal))
                            for name in normal:
                                if name not in ("trim", "seamless_color_match"):
                                    self.assertEqual(debug[name], normal[name])
                            self.assertEqual(debug["trim"]["inputs"]["head_trim_frames"], 0)
                            for name in ("images", "audio", "fps", "tail_trim_frames"):
                                self.assertEqual(debug["trim"]["inputs"][name], normal["trim"]["inputs"][name])
                            self.assertEqual(normal["seamless_color_match"]["inputs"]["source_stats.target_index"], 0)
                            self.assertEqual(debug["seamless_color_match"]["inputs"]["source_stats.target_index"], 22)
            for enabled, previous in ((False, ["previous", 0]), (True, None)):
                for mode in ("普通模式", "复刻模式"):
                    options = dict(mode=mode, video=["source", 0], enable_context=enabled, previous_video=previous)
                    self.assertEqual(comparable(cls, **options), comparable(cls, **options, debug_keep_context=True))

    def test_included_context_keeps_the_guide_without_extending_the_target_length(self):
        for cls in VARIANTS.values():
            self.assertTrue(cls.INPUT_TYPES()["required"]["context_auto_extend"][1]["default"])
            for sampling_mode in ("单采", "二采"):
                for mode in ("普通模式", "复刻模式"):
                    with self.subTest(plan=cls.SAMPLING_PLAN, sampling=sampling_mode, mode=mode):
                        graph = expanded(cls, mode=mode, sampling_mode=sampling_mode, duration=141 / 24,
                                         video=["source", 0], enable_context=True,
                                         previous_video=["previous", 0], context_auto_extend=False)
                        self.assertIn("main_context_add_guide", graph)
                        self.assertIn("seamless_color_match", graph)
                        if mode == "复刻模式":
                            self.assertFalse(graph["replica"]["inputs"]["context_auto_extend"])
                            self.assertEqual(graph["replica"]["inputs"]["context_frames"], 22)
                        else:
                            self.assertEqual(graph["reference"]["inputs"]["length"], 141)
                            self.assertEqual(graph["trim"]["inputs"]["head_trim_frames"], 22)
                            self.assertEqual(graph["trim"]["inputs"]["tail_trim_frames"], 0)
                        if "high_reference" in graph:
                            self.assertEqual(graph["high_reference"]["inputs"]["length"],
                                             graph["reference"]["inputs"]["length"])
                for enabled, previous in ((True, None), (False, ["previous", 0])):
                    graph = expanded(cls, sampling_mode=sampling_mode, duration=141 / 24,
                                     enable_context=enabled, previous_video=previous, context_auto_extend=False)
                    self.assertEqual(graph["reference"]["inputs"]["length"], 141)
                    self.assertEqual(graph["trim"]["inputs"]["head_trim_frames"], 0)
                    self.assertNotIn("main_context_add_guide", graph)

    def test_registration_contains_exactly_three_current_generators(self):
        self.assertEqual({NODE_DISPLAY_NAME_MAPPINGS[name] for name in VARIANTS},
                         {"H3 全模态生成 · TR", "H3 全模态生成 · SelfLift", "H3 全模态生成"})
        self.assertNotIn("YtonH3OmniGenerate", omni_runtime.NODE_CLASS_MAPPINGS)
        self.assertFalse(hasattr(omni_runtime, "YtonH3OmniGenerate"))

    def test_each_schema_only_exposes_its_sampling_plan_and_four_face_controls(self):
        for cls in VARIANTS.values():
            with self.subTest(plan=cls.SAMPLING_PLAN):
                schema = cls.INPUT_TYPES()
                required = schema["required"]
                names = set(required) | set(schema["optional"])
                self.assertNotIn("clip_index", names)
                self.assertEqual({name for name in names if name.startswith("face_")},
                                 {"face_model", "face_refine", "face_count", "face_sigmas", "face_reverse"})
                self.assertNotIn("latent_path", names)
                self.assertNotIn("context_path", names)
                self.assertIn("previous_video", schema["optional"])
                self.assertFalse(required["enable_context"][1]["default"])
                self.assertEqual("film_model" in names, cls.SAMPLING_PLAN == "tr")
                self.assertEqual("selflift_transition_step" in names, cls.SAMPLING_PLAN == "selflift")
                self.assertEqual("first_pass_scale" in names, cls.SAMPLING_PLAN != "tr")
                self.assertEqual("second_sigma_values" in names, cls.SAMPLING_PLAN != "selflift")

    def test_native_model_inputs_reach_each_stage_without_loader_unpacking(self):
        for cls in VARIANTS.values():
            required=cls.INPUT_TYPES()["required"]
            self.assertNotIn("model_loader",required)
            for name,kind in (("model","MODEL"),("clip","CLIP"),("vae","VAE"),("audio_vae","VAE")):
                self.assertEqual(required[name][0],kind)
                self.assertTrue(required[name][1]["rawLink"])
            graph=expanded(cls,face_refine=True,enable_context=True,previous_video=["prior",0])
            self.assertFalse(any(node["class_type"].startswith("fast ") for node in graph.values()))
            for name in ("reference","face_0_reference"):
                self.assertEqual(graph[name]["inputs"]["clip"],["clip",0])
                self.assertEqual(graph[name]["inputs"]["vae"],["video_vae",0])
                self.assertEqual(graph[name]["inputs"]["audio_vae"],["audio_vae",0])
            self.assertEqual(graph["prepare_sampling"]["inputs"]["model"],["model",0])
            self.assertEqual(graph["sound"]["inputs"]["vae"],["audio_vae",0])
            self.assertEqual(graph["face_0_denoise"]["inputs"]["model"],["model",0])

    def test_final_video_decode_uses_input_vae_and_keeps_references_for_face_refinement(self):
        for cls in VARIANTS.values():
            for sampling_mode in ("单采", "二采"):
                with self.subTest(plan=cls.SAMPLING_PLAN, sampling=sampling_mode):
                    graph = expanded(cls, sampling_mode=sampling_mode, width=1920, height=1088,
                                     image=["images", 0], face_refine=True, face_count=2,
                                     enable_context=True, previous_video=["prior", 0])
                    decode = graph["frames"]
                    self.assertEqual(decode["class_type"], "VAEDecode")
                    self.assertEqual(decode["inputs"]["vae"], ["video_vae", 0])
                    final = "high_sample" if sampling_mode == "二采" and cls.SAMPLING_PLAN != "selflift" else "main"
                    self.assertTrue(decode["inputs"]["samples"][0].endswith(final))
                    self.assertEqual(decode["inputs"]["samples"][1], 0)
                    self.assertEqual(graph["sound"]["inputs"]["samples"], decode["inputs"]["samples"])
                    self.assertTrue(graph["face_0_crop"]["inputs"]["images"][0].endswith("frames"))
                    for name in ("reference", "face_0_reference", "face_1_reference"):
                        self.assertEqual(graph[name]["inputs"]["image"], ["images", 0])
                    self.assertEqual(graph["face_0_decode"]["inputs"]["vae"], ["video_vae", 0])

    def test_normal_mode_passes_complete_video_and_audio_references_in_every_plan(self):
        for cls in VARIANTS.values():
            for sampling_mode in ("单采", "二采"):
                for enabled in (False, True):
                    with self.subTest(plan=cls.SAMPLING_PLAN, sampling_mode=sampling_mode, context=enabled):
                        graph = expanded(cls, sampling_mode=sampling_mode, duration=7.5, video=["videos", 0],
                                         audio=["audios", 0], previous_video=["previous", 0], enable_context=enabled)
                        for name in ("reference", "high_reference"):
                            if name not in graph:
                                continue
                            self.assertEqual(graph[name]["inputs"]["video"], ["videos", 0])
                            self.assertEqual(graph[name]["inputs"]["audio"], ["audios", 0])
                        for name in ("segment", "source_components", "source_images", "source_audio",
                                     "source_video", "source_guide", "high_source_guide"):
                            self.assertNotIn(name, graph)
                        self.assertEqual(graph["reference"]["inputs"]["length"], 209 if enabled else 192)
                        self.assertEqual(graph["trim"]["inputs"]["head_trim_frames"], 22 if enabled else 0)

    def test_all_variants_single_pass_skips_both_upscale_engines_and_uses_target_size(self):
        for cls in VARIANTS.values():
            graph = expanded(cls, sampling_mode="单采", width=1920, height=1088, previous_video=["prior", 0])
            self.assertEqual(graph["main"]["class_type"], "SamplerCustomAdvanced")
            self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]), (1920, 1088))
            for name in ("upscale", "high_sample", "high_ff_chunks", "previous"):
                self.assertNotIn(name, graph)

    def test_context_controls_reach_guide_and_final_colour_in_every_variant(self):
        for cls in VARIANTS.values():
            schema = cls.INPUT_TYPES()['required']
            self.assertEqual(schema['context_noise_strength'][1]['default'], 0.1)
            self.assertEqual(schema['context_color_strength'][1]['default'], 0.75)
            for sampling_mode in ('单采', '二采'):
                for noise, colour in ((0.0, 0.0), (0.23, 0.42), (1.0, 1.0)):
                    with self.subTest(plan=cls.SAMPLING_PLAN, mode=sampling_mode, noise=noise, colour=colour):
                        graph = expanded(cls, sampling_mode=sampling_mode, enable_context=True,
                                         previous_video=['previous', 0], context_noise_strength=noise,
                                         context_color_strength=colour)
                        self.assertEqual(graph['main_ctx_context_first_noise']['inputs']['strength'], noise)
                        self.assertEqual(graph['main_ctx_context_last_exact']['inputs']['strength'], 0)
                        if colour:
                            self.assertEqual(graph['seamless_color_match']['inputs']['strength'], colour)
                            self.assertTrue(graph['seamless_color_match']['inputs']['image_target'][0].endswith('trim'))
                        else:
                            self.assertNotIn('seamless_color_match', graph)
                            self.assertTrue(graph['video']['inputs']['images'][0].endswith('trim'))
                        if sampling_mode == '二采' and cls.SAMPLING_PLAN == 'traditional':
                            self.assertEqual(graph['high_context_add_guide']['inputs']['image'],
                                             graph['main_context_add_guide']['inputs']['image'])
            for previous, enabled in ((None, True), (['previous', 0], False)):
                graph = expanded(cls, previous_video=previous, enable_context=enabled,
                                 context_noise_strength=1.0, context_color_strength=1.0)
                self.assertNotIn('main_ctx_context_first_noise', graph)
                self.assertNotIn('seamless_color_match', graph)

    def test_traditional_uses_targeted_3d_upscale_and_preserves_audio(self):
        cls = VARIANTS["YtonH3TraditionalOmniGenerate"]
        graph = expanded(cls, width=1920, height=1088, first_pass_scale=0.5,
                         second_model=["hi_model", 0], second_sigma_values=["sigma2", 0])
        self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]), (960, 544))
        self.assertEqual(graph["upscale"]["class_type"], "easy minimaxH3LatentUpscaler")
        self.assertEqual((graph["upscale"]["inputs"]["mode.width"], graph["upscale"]["inputs"]["mode.height"]), (1920, 1088))
        self.assertEqual(graph["split_main"]["inputs"]["av_latent"][1], 1)
        self.assertTrue(graph["high_av"]["inputs"]["audio_latent"][0].endswith("split_main"))
        self.assertEqual(graph["high_av"]["inputs"]["audio_latent"][1], 1)
        self.assertEqual(graph["high_sample"]["inputs"]["sigmas"], ["sigma2", 0])
        self.assertEqual(graph["high_ff_chunks"]["inputs"]["model"], ["hi_model", 0])
        self.assertTrue(graph["high_sample"]["inputs"]["noise"][0].endswith("high_noise"))
        self.assertNotIn("film_disable_noise", graph)

    def test_traditional_reencodes_original_prompt_and_every_reference_at_final_size(self):
        cls = VARIANTS["YtonH3TraditionalOmniGenerate"]
        for mode in ("普通模式", "复刻模式"):
            graph = expanded(cls, mode=mode, prompt="动作与对白保持一致", video=["video", 0], image=["image", 0],
                             audio=["audio", 0], enable_context=True, previous_video=["prior", 0])
            high = graph["high_reference"]["inputs"]
            self.assertEqual(high["prompt"], "动作与对白保持一致")
            self.assertEqual(high["image"], ["image", 0])
            self.assertIn("video", high)
            self.assertEqual(high["width"], 1344)
            self.assertIn("high_context_add_guide_audio_feather", graph)
            self.assertTrue(graph["high_guider"]["inputs"]["conditioning"][0].endswith("high_context_add_guide_audio_feather"))

    def test_selflift_uses_one_complete_schedule_and_target_latent(self):
        cls = VARIANTS["YtonH3SelfLiftOmniGenerate"]
        graph = expanded(cls, sigmas=["sigmas", 0], width=1920, height=1088,
                         selflift_transition_step=3, first_pass_scale=0.6, second_model=["hi_model", 0])
        sampler = graph["main"]
        self.assertEqual(sampler["class_type"], "SelfLiftH3Sampler")
        self.assertEqual(sampler["inputs"]["sigmas"], ["sigmas", 0])
        self.assertEqual(sampler["inputs"]["transition_step"], 3)
        self.assertEqual(sampler["inputs"]["lowres_scale"], 0.6)
        self.assertEqual(sampler["inputs"]["cfg"], 1.0)
        self.assertEqual(graph["reference"]["inputs"]["width"], 1920)
        self.assertEqual(graph["high_ff_chunks"]["inputs"]["model"], ["hi_model", 0])
        self.assertTrue(sampler["inputs"]["model_hires"][0].endswith("high_prepare_sampling"))
        self.assertTrue(graph["high_prepare_sampling"]["inputs"]["model"][0].endswith("high_ff_chunks"))
        for name in ("high_sample", "upscale", "high_sigmas", "schedule"):
            self.assertNotIn(name, graph)

    def test_selflift_uses_native_installed_sampler_interface(self):
        package = types.ModuleType("selflift_contract_test")
        package.__path__ = [str(PLUGIN.parent / "comfyui-SelfLift")]
        sys.modules[package.__name__] = package
        spec = importlib.util.spec_from_file_location(package.__name__ + ".nodes", PLUGIN.parent / "comfyui-SelfLift/nodes.py")
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        graph = expanded(VARIANTS["YtonH3SelfLiftOmniGenerate"])
        schema = native.SelfLiftH3Sampler.INPUT_TYPES()
        self.assertLessEqual(set(schema["required"]), set(graph["main"]["inputs"]))
        self.assertLessEqual(set(graph["main"]["inputs"]), set(schema["required"]) | set(schema["optional"]))
        native._validate_schedule(torch.tensor([1.0, 0.7, 0.4, 0.1, 0.0]), 2)

    def test_traditional_dimensions_support_editable_scale_and_auto_sigma(self):
        cls = VARIANTS["YtonH3TraditionalOmniGenerate"]
        graph = expanded(cls, width=1920, height=1088, first_pass_scale=0.625, second_sigma_values="")
        self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]), (1216, 672))
        self.assertEqual(graph["high_sigmas"]["class_type"], "KarrasScheduler")
        self.assertEqual(graph["high_sigmas"]["inputs"]["sigma_max"], 0.4)
        self.assertEqual(graph["high_reference"]["inputs"]["width"], 1920)
        with self.assertRaises(ValueError):
            expanded(cls, first_pass_scale=0)

    def test_selflift_checks_invalid_configuration_before_generation(self):
        cls = VARIANTS["YtonH3SelfLiftOmniGenerate"]
        for changes in ({"steps": 1}, {"selflift_transition_step": 4}, {"sampler_name": "sa_solver"},
                        {"first_pass_scale": 0.1}, {"selflift_w_min": 0.8, "selflift_w_max": 0.3},
                        {"upscale_model": "none", "selflift_rho": 0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                expanded(cls, **changes)

    def test_all_variants_context_and_face_share_trimmed_output(self):
        for cls in VARIANTS.values():
            graph = expanded(cls, duration=7.5, enable_context=True, previous_video=["prior", 0],
                             face_refine=True, face_sigmas=["face_sigma", 0], face_count=2)
            self.assertEqual(graph["reference"]["inputs"]["length"], 209)
            self.assertEqual(graph["trim"]["inputs"]["head_trim_frames"], 22)
            self.assertEqual(graph["trim"]["inputs"]["tail_trim_frames"], 7)
            self.assertIn("main_context_add_guide_audio_feather", graph)
            self.assertIn("seamless_color_match", graph)
            self.assertIn("face_1_sample", graph)
            self.assertEqual(graph["face_0_sample"]["inputs"]["sigmas"], ["face_sigma", 0])

    def test_all_variant_runtimes_handle_connected_empty_media(self):
        for name, cls in VARIANTS.items():
            for empty in ([], [None]):
                values = variant_defaults(cls, image=["media", 0], video=["media", 1], audio=["media", 2])
                dynprompt = DynamicPrompt({"omni": {"class_type": name, "inputs": values}})
                cache = execution.CacheEntry(ui={}, outputs=([torch.zeros(1, 32, 32, 3)], empty, empty))
                execution_list = types.SimpleNamespace(get_cache=lambda source, target: cache)
                inputs, missing, _ = execution.get_input_data(values, cls, "omni", execution_list=execution_list, dynprompt=dynprompt)
                self.assertFalse(missing)
                results = asyncio.run(execution._async_map_node_over_list("variant-media-test", "omni", cls(), inputs, "generate"))
                graph = {key.split(".")[-1]: value for key, value in results[0]["expand"].items()}
                self.assertNotIn("source_components", graph)
                self.assertNotIn("video", graph["reference"]["inputs"])
                self.assertNotIn("audio", graph["reference"]["inputs"])
                self.assertEqual(graph["main"]["class_type"], "SelfLiftH3Sampler" if cls.SAMPLING_PLAN == "selflift" else "SamplerCustomAdvanced")


if __name__ == "__main__":
    unittest.main()
