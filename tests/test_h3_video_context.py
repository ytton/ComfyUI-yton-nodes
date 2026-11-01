"""Check VIDEO continuation wiring and native frame/audio operations on CPU."""
import asyncio
import importlib.util
from fractions import Fraction
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
COMFY = PLUGIN.parents[1]
sys.path.insert(0, str(COMFY))
sys.argv = [sys.argv[0], "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()
import torch
import execution
from comfy_api.latest import InputImpl, Types
from comfy_execution.graph import DynamicPrompt
from comfy_extras.nodes_images import ImageAddNoise
from comfy_extras.nodes_minimax_h3 import MiniMaxH3AddGuide, _empty_av_latent
from comfy_extras.nodes_post_processing import ColorTransfer

package = types.ModuleType("video_context_test")
package.__path__ = [str(PLUGIN / "h3_director")]
sys.modules[package.__name__] = package
from video_context_test.omni_video_context_runtime import YtonH3VideoContextOmniGenerate, YtonH3VideoTail
from video_context_test.omni_video_context_graph import build_video_context_graph
from video_context_test.omni_runtime import YtonH3SegmentTrim

feather_package = types.ModuleType("video_context_feather_test")
feather_package.__path__ = [str(PLUGIN.parent / "ComfyUI-MiniMax-H3-Audio-Guide-Feather")]
sys.modules[feather_package.__name__] = feather_package
spec = importlib.util.spec_from_file_location(
    feather_package.__name__ + ".nodes", Path(feather_package.__path__[0]) / "nodes.py")
feather = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feather)


def defaults(**overrides):
    values = {}
    for name, definition in YtonH3VideoContextOmniGenerate.INPUT_TYPES()["required"].items():
        options = definition[1] if len(definition) > 1 else {}
        if "default" in options:
            values[name] = options["default"]
        elif isinstance(definition[0], list):
            values[name] = definition[0][0]
    values.update(model_loader=["loader", 0], **overrides)
    return values


def expanded(**overrides):
    result = build_video_context_graph(**defaults(**overrides))
    return {key.split(".")[-1]: value for key, value in result["expand"].items()}, result


