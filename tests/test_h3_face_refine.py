"""Contracts for standalone H3 refinement and its native expansion entry point."""

import unittest
from unittest.mock import Mock, patch

from test_h3_video_context import torch, execution, asyncio, DynamicPrompt
import nodes
from comfy_api.latest import io
from video_context_test.face_runtime import YtonH3FaceRefine
from video_context_test.omni_video_context_graph import build_video_context_graph
from test_h3_omni_variants import variant_defaults, VARIANTS


class FaceRefineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        YtonH3FaceRefine.GET_SCHEMA()

    def expand(self, **overrides):
        values = dict(images=["frames", 0], model=["model", 0], clip=["clip", 0], vae=["vae", 0])
        values.update(overrides)
        clone = YtonH3FaceRefine.PREPARE_CLASS_CLONE(None)
        result = getattr(clone, clone.FUNCTION)(**values)
        return {key.split(".")[-1]: value for key, value in result.expand.items()}, result

    def test_schema_uses_standard_connections_and_only_four_refinement_controls(self):
        inputs = YtonH3FaceRefine.INPUT_TYPES()
        required = inputs["required"]
        self.assertEqual(set(required), {"images", "prompt", "enabled", "face_count", "sigmas", "reverse"})
        self.assertEqual(required["sigmas"][0], "STRING,SIGMAS")
        self.assertEqual(required["sigmas"][1]["default"], "")
        self.assertEqual(inputs["optional"]["image"][0], "IMAGE")
        self.assertTrue(required["images"][1]["rawLink"])
        self.assertTrue(required["sigmas"][1]["lazy"])
        self.assertNotIn("rawLink", required["sigmas"][1])
        for name in ("model", "clip", "vae"):
            self.assertTrue(inputs["optional"][name][1]["rawLink"])
            self.assertTrue(inputs["optional"][name][1]["lazy"])
        self.assertEqual(list(YtonH3FaceRefine.RETURN_TYPES), ["IMAGE"])

    def test_models_are_needed_only_when_enabled(self):
        clone = YtonH3FaceRefine.PREPARE_CLASS_CLONE(None)
        result = getattr(clone, clone.FUNCTION)(images=["frames", 0], enabled=False)
        self.assertEqual(result.result, (["frames", 0],))
        self.assertEqual(result.expand, {})
        with self.assertRaisesRegex(ValueError, "请连接修脸模型"):
            getattr(clone, clone.FUNCTION)(images=["frames", 0])

    def test_native_expansion_disabled_returns_source_link_without_any_work(self):
        graph, result = self.expand(enabled=False, face_count=3, sigmas="not parsed when off")
        self.assertEqual(graph, {})
        self.assertEqual(result.result, (["frames", 0],))

    def test_shared_crop_and_stitch_use_input_frames_without_audio_dependency(self):
        graph, result = self.expand(prompt="保持面部身份", image=["reference_images", 0])
        self.assertEqual(graph["face_0_crop"]["inputs"]["images"], ["frames", 0])
        self.assertEqual(graph["face_0_reference"]["inputs"]["image"], ["reference_images", 0])
        self.assertEqual(graph["face_0_reference"]["inputs"]["prompt"], "保持面部身份")
        self.assertIsNone(graph["face_0_reference"]["inputs"]["audio_vae"])
        self.assertNotIn("face_audio", graph)
        self.assertNotIn("face_0_av", graph)
        self.assertEqual(graph["face_0_denoise"]["inputs"]["av_latent"][0].split(".")[-1], "face_0_inject")
        stitch = graph["face_0_stitch"]["inputs"]
        self.assertEqual(stitch["base_images"], ["frames", 0])
        self.assertEqual(stitch["paste_region"], "face_only")
        self.assertEqual(result.result[0][0].split(".")[-1], "face_0_stitch")

    def test_default_schedule_and_settings_match_existing_generator(self):
        graph, _ = self.expand()
        self.assertEqual(graph["face_0_schedule"]["inputs"]["steps"], 4)
        self.assertEqual(graph["face_0_schedule"]["inputs"]["denoise"], 0.4)
        self.assertEqual(graph["face_0_sampler"]["inputs"]["sampler_name"], "er_sde")
        self.assertEqual(graph["face_0_noise"]["inputs"]["noise_seed"], 42)
        self.assertEqual(graph["face_0_crop"]["inputs"]["detector"], "bbox\\face_yolov8m.pt")
        self.assertEqual(graph["face_0_denoise"]["inputs"]["denoise_multiplier_large_face"], 0.35)
        self.assertNotIn("image", graph["face_0_reference"]["inputs"])

    def test_wired_sigmas_and_text_reach_all_faces(self):
        for sigmas in ("0.4, 0.2, 0", ["external_sigmas", 0], torch.tensor([0.4, 0.2, 0])):
            graph, _ = self.expand(face_count=2, sigmas=sigmas)
            self.assertNotIn("face_0_schedule", graph)
            self.assertNotIn("face_1_schedule", graph)
            for i in range(2):
                schedule = graph[f"face_{i}_sample"]["inputs"]["sigmas"]
                if isinstance(sigmas, str):
                    self.assertEqual(schedule[0].split(".")[-1], "face_sigmas")
                    self.assertEqual(graph["face_sigmas"]["inputs"]["sigmas"], sigmas)
                elif isinstance(sigmas, torch.Tensor):
                    self.assertIs(schedule, sigmas)
                else:
                    self.assertEqual(schedule, sigmas)

    def test_multiple_people_chain_and_reverse_restores_order(self):
        graph, result = self.expand(face_count=2, reverse=True)
        self.assertEqual(graph["face_reverse"]["inputs"]["images"], ["frames", 0])
        self.assertEqual(graph["face_0_crop"]["inputs"]["images"][0].split(".")[-1], "face_reverse")
        self.assertEqual(graph["face_1_crop"]["inputs"]["images"][0].split(".")[-1], "face_0_stitch")
        self.assertEqual(graph["face_1_crop"]["inputs"]["select_index"], 1)
        self.assertEqual(graph["face_restore_order"]["inputs"]["images"][0].split(".")[-1], "face_1_stitch")
        self.assertEqual(result.result[0][0].split(".")[-1], "face_restore_order")

    def test_comfy_input_mapping_does_not_evaluate_models_or_sigmas_when_disabled(self):
        values = dict(images=["frames", 0], model=["unexecuted_model", 0], clip=["unexecuted_clip", 0],
                      vae=["unexecuted_vae", 0], sigmas=["unexecuted_sigmas", 0], prompt="", enabled=False, face_count=1, reverse=False)
        prompt = DynamicPrompt({"face": {"class_type": "YtonH3FaceRefine", "inputs": values}})
        inputs, missing, _ = execution.get_input_data(values, YtonH3FaceRefine, "face", dynprompt=prompt)
        self.assertIn("sigmas", missing)
        result = asyncio.run(execution._async_map_node_over_list(
            "face-test", "face", YtonH3FaceRefine(), inputs, YtonH3FaceRefine.FUNCTION))[0]
        self.assertEqual(result.result, (["frames", 0],))
        self.assertEqual(result.expand, {})

    def test_native_executor_bypasses_disabled_branch_without_loading_dependencies(self):
        images = torch.zeros(5, 32, 32, 3)
        received = []

        class Source:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {}}
            RETURN_TYPES = ("IMAGE",)
            FUNCTION = "run"
            def run(self):
                return (images,)

        class Unused:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {}}
            RETURN_TYPES = ("MODEL", "CLIP", "VAE", "SIGMAS", "STRING", "IMAGE")
            FUNCTION = "run"
            def run(self):
                raise AssertionError("Disabled face refinement evaluated an unused dependency")

        class Output:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"images": ("IMAGE",)}}
            RETURN_TYPES = ()
            OUTPUT_NODE = True
            FUNCTION = "run"
            def run(self, images):
                received.append(images)
                return ()

        prompt = {
            "source": {"class_type": "TestFaceSource", "inputs": {}},
            "unused": {"class_type": "TestFaceUnused", "inputs": {}},
            "face": {"class_type": "YtonH3FaceRefine", "inputs": {
                "images": ["source", 0], "model": ["unused", 0], "clip": ["unused", 1], "vae": ["unused", 2],
                "sigmas": ["unused", 3], "prompt": ["unused", 4], "image": ["unused", 5],
                "enabled": False, "face_count": 1, "reverse": False}},
            "output": {"class_type": "TestFaceOutput", "inputs": {"images": ["face", 0]}},
        }
        server = Mock(client_id=None, last_node_id=None)
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, {"TestFaceSource": Source, "TestFaceUnused": Unused,
                                                  "TestFaceOutput": Output, "YtonH3FaceRefine": YtonH3FaceRefine}):
            executor = execution.PromptExecutor(server, cache_type=execution.CacheType.NONE,
                                                cache_args={"ram": 0, "ram_inactive": 0})
            asyncio.run(executor.execute_async(prompt, "face-bypass-test", execute_outputs=["output"]))
        self.assertTrue(executor.success, executor.status_messages)
        self.assertEqual(len(received), 1)
        self.assertIs(received[0], images)

        expanded = []

        class Probe(YtonH3FaceRefine):
            @classmethod
            def execute(cls, **inputs):
                expanded.append(super().execute(**inputs).expand)
                return io.NodeOutput(inputs["images"], expand={})

        class SigmaSource:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {}}
            RETURN_TYPES = ("SIGMAS",)
            FUNCTION = "run"
            def run(self):
                return (schedule,)

        prompt["sigma"] = {"class_type": "TestFaceSigma", "inputs": {}}
        prompt["face"]["inputs"].update(enabled=True, sigmas=["sigma", 0])
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, {"TestFaceSource": Source, "TestFaceUnused": Unused,
                                                  "TestFaceOutput": Output, "TestFaceSigma": SigmaSource,
                                                  "YtonH3FaceRefine": Probe}):
            for schedule in ("0.4, 0.2, 0", torch.tensor([0.4, 0.2, 0]), ""):
                SigmaSource.RETURN_TYPES = ("STRING",) if isinstance(schedule, str) else ("SIGMAS",)
                executor = execution.PromptExecutor(server, cache_type=execution.CacheType.NONE,
                                                    cache_args={"ram": 0, "ram_inactive": 0})
                asyncio.run(executor.execute_async(prompt, "face-sigmas-test", execute_outputs=["output"]))
                self.assertTrue(executor.success, executor.status_messages)
                graph = {key.split(".")[-1]: value for key, value in expanded[-1].items()}
                if isinstance(schedule, str) and schedule:
                    self.assertEqual(graph["face_sigmas"]["inputs"]["sigmas"], schedule)
                elif isinstance(schedule, str):
                    self.assertIn("face_0_schedule", graph)
                else:
                    self.assertIs(graph["face_0_sample"]["inputs"]["sigmas"], schedule)

    def test_existing_generators_preserve_original_audio_branch(self):
        for cls in VARIANTS.values():
            result = build_video_context_graph(sampling_plan=cls.SAMPLING_PLAN,
                                               **variant_defaults(cls, face_refine=True))
            graph = {key.split(".")[-1]: value for key, value in result["expand"].items()}
            self.assertEqual(graph["face_0_av"]["inputs"]["audio_latent"][0].split(".")[-1], "face_audio")
            self.assertEqual(graph["face_0_denoise"]["inputs"]["av_latent"][0].split(".")[-1], "face_0_av")


if __name__ == "__main__":
    unittest.main()
