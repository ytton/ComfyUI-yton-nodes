"""Exercise dynamic media inputs through ComfyUI's list execution path on CPU."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN.parents[1]))
sys.argv = [sys.argv[0], "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()
import execution
import torch

spec = importlib.util.spec_from_file_location("media_lists_test", PLUGIN / "nodes/media_list_node.py")
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


def collect(cls, sources):
    group = cls.define_schema().inputs[0].id
    values = {f"{group}.{name}": [name, 0] for name in sources}
    execution_list = types.SimpleNamespace(get_cache=lambda source, target:
        execution.CacheEntry(ui={}, outputs=(sources[source],)))
    inputs, missing, v3_data = execution.get_input_data(values, cls, "list", execution_list=execution_list)
    assert not missing
    results = asyncio.run(execution._async_map_node_over_list(
        "media-list-test", "list", cls, inputs, "execute", v3_data=v3_data))
    assert len(results) == 1
    return results[0].result[0]


class MediaListTests(unittest.TestCase):
    def test_image_batches_and_upstream_lists_keep_source_order_and_size(self):
        red = torch.ones(2, 8, 16, 3)
        blue = torch.zeros(1, 16, 8, 3)
        last = torch.full((1, 4, 4, 3), 0.5)
        images = collect(media.YtonImageToList, {"image_10": [last], "image_0": [red, blue]})
        self.assertEqual([tuple(image.shape) for image in images],
                         [(1, 8, 16, 3), (1, 8, 16, 3), (1, 16, 8, 3), (1, 4, 4, 3)])
        self.assertEqual([float(image.mean()) for image in images], [1, 1, 0, 0.5])
        self.assertEqual(images[0].untyped_storage().data_ptr(), red.untyped_storage().data_ptr())

    def test_video_objects_are_not_decoded_or_nested(self):
        first, second, third = object(), object(), object()
        videos = collect(media.YtonVideoToList, {"video_2": [third], "video_0": [first, second]})
        self.assertEqual(videos, [first, second, third])

    def test_audio_waveforms_and_sample_rates_are_preserved(self):
        first = {"waveform": torch.zeros(1, 2, 24), "sample_rate": 24000}
        second = {"waveform": torch.ones(1, 1, 48), "sample_rate": 48000}
        audios = collect(media.YtonAudioToList, {"audio_0": [first], "audio_1": [second]})
        self.assertIs(audios[0], first)
        self.assertIs(audios[1], second)

    def test_empty_upstream_media_list_stays_empty(self):
        for cls, name in [(media.YtonImageToList, "image_0"),
                          (media.YtonVideoToList, "video_0"), (media.YtonAudioToList, "audio_0")]:
            self.assertEqual(collect(cls, {name: []}), [])


if __name__ == "__main__":
    unittest.main()