class VideoContextGraphTests(unittest.TestCase):
    def test_previous_video_is_a_distinct_video_socket(self):
        schema = YtonH3VideoContextOmniGenerate.INPUT_TYPES()
        self.assertNotIn("previous_video", schema["required"])
        self.assertEqual(schema["optional"]["previous_video"][0], "VIDEO")
        self.assertTrue(schema["optional"]["previous_video"][1]["lazy"])
        self.assertEqual(schema["required"]["enable_context"][0], "BOOLEAN")
        self.assertFalse(schema["required"]["enable_context"][1]["default"])
        for name, kind in (("image", "IMAGE"), ("video", "VIDEO"), ("audio", "AUDIO"),
                           ("second_model", "MODEL"), ("face_model", "MODEL")):
            self.assertEqual(schema["optional"][name][0], kind)
        self.assertNotIn("latent_path", schema["required"])
        self.assertNotIn("context_path", schema["optional"])
        self.assertEqual(YtonH3VideoContextOmniGenerate.RETURN_TYPES, ("VIDEO", "LATENT"))

    def test_first_segment_needs_only_its_inputs_and_no_previous_file(self):
        for enabled in (False, True):
            with self.subTest(enable_context=enabled):
                graph, result = expanded(clip_index=2, duration=10, enable_context=enabled)
                self.assertNotIn("previous", graph)
                self.assertNotIn("seamless_color_match", graph)
                self.assertEqual(graph["reference"]["inputs"]["length"], 243)
                self.assertEqual(graph["trim"]["inputs"]["head_trim_frames"], 0)
                self.assertEqual(graph["trim"]["inputs"]["tail_trim_frames"], 3)
                self.assertEqual(len(result["result"]), 2)

    def test_connected_previous_video_is_ignored_while_context_is_off(self):
        for sampling_mode in ("单采", "二采"):
            for source_mode in ("text", "普通模式", "复刻模式"):
                with self.subTest(sampling_mode=sampling_mode, source_mode=source_mode):
                    inputs = {"sampling_mode": sampling_mode, "duration": 10,
                              "previous_video": ["prior_clip", 0]}
                    if source_mode != "text":
                        inputs.update(mode=source_mode, video=["source", 0])
                    graph, _ = expanded(**inputs)
                    self.assertNotIn("previous", graph)
                    self.assertNotIn("seamless_color_match", graph)
                    self.assertNotIn("main_context_add_guide", graph)
                    self.assertNotIn("high_context_add_guide", graph)
                    for node in graph.values():
                        self.assertNotIn(["prior_clip", 0], node["inputs"].values())
                    if source_mode == "text":
                        self.assertEqual(graph["reference"]["inputs"]["length"], 243)
                        self.assertEqual(graph["trim"]["inputs"]["head_trim_frames"], 0)
                        self.assertEqual(graph["trim"]["inputs"]["tail_trim_frames"], 3)
                    else:
                        plan = "segment" if source_mode == "普通模式" else "replica"
                        self.assertEqual(graph[plan]["inputs"]["context_frames"], 0)
                        if source_mode == "普通模式":
                            self.assertEqual(graph["source_components"]["inputs"]["video"], ["source", 0])
                            self.assertIn("source_guide", graph)
                            if sampling_mode == "二采":
                                self.assertEqual(graph["upscale"]["inputs"]["positive"], graph["guider"]["inputs"]["conditioning"])
                        else:
                            self.assertEqual(graph["reference"]["inputs"]["video"], ["source", 0])

    def test_continuation_follows_video_tail_to_both_sampling_guiders(self):
        graph, _ = expanded(previous_video=["prior_clip", 0], enable_context=True, sampling_mode="二采", duration=10)
        self.assertEqual(graph["previous"]["class_type"], "YtonH3VideoTail")
        self.assertEqual(graph["previous"]["inputs"]["video"], ["prior_clip", 0])
        for stage, guider in (("main", "guider"),):
            self.assertEqual(graph[f"{stage}_ctx_context_first"]["inputs"]["num_frames"], 21)
            self.assertEqual(graph[f"{stage}_ctx_context_last"]["inputs"]["start_index"], 21)
            self.assertEqual(graph[f"{stage}_ctx_context_first_noise"]["inputs"]["strength"], 0.1)
            self.assertEqual(graph[f"{stage}_ctx_context_last_exact"]["inputs"]["strength"], 0.0)
            guide = graph[f"{stage}_context_add_guide"]
            self.assertEqual(guide["class_type"], "MiniMaxH3AddGuide")
            self.assertEqual(guide["inputs"]["audio"][1], 1)
            self.assertTrue(guide["inputs"]["audio"][0].endswith("previous"))
            release = graph[f"{stage}_context_add_guide_audio_feather"]
            self.assertEqual(release["inputs"]["audio_feather_ticks"], 256)
            self.assertTrue(graph[guider]["inputs"]["conditioning"][0].endswith(f"{stage}_context_add_guide_audio_feather"))
        self.assertEqual(graph["upscale"]["inputs"]["positive"], graph["guider"]["inputs"]["conditioning"])
        self.assertTrue(graph["high_guider"]["inputs"]["conditioning"][0].endswith("upscale"))
        self.assertEqual(graph["high_guider"]["inputs"]["conditioning"][1], 1)
        self.assertEqual(graph["reference"]["inputs"]["length"], 277)
        self.assertEqual(graph["trim"]["inputs"]["head_trim_frames"], 22)
        self.assertEqual(graph["trim"]["inputs"]["tail_trim_frames"], 15)
        self.assertTrue(graph["seamless_reference_frame"]["inputs"]["images"][0].endswith("previous"))
        self.assertEqual(graph["seamless_reference_frame"]["inputs"]["num_frames"], 1)
        self.assertEqual(graph["seamless_color_match"]["inputs"]["strength"], 0.75)
        self.assertEqual(graph["seamless_color_match"]["inputs"]["source_stats.target_index"], 0)
        self.assertFalse(any(node["class_type"].startswith(("YtonH3Load", "YtonH3Save"))
                             or "LatentHeadReplace" in node["class_type"] for node in graph.values()))

    def test_source_video_and_context_video_stay_separate(self):
        graph, _ = expanded(clip_index=2, duration=10, video=["source", 0], previous_video=["prior_clip", 0], enable_context=True)
        self.assertEqual(graph["segment"]["inputs"]["context_frames"], 22)
        self.assertEqual(graph["source_components"]["inputs"]["video"], ["source", 0])
        self.assertEqual(graph["previous"]["inputs"]["video"], ["prior_clip", 0])
        self.assertNotIn("source_guide", graph)
        graph, _ = expanded(mode="复刻模式", video=["cut_source", 0], previous_video=["prior_clip", 0], enable_context=True)
        self.assertEqual(graph["replica"]["inputs"]["context_frames"], 22)
        self.assertEqual(graph["reference"]["inputs"]["video"], ["cut_source", 0])

    def test_sampling_models_sigmas_and_face_settings_are_preserved(self):
        graph, _ = expanded(sampling_mode="二采", width=1920, height=1088,
                            previous_video=["prior_clip", 0], enable_context=True, sigmas=["sigma", 0],
                            second_sigma_values=["sigma2", 0], second_model=["model2", 0],
                            face_refine=True, face_sigmas=["face_sigma", 0], face_model=["face_model", 0])
        self.assertEqual((graph["reference"]["inputs"]["width"], graph["reference"]["inputs"]["height"]), (960, 544))
        self.assertEqual(graph["upscale"]["class_type"], "MiniMaxH3LatentUpscaleCombined")
        self.assertEqual(graph["upscale"]["inputs"]["learned_model"], "h3_clean_latent_upscaler_film_epoch200.safetensors")
        self.assertEqual(graph["upscale"]["inputs"]["audio_denoise"], 0.0)
        self.assertEqual(graph["upscale"]["inputs"]["positive"], graph["guider"]["inputs"]["conditioning"])
        self.assertEqual(graph["main"]["inputs"]["sigmas"], ["sigma", 0])
        self.assertEqual(graph["high_sample"]["inputs"]["sigmas"], ["sigma2", 0])
        self.assertEqual(graph["high_ff_chunks"]["inputs"]["model"], ["model2", 0])
        self.assertTrue(graph["high_guider"]["inputs"]["model"][0].endswith("high_prepare_sampling"))
        self.assertTrue(graph["high_prepare_sampling"]["inputs"]["model"][0].endswith("high_ff_chunks"))
        self.assertEqual(graph["face_0_denoise"]["inputs"]["model"], ["face_model", 0])
        self.assertEqual(graph["face_0_sample"]["inputs"]["sigmas"], ["face_sigma", 0])


