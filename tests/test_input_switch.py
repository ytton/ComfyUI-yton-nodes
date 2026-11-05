"""An upstream Boolean selects the live branch through ComfyUI's executor."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN.parents[1]))
sys.argv = [sys.argv[0], "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()
import execution
import nodes
from comfy_extras.nodes_primitive import Boolean

spec = importlib.util.spec_from_file_location("input_switch_test", PLUGIN / "nodes/input_switch_node.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InputSwitchTests(unittest.TestCase):
    def test_external_boolean_routes_only_the_selected_branch_and_updates_cached_execution(self):
        received = []

        class Consumer:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"value": ("*", {"forceInput": True}), "branch": ("STRING",)}}

            RETURN_TYPES = ()
            FUNCTION = "consume"
            OUTPUT_NODE = True

            def consume(self, value, branch):
                received.append((branch, value))
                return ()

        prompt = {
            "control": {"class_type": "PrimitiveBoolean", "inputs": {"value": True}},
            "switch": {"class_type": "YtonInputSwitch", "inputs": {"value": "输入内容", "enabled": ["control", 0]}},
            "on": {"class_type": "SwitchTestConsumer", "inputs": {"value": ["switch", 0], "branch": "开启"}},
            "off": {"class_type": "SwitchTestConsumer", "inputs": {"value": ["switch", 1], "branch": "关闭"}},
        }
        server = types.SimpleNamespace(client_id=None, last_node_id=None, send_sync=lambda *args: None)

        async def run():
            executor = execution.PromptExecutor(server, cache_type=execution.CacheType.CLASSIC,
                cache_args={"ram": 0, "ram_inactive": 0})
            for state in (True, False, True):
                prompt["control"]["inputs"]["value"] = state
                valid, error, outputs, errors = await execution.validate_prompt(str(state), prompt, None)
                self.assertTrue(valid, (error, errors))
                before = len(received)
                await executor.execute_async(prompt, str(state), execute_outputs=outputs)
                self.assertTrue(executor.success, executor.status_messages)
                self.assertEqual(received[before:], [("开启" if state else "关闭", "输入内容")])

        with patch.dict(nodes.NODE_CLASS_MAPPINGS, YtonInputSwitch=module.YtonInputSwitch,
                        PrimitiveBoolean=Boolean, SwitchTestConsumer=Consumer):
            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
