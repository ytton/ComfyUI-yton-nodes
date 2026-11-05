"""Check native execution through the official generator without loading weights."""

import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import torch


package = ModuleType("local_optimizer_test")
package.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules[package.__name__] = package
native = importlib.import_module("local_optimizer_test.native_optimizer_runtime")
node_module = importlib.import_module("local_optimizer_test.nodes.local_optimizer_node")
Node = node_module.YtonLocalPromptOptimizer


def fake_clip(text="优化结果"):
    clip = Mock()
    clip.tokenize.return_value = [[(1, 1.0)]]
    clip.generate.return_value = [9]
    clip.decode.side_effect = lambda ids: text if ids == [9] else ""
    return clip


class LocalOptimizerTests(unittest.TestCase):
    def test_native_uses_official_generator_and_custom_system(self):
        clip = fake_clip()
        result = native.generate_native(clip, "用户原文", "自定义规则", "选定的 Skill", native.DEFAULT_NATIVE_JSON)
        self.assertEqual(result, "优化结果")
        args, kwargs = clip.tokenize.call_args
        self.assertEqual(args, ("用户原文",))
        self.assertIn("自定义规则", kwargs["system_prompt"])
        self.assertIn("选定的 Skill", kwargs["system_prompt"])
        self.assertFalse(kwargs["skip_template"])
        self.assertNotIn("LTX", kwargs["system_prompt"])
        self.assertEqual(clip.generate.call_args.kwargs["max_length"], native.DEFAULT_NATIVE["max_tokens"])

    def test_zero_temperature_and_seed_are_passed_to_native_generator(self):
        clip = fake_clip()
        options = {**native.DEFAULT_NATIVE, "temperature": 0, "seed": 42}
        native.generate_native(clip, "原文", "", "", json.dumps(options))
        self.assertFalse(clip.generate.call_args.kwargs["do_sample"])
        self.assertEqual(clip.generate.call_args.kwargs["seed"], 42)

    def test_image_order_and_video_timestamps_are_preserved(self):
        images = torch.rand(2, 4, 4, 3)
        frames = torch.rand(30, 4, 4, 3)
        audio = {"waveform": torch.zeros(1, 1, 160), "sample_rate": 16000}
        video = Mock()
        video.get_components.return_value = SimpleNamespace(images=frames, frame_rate=10, audio=audio)
        clip = fake_clip()
        native.generate_native(clip, "人物替换", "规则", "", native.DEFAULT_NATIVE_JSON,
                               image=[images], video=[video], audio=[audio])
        args, kwargs = clip.tokenize.call_args
        self.assertEqual(len(kwargs["images"]), 14)
        self.assertTrue(torch.equal(kwargs["images"][0], images[0:1]))
        self.assertTrue(torch.equal(kwargs["images"][-1], frames[-1:]))
        self.assertEqual(len(kwargs["audios"]), 2)
        self.assertIn("视频 1 时长 3.000 秒", args[0])
        self.assertIn("2.900 秒", args[0])
        self.assertTrue(args[0].endswith("\n\n人物替换"))

    def test_masked_edit_request_is_forwarded_verbatim_with_images(self):
        clip = fake_clip()
        native.generate_native(clip, "去掉遮罩选中的花朵", "文生图或编辑规则", "", native.DEFAULT_NATIVE_JSON,
                               image=[torch.zeros(1, 4, 4, 3)])
        request = clip.tokenize.call_args.args[0]
        self.assertEqual(request, "去掉遮罩选中的花朵")
        self.assertEqual(clip.tokenize.call_args.kwargs["system_prompt"], "文生图或编辑规则")

    def test_system_only_request_does_not_invent_user_instructions(self):
        clip = fake_clip()
        native.generate_native(clip, "", "根据图片反推", "", native.DEFAULT_NATIVE_JSON,
                               image=[torch.zeros(1, 4, 4, 3)])
        request = clip.tokenize.call_args.args[0]
        self.assertEqual(request, "")
        self.assertEqual(len(clip.tokenize.call_args.kwargs["images"]), 1)

    def test_native_requires_clip_and_valid_options(self):
        with self.assertRaisesRegex(native.OptimizerError, "CLIP"):
            native.generate_native(None, "原文", "", "", native.DEFAULT_NATIVE_JSON)
        for updates in [{"max_tokens": True}, {"thinking": "off"}, {"temperature": float("nan")}]:
            with self.subTest(updates=updates), self.assertRaises(native.OptimizerError):
                native.parse_native_options(json.dumps({**native.DEFAULT_NATIVE, **updates}))

    def test_unfinished_thinking_is_never_returned_as_prompt(self):
        with self.assertRaisesRegex(native.OptimizerError, "思考"):
            native.generate_native(fake_clip("<think>还在思考"), "原文", "", "", native.DEFAULT_NATIVE_JSON)

    def test_native_selection_does_not_use_llama_runtime(self):
        with patch.object(node_module.runtime, "generate") as llama, patch.object(node_module.runtime, "close") as close, patch.object(node_module, "load_skill", return_value="Skill"):
            result = Node().execute(["原文"], ["规则"], ["测试"], [True], [""], ["不需要解析"],
                                    ["comfyui"], [native.DEFAULT_NATIVE_JSON], clip=[fake_clip()])
        self.assertEqual(result["result"], ("优化结果",))
        llama.assert_not_called()
        close.assert_called_once()

    def test_llama_selection_keeps_gguf_generation(self):
        with patch.object(node_module.runtime, "generate", return_value="GGUF结果") as llama, patch.object(node_module, "load_skill", return_value=""):
            result = Node().execute(["原文"], ["规则"], [""], [True], ["example.gguf"], [node_module.DEFAULT_OPTIONS_JSON],
                                    ["llama.cpp"], ["不需要解析"])
        self.assertEqual(result["result"], ("GGUF结果",))
        self.assertEqual(llama.call_args.args[0], "example.gguf")

    def test_disabled_bypasses_both_runtimes_and_media(self):
        video = Mock()
        with patch.object(node_module.runtime, "generate") as llama:
            result = Node().execute(["原文"], [""], ["不存在"], [False], [""], ["invalid"],
                                    ["comfyui"], ["invalid"], video=[video])
        self.assertEqual(result["result"], ("原文",))
        llama.assert_not_called()
        video.get_components.assert_not_called()


if __name__ == "__main__":
    unittest.main()