class OptionalMediaRuntimeTests(unittest.TestCase):
    def execute(self, media_outputs, **overrides):
        values = defaults(image=["media", 0], video=["media", 1], audio=["media", 2], **overrides)
        prompt = DynamicPrompt({"omni": {"class_type": "YtonH3VideoContextOmniGenerate", "inputs": values}})
        cache = execution.CacheEntry(ui={}, outputs=media_outputs)
        execution_list = types.SimpleNamespace(get_cache=lambda source, target: cache)
        inputs, missing, _ = execution.get_input_data(values, YtonH3VideoContextOmniGenerate,
                                                     "omni", execution_list=execution_list, dynprompt=prompt)
        self.assertFalse(missing)
        results = asyncio.run(execution._async_map_node_over_list(
            "optional-media-test", "omni", YtonH3VideoContextOmniGenerate(), inputs, "generate"))
        self.assertEqual(len(results), 1)
        return {key.split(".")[-1]: value for key, value in results[0]["expand"].items()}

    def test_image_only_loader_does_not_create_empty_video_or_audio_branches(self):
        image = torch.zeros(1, 32, 32, 3)
        for empty in ([], [None]):
            for sampling_mode in ("单采", "二采"):
                with self.subTest(empty=empty, sampling_mode=sampling_mode):
                    graph = self.execute(([image, image.clone()], empty, empty),
                                         duration=10, sampling_mode=sampling_mode)
                    self.assertNotIn("source_components", graph)
                    self.assertNotIn("source_guide", graph)
                    self.assertNotIn("segment", graph)
                    self.assertEqual(graph["reference"]["inputs"]["image"], ["media", 0])
                    for stage in ("reference",):
                        self.assertNotIn("video", graph[stage]["inputs"])
                        self.assertNotIn("audio", graph[stage]["inputs"])
                    self.assertEqual(graph["reference"]["inputs"]["length"], 243)

    def test_all_empty_connected_sockets_allow_text_to_video(self):
        graph = self.execute(([], [], []))
        for name in ("image", "video", "audio"):
            self.assertNotIn(name, graph["reference"]["inputs"])
        self.assertNotIn("source_components", graph)

    def test_valid_video_still_uses_source_segmentation(self):
        video = InputImpl.VideoFromComponents(Types.VideoComponents(
            images=torch.zeros(60, 32, 32, 3), frame_rate=Fraction(24)))
        graph = self.execute(([], [video], []), duration=1)
        self.assertEqual(graph["source_components"]["inputs"]["video"], ["media", 1])
        self.assertIn("source_guide", graph)

    def test_audio_only_loader_preserves_audio_reference(self):
        audio = {"waveform": torch.zeros(1, 1, 3200), "sample_rate": 32000}
        graph = self.execute(([], [], [audio]))
        self.assertEqual(graph["reference"]["inputs"]["audio"], ["media", 2])
        self.assertNotIn("source_components", graph)
        self.assertNotIn("image", graph["reference"]["inputs"])

    def test_empty_replica_source_reports_missing_video_instead_of_demuxing(self):
        with self.assertRaisesRegex(ValueError, "复刻模式需要传入至少一个视频"):
            self.execute(([], [], []), mode="复刻模式")

    def test_previous_video_is_only_evaluated_when_context_is_enabled(self):
        node = YtonH3VideoContextOmniGenerate()
        for enabled in (False, True):
            with self.subTest(enable_context=enabled):
                values = defaults(enable_context=enabled, image=["media", 0], video=["media", 1],
                                  audio=["media", 2], previous_video=["previous", 0])
                inputs, _, _ = execution.get_input_data(values, type(node), "omni")
                requested = asyncio.run(execution._async_map_node_over_list(
                    "optional-media-test", "omni", node, inputs, "check_lazy_status"))[0]
                self.assertEqual(set(requested), {"image", "video", "audio"}
                                 | ({"previous_video"} if enabled else set()))
                self.assertTrue(type(node).INPUT_TYPES()["optional"]["previous_video"][1]["lazy"])


