"""Public catalog stays compact while expansion nodes remain registered."""
import ast
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
                ("YuanH3ContextWindowPlan", "yton-nodes/H3"),
                ("YuanH3NikoLoadLatent", "H3-Motion-Context"),
                ("YtonH3SegmentTrim", "yton-nodes/MiniMax H3"),
                ("YtonH3SaveOmniContext", "yton-nodes/MiniMax H3"),
            )
        }
        catalog.configure_node_catalog(classes)
        for name in ("YuanH3ContextWindowPlan", "YuanH3NikoLoadLatent", "YtonH3SegmentTrim", "YtonH3SaveOmniContext"):
            self.assertTrue(classes[name].DEV_ONLY)
            self.assertEqual(classes[name].CATEGORY, "yton-nodes/MiniMax H3/内部")
        public = {node.CATEGORY for node in classes.values() if not getattr(node, "DEV_ONLY", False)}
        self.assertEqual(public, {"yton-nodes/分辨率", "yton-nodes/逻辑", "yton-nodes/媒体",
                                  "yton-nodes/媒体/解析", "yton-nodes/MiniMax H3"})

    def test_alias_visibility_does_not_change_upstream_classes(self):
        tree = ast.parse((PLUGIN / "h3_director/niko_alias.py").read_text(encoding="utf8"))
        wrappers = {item.name for item in tree.body if isinstance(item, ast.ClassDef)}
        mapping = next(item.value for item in tree.body if isinstance(item, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "NODE_CLASS_MAPPINGS" for target in item.targets))
        self.assertTrue(all(isinstance(value, ast.Name) and value.id in wrappers for value in mapping.values))


if __name__ == "__main__":
    unittest.main()
