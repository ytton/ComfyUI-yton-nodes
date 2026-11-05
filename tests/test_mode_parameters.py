"""Mode changes preserve output identity, value types and parameter count."""

import asyncio
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from comfy_api.latest import io
from execution import merge_result_data, validate_prompt
import nodes


spec = importlib.util.spec_from_file_location(
    "mode_parameters_node", Path(__file__).resolve().parents[1] / "nodes" / "mode_parameters_node.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Node = module.YtonModeParameters


def configuration():
    return {
        "options": [{"id": "a", "label": "普通"}, {"id": "b", "label": "人物替换"}],
        "outputs": [
            {"id": "strength", "label": "LoRA强度", "type": "FLOAT"},
            {"id": "prompt", "label": "系统提示词", "type": "STRING"},
            {"id": "mask", "label": "启用遮罩", "type": "BOOLEAN"},
            {"id": "context", "label": "启用上下文", "type": "BOOLEAN"},
            {"id": "steps", "label": "步数", "type": "INT"},
        ],
        "values": {
            "a": {"strength": 0, "prompt": "普通提示词", "mask": False, "context": False, "steps": 7},
            "b": {"strength": 0.9, "prompt": "第一行\n第二行：角色替换", "mask": True, "context": False, "steps": 9},
        },
    }


class TypedConsumer(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="ModeParametersTestConsumer",
            is_output_node=True,
            inputs=[
                io.String.Input("mode"), io.Int.Input("index"),
                io.Float.Input("strength"), io.String.Input("prompt"),
                io.Boolean.Input("mask"), io.Boolean.Input("context"), io.Int.Input("steps"),
            ],
        )

    @classmethod
    def execute(cls, **kwargs):
        return io.NodeOutput()


class ModeParametersTests(unittest.TestCase):
    def run_mode(self, data=None, selected="b"):
        return Node.execute(json.dumps(configuration() if data is None else data, ensure_ascii=False), selected).result

    def test_selected_row_returns_all_typed_values_and_zero_based_index(self):
        self.assertEqual(self.run_mode(), ("人物替换", 1, 0.9, "第一行\n第二行：角色替换", True, False, 9))
        ordinary = self.run_mode(selected="a")
        self.assertIs(type(ordinary[2]), float)
        self.assertIs(type(ordinary[4]), bool)
        self.assertIs(type(ordinary[6]), int)

    def test_mode_reorder_changes_index_but_preserves_selected_identity(self):
        data = configuration()
        data["options"].reverse()
        self.assertEqual(self.run_mode(data)[:3], ("人物替换", 0, 0.9))

    def test_output_reorder_changes_result_order(self):
        data = configuration()
        data["outputs"].reverse()
        self.assertEqual(self.run_mode(data)[2:], (9, False, True, "第一行\n第二行：角色替换", 0.9))

    def test_no_custom_outputs_is_valid(self):
        self.assertEqual(Node.execute(module.DEFAULT_CONFIG, "option_a").result, ("A", 0))

    def test_missing_extra_and_wrong_type_values_in_any_mode_are_rejected(self):
        for transform in [
            lambda d: d["values"]["a"].pop("mask"),
            lambda d: d["values"]["a"].update(extra=1),
            lambda d: d["values"]["a"].update(mask="false"),
            lambda d: d["values"]["a"].update(steps=True),
            lambda d: d["values"]["a"].update(steps=2.5),
            lambda d: d["values"]["a"].update(strength=float("nan")),
        ]:
            data = configuration()
            transform(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.run_mode(data)

    def test_duplicate_labels_ids_and_missing_selection_are_rejected(self):
        for key in ["label", "id"]:
            data = configuration()
            data["options"][1][key] = data["options"][0][key]
            with self.assertRaises(ValueError):
                self.run_mode(data)
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.run_mode(selected="missing")

    def test_output_slots_cover_the_last_configurable_field(self):
        data = configuration()
        data["outputs"] = [{"id": str(i), "label": f"字段{i}", "type": "INT"} for i in range(module.MAX_FIELDS)]
        data["values"] = {key: {str(i): i for i in range(module.MAX_FIELDS)} for key in ["a", "b"]}
        result = self.run_mode(data)
        self.assertEqual(result[-1], 63)
        self.assertEqual(len(result), len(Node.RETURN_TYPES))
        data["outputs"].append({"id": "overflow", "label": "溢出", "type": "INT"})
        with self.assertRaises(ValueError):
            self.run_mode(data)

    def test_runtime_merges_only_the_configured_result_count(self):
        result = self.run_mode()
        self.assertEqual(merge_result_data([result], Node), [[value] for value in result])

    def test_comfyui_validates_connections_to_all_concrete_input_types(self):
        prompt = {
            "1": {"class_type": "YtonModeParameters", "inputs": {
                "config": json.dumps(configuration(), ensure_ascii=False), "selected": "b",
            }},
            "2": {"class_type": "ModeParametersTestConsumer", "inputs": {
                name: ["1", slot] for slot, name in enumerate([
                    "mode", "index", "strength", "prompt", "mask", "context", "steps",
                ])
            }},
        }
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, YtonModeParameters=Node, ModeParametersTestConsumer=TypedConsumer):
            valid, error, outputs, errors = asyncio.run(validate_prompt("mode-test", prompt, None))
        self.assertTrue(valid, (error, errors))
        self.assertEqual(outputs, ["2"])

    def test_serialized_configuration_has_identical_results(self):
        data = json.loads(json.dumps(configuration(), ensure_ascii=False))
        self.assertEqual(self.run_mode(data), self.run_mode())


if __name__ == "__main__":
    unittest.main()