class NativeVideoOperationsTests(unittest.TestCase):
    def test_video_tail_and_audio_reach_native_h3_guide(self):
        frames = torch.linspace(0.2, 0.8, 60).view(60, 1, 1, 1).expand(60, 32, 32, 3)
        audio = {"waveform": torch.arange(80000).float().view(1, 1, -1).expand(1, 2, -1), "sample_rate": 32000}
        video = InputImpl.VideoFromComponents(Types.VideoComponents(
            images=frames, audio=audio, frame_rate=Fraction(24)))
        with patch.object(video, "get_stream_source", side_effect=AssertionError("unexpected re-encode")):
            tail_frames, tail_audio = YtonH3VideoTail().extract(video)
        self.assertTrue(torch.equal(tail_frames, frames[-22:]))
        expected_start = round(38 / 24 * 32000)
        self.assertEqual(tail_audio["waveform"][0, 0, 0], expected_start)
        noisy = ImageAddNoise.execute(tail_frames[:21], 0, 0.1).result[0]
        last = ImageAddNoise.execute(tail_frames[-1:], 0, 0.0).result[0]
        guide_frames = torch.cat((noisy, last))
        self.assertFalse(torch.equal(guide_frames[:21], tail_frames[:21]))
        self.assertTrue(torch.equal(guide_frames[-1], tail_frames[-1]))

        class VideoVae:
            def encode(self, image):
                self.image = image
                return torch.zeros(1, 24, 7, 2, 2)

        class AudioVae:
            audio_sample_rate = 32000

            def encode(self, waveform):
                self.waveform = waveform
                return torch.zeros(1, 32, 2, 37)

        vae, audio_vae = VideoVae(), AudioVae()
        latent, _ = _empty_av_latent(32, 32, 277)
        positive = MiniMaxH3AddGuide.execute([[torch.zeros(1, 1, 1), {}]], latent, 0,
                                            vae, audio_vae, guide_frames, tail_audio).result[0]
        with patch.object(feather, "ensure_h3_audio_feather_compat"):
            positive = feather.MiniMaxH3AudioGuideFeather.apply(positive, 256).result[0]
        keyframe = positive[0][1]["minimax_keyframes"][0]
        self.assertEqual(keyframe["resolved_frame_index"], 0)
        self.assertEqual(keyframe["audio_feather_ticks"], 256)
        torch.testing.assert_close(vae.image, guide_frames, atol=1 / 255 + 1e-5, rtol=0)
        self.assertTrue(torch.equal(audio_vae.waveform, tail_audio["waveform"].movedim(1, -1)))

    def test_trim_then_colour_match_keeps_exact_duration(self):
        generator = torch.Generator().manual_seed(7)
        images = torch.rand(277, 8, 8, 3, generator=generator) * 0.5 + 0.2
        audio = {"waveform": torch.arange(277).view(1, 1, -1), "sample_rate": 24}
        frames, sound = YtonH3SegmentTrim().trim(images, 22, 15, audio)
        reference = images[21:22] * 0.95
        result = ColorTransfer.execute(frames, reference, "mkl_lab",
                                       {"source_stats": "target_frame", "target_index": 0}, 0.75).result[0]
        self.assertEqual(result.shape[0], 240)
        self.assertTrue(torch.isfinite(result).all())
        self.assertTrue(torch.equal(sound["waveform"].flatten(), torch.arange(22, 262)))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
