"""Sampling order and cache regression tests using ComfyUI's native executor."""

import copy
import types
import unittest
from unittest.mock import Mock, patch

from test_h3_omni_variants import VARIANTS, expanded
from test_h3_video_context import asyncio, execution, torch
from video_context_test.sampling_runtime import YtonH3PrepareSampling
from video_context_test.face_runtime import YtonH3FaceRefine
import nodes
from comfy.model_patcher import ModelPatcher
from comfy.patcher_extension import WrappersMP
from comfy.samplers import CFGGuider


def upstream(graph, name):
    found = set()
    for value in graph[name]["inputs"].values():
        if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
            parent = value[0].split(".")[-1]
            if parent in graph:
                found.add(parent)
                found.update(upstream(graph, parent))
    return found


def cpu_model():
    return ModelPatcher(torch.nn.Linear(1, 1), torch.device("cpu"), torch.device("cpu"))


class SamplingGraphTests(unittest.TestCase):
    def test_each_sampler_waits_for_references_and_uses_a_scheduled_model(self):
        for cls in VARIANTS.values():
            for mode in ("单采", "二采"):
                for context in (False, True):
                    with self.subTest(plan=cls.SAMPLING_PLAN, mode=mode, context=context):
                        graph = expanded(cls, sampling_mode=mode, enable_context=context,
                                         previous_video=["prior", 0])
                        before_main = upstream(graph, "main")
                        self.assertIn("prepare_sampling", before_main)
                        self.assertIn("reference", upstream(graph, "prepare_sampling"))
                        if context:
                            self.assertIn("main_context_add_guide_audio_feather", upstream(graph, "prepare_sampling"))
                        if mode == "单采":
                            self.assertNotIn("high_prepare_sampling", graph)
                        else:
                            high_sampler = "main" if cls.SAMPLING_PLAN == "selflift" else "high_sample"
                            self.assertIn("high_prepare_sampling", upstream(graph, high_sampler))
                            if cls.SAMPLING_PLAN == "traditional":
                                self.assertIn("high_reference", upstream(graph, "prepare_sampling"))
                                self.assertNotIn("main", upstream(graph, "high_reference"))
                                if context:
                                    self.assertIn("high_context_add_guide_audio_feather", before_main)
                            else:
                                self.assertNotIn("high_reference", graph)

    def test_each_face_uses_its_adaptive_model_after_reference_encoding(self):
        YtonH3FaceRefine.GET_SCHEMA()
        standalone = YtonH3FaceRefine.execute(images=["frames", 0], model=["model", 0],
                                              clip=["clip", 0], vae=["vae", 0], face_count=2)
        graphs = [expanded(cls, face_refine=True, face_count=2) for cls in VARIANTS.values()]
        graphs.append({key.split(".")[-1]: value for key, value in standalone.expand.items()})
        for graph in graphs:
            for i in range(2):
                prefix = f"face_{i}_"
                deps = upstream(graph, prefix + "prepare_sampling")
                self.assertIn(prefix + "reference", deps)
                self.assertIn(prefix + "inject", deps)
                self.assertTrue(graph[prefix + "prepare_sampling"]["inputs"]["model"][0].endswith(prefix + "denoise"))
                self.assertTrue(graph[prefix + "guider"]["inputs"]["model"][0].endswith(prefix + "prepare_sampling"))


