"""H3 padding and frame-exact restoration without task or overlap metadata."""

from fractions import Fraction
import unittest

import test_character_replacement as fixture
from replacement_test_plugin.nodes.h3_video_length_node import YtonH3VideoLength, adjust


torch = fixture.torch


def video(count, rate=24, audio=True):
    images = torch.arange(count).float().view(-1, 1, 1, 1).expand(-1, 4, 4, 3)
    sound = {"waveform": torch.ones((1, 2, round(count / float(rate) * 48000))), "sample_rate": 48000} if audio else None
    return fixture.InputImpl.VideoFromComponents(fixture.Types.VideoComponents(
        images=images, frame_rate=Fraction(rate), audio=sound))


class H3VideoLengthTests(unittest.TestCase):
    def test_padding_and_restore_matrix(self):
        for count, expected in ((1, 5), (5, 5), (21, 22), (22, 22), (55, 56), (56, 56),
                                (174, 175), (200, 209), (345, 345), (346, 362), (1000, 1008)):
            with self.subTest(count=count):
                source = video(count)
                padded = adjust(source)
                self.assertEqual((padded[3], padded[4]), (expected, count))
                self.assertEqual(padded[0].get_frame_rate(), 24)
                self.assertEqual((padded[3] - 5) % 17, 0)
                self.assertTrue(torch.equal(padded[1][:count], source.get_components().images))
                self.assertTrue(torch.equal(padded[1][count:], padded[1][count - 1:count].expand_as(padded[1][count:])))
                self.assertEqual(padded[2]["waveform"].shape[-1], expected * 2000)
                self.assertEqual(torch.count_nonzero(padded[2]["waveform"][..., count * 2000:]), 0)
                restored = adjust(padded[0], padded[4])
                self.assertEqual((restored[3], restored[4]), (count, count))
                self.assertTrue(torch.equal(restored[1], source.get_components().images))
                self.assertTrue(torch.equal(restored[2]["waveform"], source.get_components().audio["waveform"]))

    def test_24fps_conversion_preserves_duration(self):
        for count, rate, expected in ((100, 25, 96), (25, 12, 50), (30, Fraction(30000, 1001), 25)):
            with self.subTest(rate=rate):
                padded = adjust(video(count, rate))
                self.assertEqual(padded[4], expected)
                restored = adjust(padded[0], expected)
                self.assertEqual(restored[0].get_frame_count(), expected)
                self.assertEqual(restored[2]["waveform"].shape[-1], expected * 2000)
                expected_indices = (torch.arange(expected) * Fraction(rate).numerator // (Fraction(rate).denominator * 24)).clamp_max(count - 1)
                self.assertTrue(torch.equal(restored[1][:, 0, 0, 0], expected_indices.float()))

    def test_silent_video_and_long_audio_tail(self):
        result = adjust(video(174, audio=False))
        self.assertIsNone(result[2])
        self.assertIsNone(adjust(result[0], 174)[2])
        source = video(174)
        components = source.get_components()
        components.audio["waveform"] = torch.ones((1, 2, 175 * 2000))
        result = adjust(fixture.InputImpl.VideoFromComponents(components))
        self.assertEqual(torch.count_nonzero(result[2]["waveform"][..., 174 * 2000:]), 0)

    def test_invalid_restore_length_does_not_pad_generation_results(self):
        for value in (-1, 1.5, True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "非负整数"):
                adjust(video(100), value)
        with self.assertRaisesRegex(ValueError, "只有 100 帧"):
            adjust(video(100), 101)

    def test_generic_schema_and_two_node_connection(self):
        definition = YtonH3VideoLength.GET_NODE_INFO_V1()
        self.assertEqual(definition["category"], "yton-nodes/MiniMax H3")
        self.assertEqual(list(definition["input"]["required"]), ["video", "original_frames"])
        self.assertEqual(definition["output"], ["VIDEO", "IMAGE", "AUDIO", "INT", "INT"])
        padded = YtonH3VideoLength.execute(video(174)).result
        restored = YtonH3VideoLength.execute(padded[0], padded[4]).result
        self.assertEqual((padded[3], restored[3]), (175, 174))


if __name__ == "__main__":
    unittest.main(argv=[__file__])
