"""Mode changes preserve output identity, value types and parameter count."""

import asyncio
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import types
import uuid

from comfy_api.latest import io
from execution import CacheType, PromptExecutor, merge_result_data, validate_prompt
from server import PromptServer
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

    def test_text_outputs_execute_as_combo_values(self):
        received = []

        class DropdownConsumer(io.ComfyNode):
            @classmethod
            def define_schema(cls):
                return io.Schema(node_id="ModeDropdownTest", is_output_node=True, inputs=[
                    io.Combo.Input("mode", options=["普通", "人物替换"]),
                    io.Combo.Input("sampler_name", options=nodes.KSampler.INPUT_TYPES()["required"]["sampler_name"][0]),
                    io.Combo.Input("scheduler", options=nodes.KSampler.INPUT_TYPES()["required"]["scheduler"][0]),
                ])

            @classmethod
            def execute(cls, **kwargs):
                received.append(kwargs)
                return io.NodeOutput()

        class DropdownConsumerV1:
            @classmethod
            def INPUT_TYPES(cls):
                inputs = nodes.KSampler.INPUT_TYPES()["required"]
                return {"required": {"mode": (["普通", "人物替换"],),
                                     "sampler_name": inputs["sampler_name"], "scheduler": inputs["scheduler"]}}

            RETURN_TYPES = ()
            FUNCTION = "consume"
            OUTPUT_NODE = True

            def consume(self, **kwargs):
                received.append(kwargs)
                return ()

        data = configuration()
        data["outputs"] = [{"id": name, "label": name, "type": "COMBO" if name == "scheduler" else "STRING"}
                           for name in ("sampler_name", "scheduler")]
        data["values"] = {"a": {"sampler_name": "euler", "scheduler": "normal"},
                          "b": {"sampler_name": "heun", "scheduler": "karras"}}
        prompt = {
            "map": {"class_type": "YtonModeParameters", "inputs": {"config": json.dumps(data), "selected": "a"}},
            "use": {"class_type": "ModeDropdownTest", "inputs": {
                "mode": ["map", 0], "sampler_name": ["map", 2], "scheduler": ["map", 3]}},
        }
        server = types.SimpleNamespace(client_id=None, last_node_id=None, send_sync=lambda *args: None)
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, YtonModeParameters=Node, ModeDropdownTest=DropdownConsumer,
                        ModeDropdownTestV1=DropdownConsumerV1), \
             patch.object(PromptServer, "instance", server, create=True):
            executor = PromptExecutor(server, cache_type=CacheType.CLASSIC, cache_args={"ram": 0, "ram_inactive": 0})
            for consumer, selected in (("ModeDropdownTest", "a"), ("ModeDropdownTestV1", "b")):
                prompt["use"]["class_type"] = consumer
                prompt["map"]["inputs"]["selected"] = selected
                valid, error, outputs, errors = asyncio.run(validate_prompt("combo-mode-test", prompt, None))
                self.assertTrue(valid, (error, errors))
                executor.execute(prompt, uuid.uuid4().hex, execute_outputs=outputs)
                self.assertTrue(executor.success, executor.status_messages)
        self.assertEqual(received, [{"mode": "普通", "sampler_name": "euler", "scheduler": "normal"},
                                    {"mode": "人物替换", "sampler_name": "heun", "scheduler": "karras"}])


if __name__ == "__main__":
    unittest.main()
