"""CPU checks for precise processed frames, persisted selection and segment isolation."""

from copy import deepcopy
import unittest

import av
import numpy as np

import test_character_replacement as fixtures
from replacement_test_plugin.replacement.anchors import anchor_images, editor_preview, frame_preview, segment_info


class AnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ReplacementTests.setUpClass()
        cls.root = fixtures.ReplacementTests.root

    @classmethod
    def tearDownClass(cls):
        fixtures.ReplacementTests.tearDownClass()

    def config(self):
        return fixtures.ReplacementTests().config()

    def test_preview_and_screenshots_match_exact_processed_frames(self):
        from PIL import Image
        config = self.config()
        config["crop"] = [0.2, 0.1, 0.6, 0.8]
        info = editor_preview(config, 0)
        path, fps, count = segment_info(config, 0)
        self.assertEqual((fps, count), (24, 39))
        with av.open(str(path)) as container:
            decoded = [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]
        for frame in (0, 1, 17, count - 1):
            result = frame_preview(config, 0, frame)
            image = self.root / "temp" / result["image"]["subfolder"] / result["image"]["filename"]
            with Image.open(image) as source:
                self.assertTrue(np.array_equal(np.array(source), decoded[frame]))
        self.assertEqual(info["key"], path.stem)
        self.assertEqual(editor_preview(config, 0), info)
        for frame in (-1, count, 1.5):
            with self.assertRaises(ValueError):
                frame_preview(config, 0, frame)

    def test_only_uploaded_images_are_output_in_frame_order(self):
        config = self.config()
        path, _, _ = segment_info(config, 0)
        config["anchors"] = {path.stem: [{"frame": 32, "image": "blue.png"},
            {"frame": 4, "image": ""}, {"frame": 2, "image": "red.png"}]}
        anchors = anchor_images(config, 0)
        self.assertEqual([item["frame"] for item in anchors], [2, 32])
        self.assertEqual(float(anchors[0]["image"][0, 0, 0, 0]), 1)
        self.assertEqual(float(anchors[1]["image"][0, 0, 0, 2]), 1)
        self.assertEqual(anchor_images(config, 1), [])
        changed = deepcopy(config)
        changed["crop"] = [0, 0, 0.5, 1]
        self.assertEqual(anchor_images(changed, 0), [])
        changed = deepcopy(config)
        changed["compression"]["crf"] = 24
        self.assertEqual(anchor_images(changed, 0), [])

    def test_frame_position_resamples_to_h3_axis(self):
        for fps in (12, 30):
            config = self.config()
            config["plan"]["enabled"] = False
            config["compression"]["fps"] = fps
            path, _, _ = segment_info(config, 0)
            config["anchors"] = {path.stem: [{"frame": fps, "image": "red.png"}]}
            self.assertEqual(anchor_images(config, 0)[0]["frame"], 24)

    def test_missing_replacement_file_and_invalid_frame_are_actionable(self):
        config = self.config()
        path, _, count = segment_info(config, 0)
        config["anchors"] = {path.stem: [{"frame": count, "image": "red.png"}]}
        with self.assertRaisesRegex(ValueError, "超出"):
            anchor_images(config, 0)
        config["anchors"][path.stem] = [{"frame": 0, "image": "absent.png"}]
        with self.assertRaises((ValueError, FileNotFoundError)):
            anchor_images(config, 0)


if __name__ == "__main__":
    unittest.main()
