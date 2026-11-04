"""Public catalog stays compact while expansion nodes remain registered."""
import importlib.util
from pathlib import Path
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("node_catalog", PLUGIN / "node_catalog.py")
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class CatalogTests(unittest.TestCase):
    def test_public_categories_and_internal_visibility(self):
        classes = {
            name: type(name, (), {"CATEGORY": category}) for name, category in (
                ("YtonResolutionSelector", "yton-nodes/Resolution"),
                ("YtonInputSwitch", "yton-nodes/Logic"),
                ("YtonEasyMediaLoader", "yton-nodes/Media"),
                ("YtonVideoParser", "yton-nodes/Media/解析"),
                ("YtonH3TraditionalOmniGenerate", "yton-nodes/MiniMax H3"),
                ("YtonH3VideoContextOmniGenerate", "yton-nodes/MiniMax H3"),
                ("YtonH3SegmentTrim", "yton-nodes/MiniMax H3"),
                ("YtonH3SaveOmniContext", "yton-nodes/MiniMax H3"),
            )
        }
        catalog.configure_node_catalog(classes)
        for name in ("YtonH3SegmentTrim", "YtonH3SaveOmniContext"):
            self.assertTrue(classes[name].DEV_ONLY)
            self.assertEqual(classes[name].CATEGORY, "yton-nodes/MiniMax H3/内部")
        public = {node.CATEGORY for node in classes.values() if not getattr(node, "DEV_ONLY", False)}
        self.assertEqual(public, {"yton-nodes/分辨率", "yton-nodes/逻辑", "yton-nodes/媒体",
                                  "yton-nodes/媒体/解析", "yton-nodes/MiniMax H3"})

if __name__ == "__main__":
    unittest.main()
