"""CPU regression tests using ComfyUI's real native VIDEO objects."""

import importlib.util
import sys
import unittest
from fractions import Fraction
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN.parents[1]))
sys.argv = [sys.argv[0], "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()

import torch

spec = importlib.util.spec_from_file_location("replacement", PLUGIN / "nodes/h3_video_replacement_node.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class VideoReplacementTest(unittest.TestCase):
    def video(self, frames, rate=24, audio=True):
        images = torch.arange(frames).view(-1, 1, 1, 1).expand(-1, 4, 4, 3).float()
        samples = round(frames / float(rate) * 48000)
        soundtrack = {"waveform": torch.arange(samples).float().view(1, 1, -1), "sample_rate": 48000} if audio else None
        return module.InputImpl.VideoFromComponents(module.Types.VideoComponents(
            images=images, frame_rate=Fraction(rate), audio=soundtrack))

    def test_padding_and_context_matrix(self):
        for frames, rate in [(124, 24), (125, 24), (3, 24), (101, 25), (101, Fraction(30000, 1001)), (180, 60)]:
            for prefix in (0, 39):
                with self.subTest(frames=frames, rate=rate, prefix=prefix):
                    original = self.video(frames, rate)
                    videos, length, count, match_tail = module.YtonH3VideoReplacementPrepare().prepare(
                        [True], [999], [prefix], [original])
                    expected = -(-(frames * 24 * Fraction(rate).denominator) // Fraction(rate).numerator)
                    self.assertEqual(count, expected)
                    self.assertGreaterEqual(length, count + prefix)
                    self.assertEqual(length % 17, 5)
                    self.assertLess(length - count - prefix, 17 if count + prefix >= 5 else 22)
                    self.assertFalse(match_tail)
                    components = videos[0].get_components()
                    self.assertEqual(components.images.shape[0], length)
                    self.assertTrue(torch.equal(components.images[:prefix], components.images[:1].expand(prefix, -1, -1, -1)))
                    tail = components.images[prefix + count:]
                    self.assertTrue(torch.equal(tail, components.images[prefix + count - 1:prefix + count].expand_as(tail)))
                    wave = components.audio["waveform"]
                    before = prefix * 2000
                    old_wave = original.get_components().audio["waveform"]
                    retained = min(old_wave.shape[-1], count * 2000)
                    self.assertTrue(torch.equal(wave[..., before:before + retained], old_wave[..., :retained]))
                    self.assertEqual(wave.shape[-1], length * 2000)
                    self.assertEqual(torch.count_nonzero(wave[..., :before]), 0)
                    self.assertEqual(torch.count_nonzero(wave[..., before + count * 2000:]), 0)

    def test_disabled_and_missing_video(self):
        self.assertEqual(module.YtonH3VideoReplacementPrepare().prepare([False], [226], [0]), ([], 226, 0, True))
        with self.assertRaisesRegex(ValueError, "第一个视频"):
            module.YtonH3VideoReplacementPrepare().prepare([True], [226], [0], [])
        other = self.video(23, audio=False)
        result = module.YtonH3VideoReplacementPrepare().prepare([False], [226], [39], [None, other])
        self.assertEqual(result, ([None, other], 226, 0, True))

    def test_video_list_identity_and_silent_video(self):
        first, other = self.video(23, audio=False), self.video(22)
        videos, length, count, _ = module.YtonH3VideoReplacementPrepare().prepare([True], [999], [0], [first, None, other])
        self.assertEqual((length, count), (39, 23))
        self.assertIsNone(videos[0].get_components().audio)
        self.assertIsNone(videos[1])
        self.assertIs(videos[2], other)

    def test_official_reference_node_keeps_the_padded_tail(self):
        from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo

        parser_spec = importlib.util.spec_from_file_location("media_parser", PLUGIN / "nodes/media_loader_node.py")
        parser_module = importlib.util.module_from_spec(parser_spec)
        parser_spec.loader.exec_module(parser_module)

        class Clip:
            def tokenize(self, prompt, **kwargs):
                return []

            def encode_from_tokens_scheduled(self, tokens):
                return [[torch.zeros(1, 1), {}]]

        class Vae:
            def encode(self, images):
                self.frames = images
                return torch.zeros(1, 1, (images.shape[0] - 5) // 17 * 5 + 2, 2, 2)

        for prefix in (0, 39):
            videos, length, count, _ = module.YtonH3VideoReplacementPrepare().prepare(
                [True], [999], [prefix], [self.video(125)])
            images, parsed_count, audio, _ = parser_module.YtonVideoParser().parse_video(videos[0], force_rate=24)
            self.assertEqual(parsed_count, length)
            vae = Vae()
            MiniMaxH3ReferenceToVideo.execute(
                clip=Clip(), prompt="", width=32, height=32, length=length,
                vae=vae, ref_videos={"ref_video_1": images},
                ref_video_audios={"ref_video_audio_1": audio})
            self.assertEqual(vae.frames.shape[0], length)
            self.assertTrue(torch.equal(vae.frames[-1], vae.frames[prefix + count - 1]))

    def test_output_trims_audio_without_shifting_or_resampling(self):
        for prefix in (0, 39):
            prepared, length, count, _ = module.YtonH3VideoReplacementPrepare().prepare(
                [True], [999], [prefix], [self.video(125)])
            components = prepared[0].get_components()
            images = components.images[prefix:]
            audio = {**components.audio, "waveform": components.audio["waveform"][..., prefix * 2000:]}
            output, soundtrack = module.YtonH3VideoReplacementTrim().trim(images, count, audio)
            self.assertEqual(output.shape[0], 125)
            self.assertEqual(soundtrack["waveform"].shape[-1], 250000)
            self.assertTrue(torch.equal(soundtrack["waveform"], self.video(125).get_components().audio["waveform"]))
        unchanged = module.YtonH3VideoReplacementTrim().trim(images, 0, audio)
        self.assertIs(unchanged[0], images)
        self.assertIs(unchanged[1], audio)
        short = {"waveform": torch.ones(1, 2, 100), "sample_rate": 48000}
        _, padded = module.YtonH3VideoReplacementTrim().trim(torch.zeros(5, 4, 4, 3), 5, short)
        self.assertEqual(padded["waveform"].shape[-1], 10000)
        self.assertEqual(torch.count_nonzero(padded["waveform"][..., 100:]), 0)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
