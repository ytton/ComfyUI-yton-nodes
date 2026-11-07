"""Dynamic dropdown values reach both V1 and V3 COMBO consumers unchanged."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import uuid

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN.parents[1]))
sys.argv = [sys.argv[0], "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()
from comfy_api.latest import io
import execution
import nodes
from server import PromptServer

spec = importlib.util.spec_from_file_location("combo_clone_node", PLUGIN / "nodes/combo_clone_node.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Node = module.YtonComboClone


class ComboCloneTests(unittest.TestCase):
    def test_dynamic_choice_executes_with_both_combo_formats(self):
        received = []

        class ConsumerV1:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"value": (["euler", "heun"],)}}

            RETURN_TYPES = ()
            FUNCTION = "consume"
            OUTPUT_NODE = True

            def consume(self, value):
                received.append(("v1", value))
                return ()

        class ConsumerV3(io.ComfyNode):
            @classmethod
            def define_schema(cls):
                return io.Schema(node_id="CloneConsumerV3", is_output_node=True,
                                 inputs=[io.Combo.Input("value", options=[24, 30])])

            @classmethod
            def execute(cls, value):
                received.append(("v3", value))
                return io.NodeOutput()

        server = types.SimpleNamespace(client_id=None, last_node_id=None, send_sync=lambda *args: None)
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, YtonComboClone=Node,
                        CloneConsumerV1=ConsumerV1, CloneConsumerV3=ConsumerV3), \
             patch.object(PromptServer, "instance", server, create=True):
            executor = execution.PromptExecutor(server, cache_type=execution.CacheType.CLASSIC,
                cache_args={"ram": 0, "ram_inactive": 0})
            for consumer, value in (("CloneConsumerV1", "euler"), ("CloneConsumerV1", "heun"), ("CloneConsumerV3", 24)):
                prompt = {"clone": {"class_type": "YtonComboClone", "inputs": {"value": value}},
                          "use": {"class_type": consumer, "inputs": {"value": ["clone", 0]}}}
                valid, error, outputs, errors = asyncio.run(execution.validate_prompt("combo-clone", prompt, None))
                self.assertTrue(valid, (error, errors))
                executor.execute(prompt, uuid.uuid4().hex, execute_outputs=outputs)
                self.assertTrue(executor.success, executor.status_messages)
        self.assertEqual(received, [("v1", "euler"), ("v1", "heun"), ("v3", 24)])
