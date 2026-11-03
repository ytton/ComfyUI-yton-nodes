"""CPU checks for the integrated H3 reference preparation node."""

import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from fractions import Fraction
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
if "--cpu" not in sys.argv:
    sys.argv.append("--cpu")
package = types.ModuleType("studio_test_nodes")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
nodes_package = types.ModuleType("studio_test_nodes.nodes")
nodes_package.__path__ = [str(ROOT / "nodes")]
sys.modules[nodes_package.__name__] = nodes_package
module = importlib.import_module("studio_test_nodes.nodes.h3_reference_studio_node")
Studio = module.YtonH3ReferenceStudio
VideoConfig = module.YtonH3VideoConfig

import torch
import folder_paths
from PIL import Image
from comfy_api.latest import InputImpl, Types, io


class Clip:
    def tokenize(self, prompt, minimax_ref_items):
        self.prompt, self.references = prompt, minimax_ref_items
        return prompt

    def encode_from_tokens_scheduled(self, tokens):
        return [[torch.zeros(1, 2, 4), {}]]


class StudioTests(unittest.TestCase):
    def inputs(self, **extra):
        return dict(clip=Clip(), prompt="参考 <Picture 1>", aspect_ratio="16:9", resolution="480p",
                    ref_image_size="match", ref_scale=0.5,
                    duration=5, **extra)

    def execute(self, **extra):
        inputs = self.inputs()
        inputs.update(extra)
        return Studio.execute(**inputs)

    def mocked(self, media, **extra):
        with patch.object(module.YtonEasyMediaLoader, "load_media", return_value=media), \
             patch.object(module.MiniMaxH3ReferenceToVideo, "execute", return_value=io.NodeOutput("positive", "latent")) as native:
            output = self.execute(**extra)
        return output, native.call_args.kwargs

    def test_empty_media_uses_native_text_generation(self):
        clip = Clip()
        result = self.execute(clip=clip)
        self.assertEqual(len(clip.references), 0)
        self.assertEqual(result.result[2:], (864, 480))
        self.assertIn("samples", result.result[1])
        self.assertEqual(result.result[0][0][0].shape, (1, 2, 4))

    def test_preset_dimensions_and_fractional_duration(self):
        for duration, frames in [(7.91, 192), (8.001, 209)]:
            with self.subTest(duration=duration):
                result, native = self.mocked(([], [], []), resolution="1080p", aspect_ratio="9:16", duration=duration)
                self.assertEqual(result.result, ("positive", "latent", 1088, 1920))
                self.assertEqual((native["width"], native["height"], native["length"]), (1088, 1920, frames))

    def test_auto_ratio_uses_first_enabled_image(self):
        image = torch.zeros(1, 128, 72, 3)
        result, _ = self.mocked(([None, image], [], []), aspect_ratio="auto")
        self.assertEqual(result.result[2:4], (480, 864))

    def test_match_and_max_keep_original_images_for_native_sizing(self):
        image = torch.zeros(1, 64, 96, 3)
        for mode in ["match", "max"]:
            with self.subTest(mode=mode):
                _, native = self.mocked(([image], [], []), ref_image_size=mode)
                self.assertIs(native["ref_images"]["ref_image_1"], image)
                self.assertEqual(native["ref_image_size"], mode)

    def test_custom_reference_scale_halves_match_dimensions(self):
        image = torch.zeros(1, 640, 1152, 3)
        _, native = self.mocked(([None, image], [], []), resolution="640p", ref_image_size="自定义", ref_scale=0.5)
        self.assertIsNone(native["ref_images"]["ref_image_1"])
        self.assertEqual(native["ref_images"]["ref_image_2"].shape, (1, 320, 576, 3))
        self.assertEqual(native["ref_image_size"], "max")

    def test_video_resamples_to_24fps_and_keeps_soundtrack(self):
        audio = {"waveform": torch.zeros(1, 1, 320), "sample_rate": 32000}
        video = InputImpl.VideoFromComponents(Types.VideoComponents(
            images=torch.zeros(30, 32, 32, 3), frame_rate=Fraction(30), audio=audio))
        _, native = self.mocked(([], [None, video], [None, audio]))
        self.assertIsNone(native["ref_videos"]["ref_video_1"])
        self.assertEqual(native["ref_videos"]["ref_video_2"].shape[0], 24)
        self.assertIs(native["ref_video_audios"]["ref_video_audio_2"], audio)
        self.assertIs(native["ref_audios"]["ref_audio_2"], audio)

    def test_media_loader_reads_files_and_honors_disabled_slots(self):
        with tempfile.TemporaryDirectory(dir=folder_paths.get_input_directory()) as folder:
            first = Path(folder) / "portrait.png"
            Image.new("RGB", (64, 128)).save(first)
            filename = first.relative_to(folder_paths.get_input_directory()).as_posix()
            clip = Clip()
            result = self.execute(clip=clip, aspect_ratio="auto", image_1=filename,
                                  image_2="unused.png", disable_image_2=True)
            self.assertEqual(result.result[2:4], (480, 864))
            self.assertEqual(len(clip.references), 1)
            fingerprint = Studio.fingerprint_inputs(image_1=filename, prompt="prompt")
            self.assertEqual(fingerprint[0][2], str(first))

    def test_schema_has_model_inputs_media_controls_and_four_outputs(self):
        info = Studio.GET_NODE_INFO_V1()
        self.assertEqual(info["output"], ["CONDITIONING", "LATENT", "INT", "INT"])
        self.assertEqual(info["input"]["optional"]["vae"][0], "VAE")
        self.assertIn("disable_audio_3", info["input"]["required"])
        self.assertIn("16:9|1080p", info["input"]["required"]["resolution"][1]["yton_presets"])
        resolution = info["input"]["required"]["resolution"][1]
        self.assertEqual(resolution["options"], ["320p", "480p", "540p", "640p", "720p", "768p", "944p", "1024p", "1080p"])
        self.assertEqual(resolution["yton_h3_multipliers"]["1080p"], 2.0)
        self.assertNotIn("custom_width", info["input"]["required"])

    def test_video_config_outputs_h3_dimensions_frames_and_reference_settings(self):
        image = torch.zeros(1, 128, 72, 3)
        result = VideoConfig.execute("生成提示词", False, "1080p", "9:16", "自定义", 0.75, 7.91, image=image)
        self.assertEqual(result.result[:7], ("生成提示词", 1088, 1920, 192, 8, "max", 0.75))
        self.assertEqual(result.result[7][0].shape, (1, 96, 64, 3))
        self.assertEqual(result.ui["h3_video_config"][0]["width"], 1088)
        auto = VideoConfig.execute("", False, "480p", "auto", "match", 0.5, 5, image=[None, image])
        self.assertEqual(auto.result[1:7], (480, 864, 124, 124 / 24, "match", 0.5))
        fallback = VideoConfig.execute("", False, "480p", "auto", "match", 0.5, 5)
        self.assertEqual(fallback.result[1:3], (864, 480))

    def test_video_config_passes_three_media_lists_to_optimizer_and_outputs_them(self):
        image = torch.zeros(1, 64, 96, 3)
        audio = {"waveform": torch.zeros(1, 1, 320), "sample_rate": 32000}
        video = object()

        class LLM:
            def generate(self, prompt, **kwargs):
                self.prompt, self.kwargs = prompt, kwargs
                return "优化后的提示词"

        llm = LLM()
        encoded = [{"type": "text", "text": "图片 1 / 视频 1 / 音频 1"}]
        with patch.object(module, "media_content", return_value=encoded) as encode:
            result = VideoConfig.execute("原提示词", True, "480p", "16:9", "match", 0.5, 5,
                                         image=[image], video=[video], audio=[audio], llm=[llm])
        encode.assert_called_once_with(image=[image], audio=[audio], video=[video])
        self.assertEqual(result.result[0], "优化后的提示词")
        self.assertIs(result.result[7][0], image)
        self.assertIs(result.result[8][0], video)
        self.assertIs(result.result[9][0], audio)
        self.assertEqual(llm.kwargs["media"], encoded)
        self.assertIn("<Picture N>", llm.prompt)

    def test_video_config_schema_exposes_prompt_parameters_and_auto_ratio_input(self):
        info = VideoConfig.GET_NODE_INFO_V1()
        self.assertEqual(info["output"], ["STRING", "INT", "INT", "INT", "FLOAT", "STRING", "FLOAT", "IMAGE", "VIDEO", "AUDIO"])
        self.assertEqual(info["input"]["optional"]["image"][0], "IMAGE")
        self.assertEqual(info["input"]["optional"]["video"][0], "VIDEO")
        self.assertEqual(info["input"]["optional"]["audio"][0], "AUDIO")
        self.assertEqual(info["input"]["optional"]["llm"][0], "YTON_LLM")
        self.assertIn("prompt", info["input"]["required"])
        self.assertNotIn("prompt", info["input"].get("optional", {}))
        self.assertEqual(info["input"]["required"]["duration"][1]["round"], False)


if __name__ == "__main__":
    sys.argv = [sys.argv[0]]
    unittest.main()
