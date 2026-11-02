"""CPU checks for segment planning, latent preservation and atomic context files."""
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


class SegmentPlanningTests(unittest.TestCase):
    def test_replica_uses_first_video_duration_and_aligns_tail(self):
        video = InputImpl.VideoFromComponents(Types.VideoComponents(
            images=torch.zeros(125, 4, 4, 3), frame_rate=Fraction(24)))
        for overlap in (0, 22):
            length, head, tail = omni_runtime.YtonH3ReplicaPlan().plan([video], [overlap], [True])
            self.assertEqual(length % 17, 5)
            self.assertEqual(head, overlap)
            self.assertGreaterEqual(tail, 0)
            self.assertEqual(length - head - tail, 125)

    def test_included_context_preserves_the_source_timeline_across_all_four_segments(self):
        source = torch.arange(455, dtype=torch.float32).reshape(455, 1, 1, 1)
        output, sounds = [], []
        for start, end in ((0, 141), (119, 260), (238, 379), (357, 455)):
            video = InputImpl.VideoFromComponents(Types.VideoComponents(
                images=source[start:end], frame_rate=Fraction(24)))
            length, head, tail = omni_runtime.YtonH3ReplicaPlan().plan(
                [video], [0 if start == 0 else 22], [False])
            if start:
                self.assertEqual(head, 22)
            self.assertEqual(length, 107 if end == 455 else 141)
            sampled = torch.cat((source[start:end], source[end - 1:end].expand(tail, -1, -1, -1)))
            audio = {"waveform": sampled[:, 0, 0, 0].reshape(1, 1, -1), "sample_rate": 24}
            images, sound = omni_runtime.YtonH3SegmentTrim().trim(sampled, head, tail, audio)
            output.append(images)
            sounds.append(sound["waveform"])
        torch.testing.assert_close(torch.cat(output), source)
        torch.testing.assert_close(torch.cat(sounds, dim=-1).flatten(), source.flatten())

    def test_context_length_switch_only_counts_an_active_context_once(self):
        for target, context, extend, expected in (
            (141, 22, True, (175, 22, 12)),
            (141, 22, False, (141, 22, 0)),
            (141, 0, False, (141, 0, 0)),
            (32, 22, True, (56, 22, 2)),
            (98, 22, False, (107, 22, 9)),
        ):
            with self.subTest(target=target, context=context, extend=extend):
                self.assertEqual(omni_runtime.plan_context_length(target, context, extend), expected)
        with self.assertRaisesRegex(ValueError, "总帧数必须大于上下文帧数"):
            omni_runtime.plan_context_length(22, 22, False)

    def test_segment_plan_keeps_context_at_head_and_alignment_surplus_at_tail(self):
        plan = omni_runtime.YtonH3SegmentPlan().plan(10.0, 2, 22)
        length, head, tail, start, visible = plan
        self.assertEqual((length, head, tail, start, visible), (277, 22, 15, 218, 240))

    def test_segment_trim_keeps_audio_aligned_with_head_and_tail(self):
        images = torch.arange(10, dtype=torch.float32).reshape(10, 1, 1, 1)
        audio = {"waveform": torch.arange(10, dtype=torch.float32).reshape(1, 1, 10),
                 "sample_rate": 24}
        result_images, result_audio = omni_runtime.YtonH3SegmentTrim().trim(
            images, 2, 3, audio, 24.0)
        self.assertEqual(result_images.shape[0], 5)
        self.assertTrue(torch.equal(result_images[:, 0, 0, 0], torch.arange(2, 7).float()))
        self.assertEqual(result_audio["waveform"].shape[-1], 5)
        self.assertTrue(torch.equal(result_audio["waveform"].flatten(), torch.arange(2, 7).float()))


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
            expected_tail_count = min(omni_context.CONTEXT_FRAMES, 8)
            self.assertEqual(count, expected_tail_count)
            self.assertTrue(torch.allclose(tail, self.video(size).get_components().images[-expected_tail_count:], atol=0.0005))
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

    def test_overwriting_previous_candidate_invalidates_context_cache(self):
        saver = omni_context.YtonH3SaveOmniContext()
        args = (self.video(), self.latent(), self.latent(), "单采", "task", 1)
        saver.save(*args)
        before = omni_context.YtonH3LoadOmniContext.IS_CHANGED("task/clip_00001.safetensors")
        path = Path(self.temporary.name) / "task/clip_00001.safetensors"
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
        self.assertNotEqual(before, omni_context.YtonH3LoadOmniContext.IS_CHANGED("task/clip_00001.safetensors"))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
