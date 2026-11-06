"""Task prompts and media reach the local runtime through the shared LLM socket."""

import asyncio
import base64
from copy import deepcopy
import io as byteio
import json
import types
import unittest
from unittest.mock import patch
import wave

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

import test_character_replacement as fixture
from replacement_test_plugin.llama_optimizer_config import DEFAULT_OPTIONS, DEFAULT_OPTIONS_JSON
from replacement_test_plugin.local_llm_connection import LocalLLMConnection, connection_from_config, runtime
from replacement_test_plugin.llm_connection import LLMConnection
from replacement_test_plugin.nodes.local_llm_connector_node import YtonLocalLLMConnector
from replacement_test_plugin.replacement import routes as replacement_routes
from replacement_test_plugin.viggle import routes as viggle_routes
from replacement_test_plugin.viggle.media import DEFAULT_CONFIG
from replacement_test_plugin.viggle.nodes import YtonViggleReplacementSegment


class LocalLLMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ReplacementTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.ReplacementTests.tearDownClass()

    def viggle_config(self):
        config = deepcopy(DEFAULT_CONFIG)
        config.update(video="source.mp4", images=["red.png", "", "blue.png", ""], resolution="320p")
        config["plan"].update(seconds=1.5)
        return config

    def test_node_creates_connection_without_loading_model(self):
        with patch.object(runtime, "generate") as generate:
            result = YtonLocalLLMConnector.execute("test.gguf", DEFAULT_OPTIONS_JSON)
            self.assertEqual(result.result[0], LocalLLMConnection("test.gguf"))
            generate.assert_not_called()
        local = YtonLocalLLMConnector.GET_NODE_INFO_V1()
        remote = fixture.CLASSES[0].GET_NODE_INFO_V1()
        self.assertIn(YtonLocalLLMConnector, fixture.CLASSES)
        self.assertEqual(local["output"], remote["output"])
        self.assertEqual(local["output"], ["YTON_LLM"])
        with self.assertRaisesRegex(ValueError, "选择"):
            YtonLocalLLMConnector.execute("", DEFAULT_OPTIONS_JSON)

    def test_system_user_and_generation_parameters(self):
        options = {**DEFAULT_OPTIONS, "temperature": .3, "keep_loaded": True}
        connection = LocalLLMConnection("custom.gguf", json.dumps(options))
        with patch.object(runtime, "generate", return_value="删除选中的花朵，其余画面保留。") as generate:
            result = connection.generate("去掉遮罩选中的花朵", system="按用户要求编辑图片。",
                                         parameters={"temperature": .1, "max_tokens": 512, "top_p": .8, "seed": 42})
        self.assertIn("删除", result)
        model, passed, messages = generate.call_args.args
        self.assertEqual(model, "custom.gguf")
        self.assertEqual((passed["temperature"], passed["max_tokens"], passed["seed"]), (.1, 512, 42))
        self.assertTrue(passed["keep_loaded"])
        self.assertEqual(messages, [{"role": "system", "content": "按用户要求编辑图片。"},
                                   {"role": "user", "content": [{"type": "text", "text": "去掉遮罩选中的花朵"}]}])
        self.assertFalse(generate.call_args.kwargs["has_media"])
        self.assertEqual(json.loads(connection.options_json), options)

    def test_multimodal_order_and_audio_encoding(self):
        audio = {"waveform": fixture.torch.zeros((1, 2, 100)), "sample_rate": 16000}
        media = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,preencoded"}}]
        with patch.object(runtime, "generate", return_value="ok") as generate:
            LocalLLMConnection("vision.gguf").generate("先读用户要求", system="视觉任务", media=media,
                images=[Image.new("RGB", (8, 8), "red"), Image.new("RGB", (8, 8), "blue")], audios=[audio])
        content = generate.call_args.args[2][1]["content"]
        self.assertTrue(generate.call_args.kwargs["has_media"])
        self.assertEqual([item["type"] for item in content], ["text", "image_url", "image_url", "image_url", "input_audio"])
        self.assertEqual(content[1], media[0])
        for item, channel in ((content[2], 0), (content[3], 2)):
            image = Image.open(byteio.BytesIO(base64.b64decode(item["image_url"]["url"].split(",")[1])))
            self.assertGreater(image.getpixel((0, 0))[channel], 250)
        with wave.open(byteio.BytesIO(base64.b64decode(content[4]["input_audio"]["data"]))) as wav:
            self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getnframes()), (2, 16000, 100))

    def test_factories_and_invalid_parameters(self):
        self.assertEqual(connection_from_config({"kind": "local", "model_name": "v.gguf", "options_json": DEFAULT_OPTIONS_JSON}), LocalLLMConnection("v.gguf"))
        self.assertEqual(connection_from_config({"kind": "remote", "model_ref": "test", "temperature": .2, "max_tokens": 512}), LLMConnection("test", .2, 512))
        with self.assertRaisesRegex(ValueError, "类型"):
            connection_from_config({"kind": "bad"})
        with patch.object(runtime, "generate") as generate:
            with self.assertRaisesRegex(ValueError, "参数"):
                LocalLLMConnection().generate("user", parameters={"messages": []})
            with self.assertRaises(ValueError):
                LocalLLMConnection(options_json="{}").generate("user")
            generate.assert_not_called()

    def test_replacement_auto_optimization(self):
        config = fixture.ReplacementTests().config()
        config.update(auto=True, original="用 @图片1 替换 @视频 的左侧人物")
        with patch.object(runtime, "generate", return_value="替换完成的提示词") as generate:
            result = fixture.ReplacementTests().node().execute(json.dumps(config), llm=LocalLLMConnection("vision.gguf"))
        self.assertEqual(result.result[2], "替换完成的提示词")
        messages = generate.call_args.args[2]
        self.assertIn("<Picture 1>", messages[1]["content"][0]["text"])
        self.assertEqual(len(messages[1]["content"]), 4)  # 用户要求、六帧拼图、两张参考图
        self.assertTrue(generate.call_args.kwargs["has_media"])

    def test_viggle_auto_optimization(self):
        config = self.viggle_config()
        config.update(auto=True, mode="keyframe", original="保留原动作")
        config["keyframes"] = {"0": [{"frame": 0, "image": "red.png"}, {"frame": 20, "image": "blue.png"}]}
        node = type("LocalViggleParser", (YtonViggleReplacementSegment,), {})
        node.hidden = fixture.io.HiddenHolder.from_dict({fixture.io.Hidden.unique_id: "parser", fixture.io.Hidden.dynprompt: fixture.DynamicPrompt({})})
        with patch.object(runtime, "generate", return_value="pin模式提示词") as generate:
            result = node.execute({"config": json.dumps(config), "index": 0, "llm": LocalLLMConnection("vision.gguf"), "previous_video": None})
        self.assertEqual(result.result[2], "pin模式提示词")
        content = generate.call_args.args[2][1]["content"]
        user = content[0]["text"]
        self.assertRegex(user, r"零基帧索引\s+20")
        self.assertIn("保留原动作", user)
        for item, channel in ((content[1], 0), (content[2], 2)):
            with Image.open(byteio.BytesIO(base64.b64decode(item["image_url"]["url"].split(",")[1]))) as image:
                self.assertGreater(image.getpixel((0, 0))[channel], 250)
        with Image.open(byteio.BytesIO(base64.b64decode(content[3]["image_url"]["url"].split(",")[1]))) as sheet:
            self.assertEqual(sheet.size, (960, 600))

    def test_manual_routes_use_local_connection(self):
        import server

        async def run():
            table = web.RouteTableDef()
            with patch.object(server.PromptServer, "instance", types.SimpleNamespace(routes=table), create=True):
                replacement_routes.install()
                viggle_routes.install()
            app = web.Application()
            app.add_routes(table)
            async with TestClient(TestServer(app)) as client:
                for path, config in (("replacement", fixture.ReplacementTests().config()), ("viggle", self.viggle_config())):
                    with self.subTest(path=path), patch.object(runtime, "generate", return_value="本地手动优化结果") as generate:
                        response = await client.post(f"/yton/{path}/optimize", json={"config": config, "index": 0,
                            "connection": {"kind": "local", "model_name": "vision.gguf", "options_json": DEFAULT_OPTIONS_JSON}})
                        data = await response.json()
                        self.assertEqual(response.status, 200, data)
                        self.assertEqual(data["text"], "本地手动优化结果")
                        self.assertTrue(data["signature"])
                        self.assertTrue(generate.call_args.kwargs["has_media"])
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main(argv=[__file__])
