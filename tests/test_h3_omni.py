"""CPU checks for actual expansion, latent preservation and atomic context files."""
import importlib.util
from fractions import Fraction
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
COMFY = PLUGIN.parents[1]
sys.path.insert(0, str(COMFY))
sys.argv = [sys.argv[0], "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()
import folder_paths
import torch
from comfy.nested_tensor import NestedTensor
from comfy_api.latest import InputImpl, Types
from safetensors.torch import load_file

folder_paths.add_model_folder_path("latent_upscale_models", str(COMFY / "models/latent_upscale_models"))
package = types.ModuleType("omni_test_package")
package.__path__ = [str(PLUGIN / "h3_director")]
sys.modules[package.__name__] = package
from omni_test_package import omni_context, omni_runtime

spec = importlib.util.spec_from_file_location("head_replace", PLUGIN.parent / "ComfyUI-MiniMax-Tools/minimax_latent_head_replace.py")
head_replace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(head_replace)


def defaults(**overrides):
    values = {}
    for name, definition in omni_runtime.YtonH3OmniGenerate.INPUT_TYPES()["required"].items():
        options = definition[1] if len(definition) > 1 else {}
        if "default" in options:
            values[name] = options["default"]
        elif isinstance(definition[0], list):
            values[name] = definition[0][0]
    values["model_loader"] = ["loader", 0]
    return dict(values, **overrides)


def expanded(**overrides):
    result = omni_runtime.YtonH3OmniGenerate().generate(**defaults(**overrides))
    return {key.split(".")[-1]: value for key, value in result["expand"].items()}, result


class ExpansionTests(unittest.TestCase):
    def test_single_first_segment_has_one_sampler_and_no_context_or_face_work(self):
        graph, _ = expanded()
        self.assertEqual(sum(n["class_type"] == "SamplerCustomAdvanced" for n in graph.values()), 1)
        self.assertNotIn("previous", graph)
        self.assertNotIn("main_context", graph)
        self.assertNotIn("upscale", graph)
        self.assertNotIn("face_0_crop", graph)
        self.assertEqual(graph["trim"]["inputs"]["trim_frames"], 0)
        self.assertEqual(graph["reference"]["inputs"]["width"], 1344)

    def test_two_pass_continuation_uses_two_distinct_saved_stages(self):
        graph, result = expanded(sampling_mode="二采", clip_index=2, width=1280, height=704)
        self.assertEqual(sum(n["class_type"] == "SamplerCustomAdvanced" for n in graph.values()), 2)
        self.assertEqual(graph["reference"]["inputs"]["width"], 800)
        self.assertEqual(graph["reference"]["inputs"]["height"], 448)
        self.assertEqual(graph["upscale"]["inputs"]["mode.width"], 1280)
        self.assertEqual(graph["upscale"]["inputs"]["mode.height"], 704)
        for key, slot in (("main_context", 0), ("high_context", 1)):
            inputs = graph[key]["inputs"]
            self.assertTrue(inputs["latent_tail"][0].endswith("previous"))
            self.assertEqual(inputs["latent_tail"][1], slot)
            self.assertEqual((inputs["replace_frames"], inputs["head_mask_strength"], inputs["apply_mask"], inputs["replace_audio"]), (22, 0, True, False))
        self.assertTrue(graph["main"]["inputs"]["latent_image"][0].endswith("main_context"))
        self.assertTrue(graph["high_sample"]["inputs"]["latent_image"][0].endswith("high_context"))
        self.assertTrue(graph["high_context"]["inputs"]["latent_base"][0].endswith("high_av"))
        self.assertEqual(graph["trim"]["inputs"]["trim_frames"], 22)
        self.assertEqual(graph["save_context"]["inputs"]["final_latent"], result["result"][1])
        self.assertTrue(graph["save_context"]["inputs"]["video"][0].endswith("video"))

    def test_explicit_candidate_context_and_custom_schedules(self):
        main = torch.tensor([1.0, 0.7, 0.0])
        second = torch.tensor([0.4, 0.0])
        graph, _ = expanded(sampling_mode="二采", context_path="chosen/clip_00003.safetensors",
                            sigmas=main, second_sigmas=second)
        self.assertEqual(graph["previous"]["inputs"]["context_path"], "chosen/clip_00003.safetensors")
        self.assertNotIn("schedule", graph)
        self.assertNotIn("high_sigmas", graph)
        self.assertIs(graph["main"]["inputs"]["sigmas"], main)
        self.assertIs(graph["high_sample"]["inputs"]["sigmas"], second)

    def test_multiple_faces_chain_and_use_patched_model(self):
        graph, _ = expanded(face_refine=True, face_count=2, face_reverse=True, image=["references", 0])
        self.assertEqual(sum(n["class_type"] == "H3FaceTrackCrop" for n in graph.values()), 2)
        self.assertTrue(graph["face_1_crop"]["inputs"]["images"][0].endswith("face_0_stitch"))
        for index in range(2):
            prefix = f"face_{index}_"
            self.assertEqual(graph[prefix + "crop"]["inputs"]["select_index"], index)
            self.assertEqual(graph[prefix + "guider"]["inputs"]["model"][1], 2)
            self.assertEqual(graph[prefix + "sample"]["inputs"]["latent_image"][1], 0)
            self.assertEqual(graph[prefix + "reference"]["inputs"]["image"], ["references", 0])
            self.assertEqual(graph[prefix + "av"]["inputs"]["audio_latent"][1], 1)
        self.assertTrue(graph["trim"]["inputs"]["images"][0].endswith("face_restore_order"))
        self.assertTrue(graph["sound"]["inputs"]["samples"][0].endswith("main"))
        self.assertEqual(graph["save_context"]["inputs"]["main_latent"], graph["save_context"]["inputs"]["final_latent"])

    def test_minimum_duration_still_delivers_frames_after_context_trim(self):
        for seconds in (0.21, 1, 5, 7, 10):
            graph, _ = expanded(duration=seconds, clip_index=2)
            length = graph["reference"]["inputs"]["length"]
            self.assertEqual(length % 17, 5)
            self.assertGreater(length, 22)

    def test_replica_uses_first_video_duration_and_aligns_tail(self):
        video = InputImpl.VideoFromComponents(Types.VideoComponents(
            images=torch.zeros(125, 4, 4, 3), frame_rate=Fraction(24)))
        for overlap in (0, 22):
            length, trim = omni_runtime.YtonH3ReplicaPlan().plan([video], [overlap])
            self.assertEqual(length % 17, 5)
            self.assertGreaterEqual(trim, overlap)
            self.assertEqual(length - trim, 125)
        graph, _ = expanded(mode="复刻模式", video=["source", 0], clip_index=2)
        self.assertEqual(graph["replica"]["inputs"]["context_frames"], 22)
        self.assertEqual(graph["trim"]["inputs"]["trim_frames"][1], 1)


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.output = patch.object(folder_paths, "get_output_directory", return_value=self.temporary.name)
        self.output.start()

    def tearDown(self):
        self.output.stop()
        self.temporary.cleanup()

    def latent(self, size=2, offset=0):
        video = torch.arange(12 * size * size).reshape(1, 1, 12, size, size).float() + offset
        audio = torch.arange(20).reshape(1, 1, 1, 20).float() + offset
        return {"samples": NestedTensor((video, audio))}

    def video(self, size=32):
        return InputImpl.VideoFromComponents(Types.VideoComponents(
            images=torch.linspace(0, 1, 8).reshape(8, 1, 1, 1).expand(8, size, size, 3), frame_rate=Fraction(24)))

    def test_single_and_two_pass_roundtrip_and_ui_reference(self):
        for mode in ("单采", "二采"):
            main = self.latent()
            final = main if mode == "单采" else self.latent(4, 1000)
            size = 32 if mode == "单采" else 64
            result = omni_context.YtonH3SaveOmniContext().save(self.video(size), main, final, mode, "task", 1)
            self.assertEqual(result["result"][0], "task/clip_00001.safetensors")
            self.assertEqual(result["ui"]["h3_omni_context"][0]["clip_index"], 1)
            restored_main, restored_final, tail, count = omni_context.YtonH3LoadOmniContext().load(
                result["result"][0], 32, 32, size, size)
            for restored, expected in ((restored_main, main), (restored_final, final)):
                for a, b in zip(restored["samples"].unbind(), expected["samples"].unbind()):
                    self.assertTrue(torch.equal(a, b))
            self.assertEqual(count, 4)
            self.assertTrue(torch.allclose(tail, self.video(size).get_components().images[-4:], atol=0.0005))
            tensors = load_file(str(Path(self.temporary.name) / result["result"][0]))
            self.assertEqual("final.video" in tensors, mode == "二采")

    def test_real_head_replace_preserves_exactly_seven_tokens_at_each_resolution(self):
        for size in (2, 4):
            previous = self.latent(size, 1000)
            base = self.latent(size)
            expected_video, expected_audio = base["samples"].unbind()
            result, = head_replace.MiniMaxH3LatentHeadReplace().process_latent(
                22, 0.0, True, False, latent_tail=previous, latent_base=base)
            video, audio = result["samples"].unbind()
            mask, _ = result["noise_mask"].unbind()
            self.assertTrue(torch.equal(video[:, :, :7], previous["samples"].unbind()[0][:, :, -7:]))
            self.assertTrue(torch.equal(video[:, :, 7:], expected_video[:, :, 7:]))
            self.assertTrue(torch.equal(audio, expected_audio))
            self.assertEqual(mask[:, :, :7].sum().item(), 0)
            self.assertTrue(torch.all(mask[:, :, 7:] == 1))

    def test_failed_write_keeps_previous_context_and_cleans_temporary_file(self):
        saver = omni_context.YtonH3SaveOmniContext()
        args = (self.video(), self.latent(), self.latent(), "单采", "task", 1)
        saver.save(*args)
        path = Path(self.temporary.name) / "task/clip_00001.safetensors"
        before = path.read_bytes()

        def partial_write(tensors, filename, metadata):
            Path(filename).write_bytes(b"partial")
            raise OSError("disk full")

        with patch.object(omni_context, "save_file", side_effect=partial_write):
            with self.assertRaisesRegex(OSError, "disk full"):
                saver.save(*args)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_context_path_and_resolution_validation(self):
        with self.assertRaises(ValueError):
            omni_context.context_file("../outside.safetensors")
        omni_context.YtonH3SaveOmniContext().save(self.video(), self.latent(), self.latent(), "单采", "task", 1)
        with self.assertRaisesRegex(ValueError, "分辨率"):
            omni_context.YtonH3LoadOmniContext().load("task/clip_00001.safetensors", 64, 32, 32, 32)

    def test_overwriting_previous_candidate_invalidates_outer_node_cache(self):
        saver = omni_context.YtonH3SaveOmniContext()
        args = (self.video(), self.latent(), self.latent(), "单采", "task", 1)
        saver.save(*args)
        before = omni_runtime.YtonH3OmniGenerate.IS_CHANGED("task", 2)
        path = Path(self.temporary.name) / "task/clip_00001.safetensors"
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
        self.assertNotEqual(before, omni_runtime.YtonH3OmniGenerate.IS_CHANGED("task", 2))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