class SamplingRuntimeTests(unittest.TestCase):
    def test_native_sampler_releases_only_te_before_outer_sample_and_preserves_wrappers(self):
        original = cpu_model()
        clip = types.SimpleNamespace(patcher=cpu_model())
        events = []

        def existing(executor, *args, **kwargs):
            events.append("existing")
            return executor(*args, **kwargs)

        original.add_wrapper_with_key(WrappersMP.OUTER_SAMPLE, "other_node", existing)
        with patch("video_context_test.sampling_runtime.model_management.unload_model_and_clones") as unload:
            patched = YtonH3PrepareSampling.execute(original, clip, []).result[0]
            unload.assert_not_called()
            self.assertIs(patched.model, original.model)
            self.assertEqual(original.get_all_wrappers(WrappersMP.OUTER_SAMPLE), [existing])
            patched = YtonH3PrepareSampling.execute(patched, clip, []).result[0]
            self.assertEqual(len(patched.get_all_wrappers(WrappersMP.OUTER_SAMPLE)), 2)
            guider = CFGGuider(patched)

            def outer(noise, latent, sampler, sigmas, denoise_mask, callback, disable_pbar, seed, latent_shapes=None):
                unload.assert_called_once_with(clip.patcher)
                self.assertEqual(seed, 42)
                return result

            result = torch.ones(1, 1, 1, 1)
            with patch.object(guider, "outer_sample", side_effect=outer):
                output = guider.sample(torch.zeros_like(result), result, None, torch.tensor([1., 0.]), seed=42)
            self.assertIs(output, result)
            self.assertEqual(events, ["existing"])

    def test_sampling_errors_are_not_swallowed(self):
        clip = types.SimpleNamespace(patcher=cpu_model())
        model = YtonH3PrepareSampling.execute(cpu_model(), clip, []).result[0]
        guider = CFGGuider(model)
        latent = torch.zeros(1, 1, 1, 1)
        with patch("video_context_test.sampling_runtime.model_management.unload_model_and_clones") as unload:
            with patch.object(guider, "outer_sample", side_effect=RuntimeError("sample failed")):
                with self.assertRaisesRegex(RuntimeError, "sample failed"):
                    guider.sample(latent, latent, None, torch.tensor([1., 0.]))
            unload.assert_called_once_with(clip.patcher)

    def test_second_pass_rerun_keeps_first_pass_cache_and_still_releases_te(self):
        model = cpu_model()
        clip = types.SimpleNamespace(patcher=cpu_model())
        events = []
        te_loaded = False
        received = []

        class Models:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {}}
            RETURN_TYPES = ("MODEL", "CLIP", "LATENT")
            FUNCTION = "run"
            def run(self):
                return (model, clip, torch.zeros(1, 1, 1, 1))

        class Reference:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"tag": ("STRING",)}}
            RETURN_TYPES = ("CONDITIONING",)
            FUNCTION = "run"
            def run(self, tag):
                nonlocal te_loaded
                te_loaded = True
                events.append(tag)
                return ([[torch.zeros(1, 1, 1), {}]],)

        class Sampler:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"model": ("MODEL",), "conditioning": ("CONDITIONING",),
                                     "seed": ("INT",), "latent": ("LATENT",)}}
            RETURN_TYPES = ("LATENT",)
            FUNCTION = "run"
            def run(self, model, conditioning, seed, latent):
                guider = CFGGuider(model)
                guider.set_conds(conditioning, [])
                return (guider.sample(latent, latent, None, torch.tensor([1., 0.]), seed=seed),)

        class Output:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"latent": ("LATENT",)}}
            RETURN_TYPES = ()
            OUTPUT_NODE = True
            FUNCTION = "run"
            def run(self, latent):
                received.append(latent)
                return ()

        prompt = {
            "models": {"class_type": "TestScheduleModels", "inputs": {}},
            "low_ref": {"class_type": "TestScheduleReference", "inputs": {"tag": "encode_low"}},
            "high_ref": {"class_type": "TestScheduleReference", "inputs": {"tag": "encode_high"}},
            "low_model": {"class_type": "YtonH3PrepareSampling", "inputs": {
                "model": ["models", 0], "clip": ["models", 1],
                "conditioning": ["low_ref", 0], "additional_conditioning": ["high_ref", 0]}},
            "high_model": {"class_type": "YtonH3PrepareSampling", "inputs": {
                "model": ["models", 0], "clip": ["models", 1], "conditioning": ["high_ref", 0]}},
            "low": {"class_type": "TestScheduleSampler", "inputs": {
                "model": ["low_model", 0], "conditioning": ["low_ref", 0],
                "seed": 1, "latent": ["models", 2]}},
            "high": {"class_type": "TestScheduleSampler", "inputs": {
                "model": ["high_model", 0], "conditioning": ["high_ref", 0], "seed": 2, "latent": ["low", 0]}},
            "out": {"class_type": "TestScheduleOutput", "inputs": {"latent": ["high", 0]}},
        }

        def release(target):
            nonlocal te_loaded
            self.assertIs(target, clip.patcher)
            self.assertIn("encode_low", events)
            self.assertIn("encode_high", events)
            te_loaded = False
            events.append("release_te")

        def outer(guider, noise, latent, sampler, sigmas, denoise_mask, callback, disable_pbar, seed, latent_shapes=None):
            self.assertFalse(te_loaded)
            events.append(f"sample_{seed}")
            return latent + seed

        mapping = {"TestScheduleModels": Models, "TestScheduleReference": Reference,
                   "TestScheduleSampler": Sampler, "TestScheduleOutput": Output,
                   "YtonH3PrepareSampling": YtonH3PrepareSampling}
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, mapping), patch.object(CFGGuider, "outer_sample", outer):
            with patch("video_context_test.sampling_runtime.model_management.unload_model_and_clones", side_effect=release):
                executor = execution.PromptExecutor(Mock(client_id=None, last_node_id=None),
                                                    cache_type=execution.CacheType.CLASSIC,
                                                    cache_args={"ram": 0, "ram_inactive": 0})
                asyncio.run(executor.execute_async(prompt, "first", execute_outputs=["out"]))
                self.assertTrue(executor.success, executor.status_messages)
                self.assertEqual(events[-4:], ["release_te", "sample_1", "release_te", "sample_2"])
                self.assertEqual(received[-1].item(), 3)

                # Another branch may have loaded TE while the MODEL output stayed cached.
                te_loaded = True
                second = copy.deepcopy(prompt)
                second["high"]["inputs"]["seed"] = 3
                asyncio.run(executor.execute_async(second, "second", execute_outputs=["out"]))
                self.assertTrue(executor.success, executor.status_messages)
                self.assertEqual(events[-2:], ["release_te", "sample_3"])
                self.assertEqual(events.count("sample_1"), 1)
                self.assertEqual(events.count("encode_low"), 1)
                self.assertEqual(events.count("encode_high"), 1)
                self.assertEqual(received[-1].item(), 4)


if __name__ == "__main__":
    unittest.main()
