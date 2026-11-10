"""Run with ComfyUI's Python and its root on PYTHONPATH."""

import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import folder_paths
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("h3_image_test_package")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
node_package = types.ModuleType(f"{package.__name__}.nodes")
node_package.__path__ = [str(ROOT / "nodes")]
sys.modules[node_package.__name__] = node_package
module = importlib.import_module(f"{package.__name__}.nodes.h3_image_node")


class H3ImageNodeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="yton-h3-image-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        previous = folder_paths.get_input_directory()
        folder_paths.set_input_directory(directory.name)
        self.addCleanup(folder_paths.set_input_directory, previous)
        Image.new("RGB", (256, 128), "red").save(self.root / "first.png")
        Image.new("RGB", (128, 256), "blue").save(self.root / "third.png")
        Image.new("RGB", (512, 256), "green").save(self.root / "large.png")

    def test_sixteen_slots_and_sparse_reference_numbers(self):
        node = module.YtonH3ImageConfig()
        inputs = node.INPUT_TYPES()
        self.assertEqual(len([name for name in inputs["required"] if name.startswith("image_")]), 16)
        self.assertEqual(len(inputs["optional"]), 16)
        result = node.configure("以 @1 为主体，@3 为配色", "", 4.0, "auto", 0.0, "", "h3-image",
                                image_1="first.png", image_3="third.png")
        images, prompt, width, height = result
        self.assertEqual(len(images), 2)
        self.assertEqual(prompt, "以 参考图 1 为主体，参考图 2 为配色")
        self.assertGreater(width, height)
        self.assertEqual(images[0].shape[1:3], (128, 256))
        self.assertEqual(images[1].shape[1:3], (256, 128))
        self.assertEqual(node.OUTPUT_IS_LIST, (True, False, False, False))

    def test_reference_upscale_and_area_validation(self):
        node = module.YtonH3ImageConfig()
        images, _, width, height = node.configure("画一张图", "", 16.0, "3:4", 4.0, "", "h3-image",
                                                  image_1="large.png")
        self.assertGreaterEqual(images[0].shape[1] * images[0].shape[2], 4_000_000)
        self.assertLessEqual(width * height, 20_000_000)
        self.assertAlmostEqual(width / height, 3 / 4, delta=.01)
        self.assertEqual(module.reference_dimensions(4000, 3000, 4), (4000, 3000))
        self.assertEqual(module.output_dimensions(8, "16:9", []), (3768, 2120))
        self.assertEqual(module.output_dimensions(16, "1:1", []), (4000, 4000))
        with self.assertRaisesRegex(ValueError, "@2"):
            node.configure("使用 @2", "", 8.0, "1:1", 0.0, "", "h3-image", image_1="first.png")
        with self.assertRaisesRegex(ValueError, "4–20 MP"):
            module.output_dimensions(2, "16:9", [])
        self.assertIn("缩放目标", node.VALIDATE_INPUTS(image_1="first.png", reference_target_mp=2.0))
        Image.new("RGB", (100, 100), "white").save(self.root / "small.png")
        self.assertIn("边长或比例", node.VALIDATE_INPUTS(image_1="small.png", reference_target_mp=4.0))

    def test_optimizer_receives_ordered_images_and_skill(self):
        with patch.object(module, "optimize", return_value={"text": "整理后的提示词"}) as optimize:
            with patch.object(module, "get_store", return_value=object()):
                result = module.optimize_h3_image({"prompt": "参考 @3", "image_3": "third.png",
                                                   "model_ref": "model", "reference_target_mp": 0.0,
                                                   "skill_name": "h3-image"})
        self.assertEqual(result["text"], "整理后的提示词")
        self.assertEqual(optimize.call_args.args[1], "参考 参考图 1")
        self.assertEqual(optimize.call_args.kwargs["model_ref"], "model")
        self.assertIn("多张参考图", optimize.call_args.kwargs["skill"])
        self.assertEqual(len(optimize.call_args.kwargs["media"]), 2)


if __name__ == "__main__":
    unittest.main()
