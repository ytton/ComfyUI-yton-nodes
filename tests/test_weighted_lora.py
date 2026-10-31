"""LoRA ordering, native loader expansion, and wired strength precedence."""

import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
spec = importlib.util.spec_from_file_location("weighted_lora", ROOT / "nodes/weighted_lora_node.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Loader = module.YtonWeightedLoraLoader
from comfy_api.latest._io import build_nested_inputs, get_finalized_class_inputs


def row(slot, strength=1, enabled=True):
    return {"slot": slot, "lora": f"test_{slot}.safetensors", "strength": strength, "enabled": enabled}


class WeightedLoraTests(unittest.TestCase):
    def expand(self, rows, **kwargs):
        with patch.object(module.folder_paths, "get_full_path_or_raise", return_value="test.safetensors"):
            return Loader.execute("model", json.dumps(rows), **kwargs)

    def test_empty_stack_and_optional_clip(self):
        result = self.expand([])
        self.assertEqual(result.result, ("model", None))
        self.assertEqual(result.expand, {})
        self.assertIn("clip", Loader.INPUT_TYPES()["optional"])

    def test_model_only_stack_preserves_order(self):
        result = self.expand([row(4, 0.85), row(1, -0.5)])
        nodes = list(result.expand.values())
        self.assertEqual([n["class_type"] for n in nodes], ["LoraLoaderModelOnly"] * 2)
        self.assertEqual([n["inputs"]["lora_name"] for n in nodes], ["test_4.safetensors", "test_1.safetensors"])
        self.assertEqual(nodes[1]["inputs"]["model"], [list(result.expand)[0], 0])
        self.assertEqual(result.result[1], None)

    def test_connected_strength_replaces_inline_and_clip_uses_same_value(self):
        result = self.expand([row(5, 0.85)], clip="clip", strengths={"strength_5": 1.5})
        node = next(iter(result.expand.values()))
        self.assertEqual(node["class_type"], "LoraLoader")
        self.assertEqual(node["inputs"]["strength_model"], 1.5)
        self.assertEqual(node["inputs"]["strength_clip"], 1.5)
        self.assertEqual(node["inputs"]["clip"], "clip")
        self.assertEqual(result.result[1], [next(iter(result.expand)), 1])

    def test_clip_and_model_both_chain(self):
        result = self.expand([row(0), row(8)], clip="clip")
        first, second = result.expand.values()
        self.assertEqual(second["inputs"]["clip"], [next(iter(result.expand)), 1])
        self.assertEqual(first["inputs"]["model"], "model")

    def test_disabled_and_zero_rows_do_not_load(self):
        with patch.object(module.folder_paths, "get_full_path_or_raise") as resolve:
            result = Loader.execute("model", json.dumps([row(0, enabled=False), row(1), row(2, 0)]),
                                    strengths={"strength_1": 0})
        self.assertEqual(result.expand, {})
        resolve.assert_not_called()

    def test_strength_uses_stable_slot_instead_of_row_index(self):
        result = self.expand([row(9, 0.4), row(2, 0.7)], strengths={"strength_2": 0.2})
        self.assertEqual([n["inputs"]["strength_model"] for n in result.expand.values()], [0.4, 0.2])

    def test_file_resolution_is_required_before_loading(self):
        with patch.object(module.folder_paths, "get_full_path_or_raise", side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                Loader.execute("model", json.dumps([row(0)]))

    def test_duplicate_or_invalid_slot_is_rejected(self):
        for rows in [[row(0), row(0)], [row(-1)], [row(100)]]:
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "接口编号"):
                self.expand(rows)

    def test_non_finite_strength_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "有限数值"):
            self.expand([row(0)], strengths={"strength_0": float("nan")})

    def test_dynamic_strength_schema_accepts_no_connections(self):
        schema = Loader.INPUT_TYPES()["optional"]["strengths"]
        self.assertEqual(schema[0], "COMFY_AUTOGROW_V3")
        self.assertEqual(schema[1]["template"]["min"], 0)

    def test_native_api_groups_wired_strengths_by_slot(self):
        live = {"model": "model", "loras": json.dumps([row(5), row(2)]),
                "strengths.strength_2": 0.6, "strengths.strength_5": -0.2}
        inputs, _, data = get_finalized_class_inputs(Loader.INPUT_TYPES(), live)
        self.assertEqual(inputs["optional"]["strengths.strength_2"][0], "FLOAT")
        nested = build_nested_inputs(live, data)
        self.assertEqual(nested["strengths"], {"strength_2": 0.6, "strength_5": -0.2})
        with patch.object(module.folder_paths, "get_full_path_or_raise", return_value="test.safetensors"):
            result = Loader.execute(**nested)
        self.assertEqual([n["inputs"]["strength_model"] for n in result.expand.values()], [-0.2, 0.6])

    def test_native_api_maps_unconnected_strengths_to_empty_dict(self):
        live = {"model": "model", "loras": "[]"}
        _, _, data = get_finalized_class_inputs(Loader.INPUT_TYPES(), live)
        self.assertEqual(build_nested_inputs(live, data)["strengths"], {})


if __name__ == "__main__":
    unittest.main()
