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
package.__path__ = [str(ROOT / "nodes")]
sys.modules[package.__name__] = package
module = importlib.import_module("studio_test_nodes.h3_reference_studio_node")
Studio = module.YtonH3ReferenceStudio

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
                    custom_width=1344, custom_height=768, ref_image_size="match", ref_scale=0.5,
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
        self.assertEqual(result.result[2:], (864, 480, 124))
        self.assertIn("samples", result.result[1])
        self.assertEqual(result.result[0][0][0].shape, (1, 2, 4))

    def test_preset_dimensions_and_fractional_duration(self):
        result, native = self.mocked(([], [], []), resolution="1080p", aspect_ratio="9:16", duration=7.5)
        self.assertEqual(result.result, ("positive", "latent", 1088, 1920, 192))
        self.assertEqual((native["width"], native["height"], native["length"]), (1088, 1920, 192))

    def test_custom_dimensions_align_and_override_preset(self):
        result, _ = self.mocked(([], [], []), resolution="自定义", custom_width=1000, custom_height=701)
        self.assertEqual(result.result[2:4], (992, 672))

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

    def test_schema_has_model_inputs_media_controls_and_five_outputs(self):
        info = Studio.GET_NODE_INFO_V1()
        self.assertEqual(info["output"], ["CONDITIONING", "LATENT", "INT", "INT", "INT"])
        self.assertEqual(info["input"]["optional"]["vae"][0], "VAE")
        self.assertIn("disable_audio_3", info["input"]["required"])
        self.assertIn("16:9|1080p", info["input"]["required"]["resolution"][1]["yton_presets"])


if __name__ == "__main__":
    sys.argv = [sys.argv[0]]
    unittest.main()
