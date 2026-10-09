"""Run with ComfyUI's Python and its root on PYTHONPATH."""

import importlib.util
import asyncio
import ast
import __future__
import os
from pathlib import Path
import tempfile
import unittest
import wave

import av
import folder_paths
import numpy as np
import torch
from PIL import Image
from comfy_execution.graph_utils import ExecutionBlocker


NODE_FILE = Path(__file__).resolve().parents[1] / "nodes" / "media_loader_node.py"
spec = importlib.util.spec_from_file_location("yton_media_test", NODE_FILE)
media_nodes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media_nodes)


class MediaNodesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="yton-media-test-")
        self.addCleanup(self.directory.cleanup)
        self.previous_input = folder_paths.get_input_directory()
        folder_paths.set_input_directory(self.directory.name)
        self.addCleanup(folder_paths.set_input_directory, self.previous_input)
        self.root = Path(self.directory.name)
        (self.root / "nested").mkdir()
        Image.new("RGBA", (8, 6), (220, 120, 40, 128)).save(self.root / "nested" / "alpha.png")
        with wave.open(str(self.root / "voice.wav"), "wb") as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(16000)
            file.writeframes(np.arange(1600, dtype=np.int16).tobytes())
        with av.open(str(self.root / "clip.mp4"), "w") as output:
            stream = output.add_stream("mpeg4", rate=5)
            stream.width, stream.height, stream.pix_fmt = 16, 16, "yuv420p"
            for _ in range(3):
                frame = av.VideoFrame.from_ndarray(np.full((16, 16, 3), 150, dtype=np.uint8), format="rgb24")
                for packet in stream.encode(frame):
                    output.mux(packet)
            for packet in stream.encode():
                output.mux(packet)

    def test_fixed_contract_and_sparse_slots(self):
        loader = media_nodes.YtonEasyMediaLoader()
        inputs = loader.INPUT_TYPES()["required"]
        self.assertEqual(len(inputs), 15)
        self.assertTrue(all(value[0] == "STRING" and not value[1].get("forceInput") for value in inputs.values()))
        images, videos, audios = loader.load_media(image_9="nested/alpha.png", video_3="clip.mp4", audio_2="voice.wav")
        self.assertEqual(loader.RETURN_NAMES, ("image", "video", "audio"))
        self.assertEqual(loader.OUTPUT_IS_LIST, (True, True, True))
        self.assertEqual((len(images), len(videos), len(audios)), (1, 1, 1))
        self.assertIsInstance(images[0], torch.Tensor)
        self.assertEqual(videos[0].get_dimensions(), (16, 16))
        self.assertEqual(audios[0]["sample_rate"], 16000)
        for kind, parser, items in [("image", media_nodes.YtonImageListParser, images),
                                    ("video", media_nodes.YtonVideoListParser, videos),
                                    ("audio", media_nodes.YtonAudioListParser, audios)]:
            outputs = parser().parse_list(**{f"{kind}_list": items})
            self.assertEqual(len(outputs), media_nodes.MEDIA_SLOTS[kind])
            self.assertIs(outputs[0], items[0])
            self.assertIsInstance(outputs[1], ExecutionBlocker)
        self.assertEqual(loader.load_media(), ([], [], []))

    def test_image_alpha_audio_and_native_video(self):
        images, videos, audios = media_nodes.YtonEasyMediaLoader().load_media(
            image_1="nested/alpha.png [input]", video_1="clip.mp4", audio_1="voice.wav")
        image, mask = media_nodes.YtonImageParser().parse_image(images[0])
        self.assertEqual(tuple(image.shape), (1, 6, 8, 3))
        self.assertEqual(tuple(mask.shape), (1, 6, 8))
        self.assertEqual(mask[0, 0, 0].item(), 0)
        rgba = torch.full((1, 6, 8, 4), 128 / 255)
        _, alpha_mask = media_nodes.YtonImageParser().parse_image(rgba)
        self.assertAlmostEqual(alpha_mask[0, 0, 0].item(), 1 - 128 / 255, places=5)
        audio, = media_nodes.YtonAudioParser().parse_audio(audios[0])
        self.assertEqual(audio["sample_rate"], 16000)
        self.assertEqual(tuple(audio["waveform"].shape), (1, 1, 1600))
        video, = media_nodes.YtonVideoParser().parse_video(videos[0])
        self.assertEqual(video.get_dimensions(), (16, 16))
        self.assertEqual(tuple(video.get_components().images.shape), (3, 16, 16, 3))

    def test_missing_files_and_modified_files(self):
        loader = media_nodes.YtonEasyMediaLoader
        self.assertIn("素材文件不存在", loader.VALIDATE_INPUTS(image_1="missing.png"))
        before = loader.IS_CHANGED(image_1="nested/alpha.png")
        path = self.root / "nested" / "alpha.png"
        stamp = path.stat().st_mtime_ns
        os.utime(path, ns=(stamp, stamp + 1_000_000_000))
        self.assertNotEqual(before, loader.IS_CHANGED(image_1="nested/alpha.png"))
        self.assertEqual(loader.VALIDATE_INPUTS(), True)

    def test_comfy_execution_graph_and_empty_branch(self):
        import execution
        import nodes

        received = []

        class OutputCheck:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"image": ("IMAGE",), "video": ("VIDEO",), "audio": ("AUDIO",)}}

            RETURN_TYPES = ()
            FUNCTION = "consume"
            OUTPUT_NODE = True

            def consume(self, image, video, audio):
                received.append((tuple(image.shape), video.get_dimensions(), audio["sample_rate"]))
                return ()

        for name in ["YtonEasyMediaLoader", "YtonImageListParser", "YtonVideoListParser",
                     "YtonAudioListParser", "YtonImageParser", "YtonVideoParser", "YtonAudioParser"]:
            nodes.NODE_CLASS_MAPPINGS[name] = getattr(media_nodes, name)
        nodes.NODE_CLASS_MAPPINGS["YtonTestOutput"] = OutputCheck
        files = {name: "" for name in media_nodes.YtonEasyMediaLoader.INPUT_TYPES()["required"]}
        files.update(image_9="nested/alpha.png", video_2="clip.mp4", audio_3="voice.wav")
        prompt = {"1": {"class_type": "YtonEasyMediaLoader", "inputs": files}}
        for kind, list_id, item_id, loader_slot, item_slot in [
            ("Image", "2", "3", 0, 0), ("Video", "4", "5", 1, 0), ("Audio", "6", "7", 2, 0),
        ]:
            prompt[list_id] = {"class_type": f"Yton{kind}ListParser", "inputs": {f"{kind.lower()}_list": ["1", loader_slot]}}
            prompt[item_id] = {"class_type": f"Yton{kind}Parser", "inputs": {kind.lower(): [list_id, item_slot]}}
        prompt["8"] = {"class_type": "YtonTestOutput", "inputs": {"image": ["3", 0], "video": ["5", 0], "audio": ["7", 0]}}
        prompt["9"] = {"class_type": "YtonImageParser", "inputs": {"image": ["2", 1]}}
        prompt["10"] = {"class_type": "YtonTestOutput", "inputs": {"image": ["9", 0], "video": ["5", 0], "audio": ["7", 0]}}

        class TestServer:
            client_id = None
            last_node_id = None

            def send_sync(self, *args):
                pass

        async def run():
            valid, errors, outputs, node_errors = await execution.validate_prompt("yton-media-test", prompt, None)
            self.assertTrue(valid, (errors, node_errors))
            executor = execution.PromptExecutor(TestServer(), cache_type=execution.CacheType.CLASSIC,
                                                cache_args={"ram": 0, "ram_inactive": 0})
            await executor.execute_async(prompt, "yton-media-test", execute_outputs=outputs)
            self.assertTrue(executor.success, executor.status_messages)

        asyncio.run(run())
        self.assertEqual(received, [((1, 6, 8, 3), (16, 16), 16000)])

    def test_easy_media_split_nodes_receive_native_lists(self):
        import execution
        import nodes
        from comfy_api.latest import Input, io

        easy_root = Path(folder_paths.base_path) / "custom_nodes" / "ComfyUI-Easy-Media"
        if not easy_root.is_dir():
            self.skipTest("EasyMedia is not installed")
        # Load the actual EasyMedia parser classes without initializing its model suite.
        util_spec = importlib.util.spec_from_file_location("easy_media_utils_test", easy_root / "utils" / "media.py")
        util = importlib.util.module_from_spec(util_spec)
        util_spec.loader.exec_module(util)
        scope = {"io": io, "Input": Input, "torch": torch, "split_list_outputs": util.split_list_outputs,
                 "CATEGORY_IMAGE": "image", "CATEGORY_VIDEO": "video", "CATEGORY_AUDIO": "audio"}
        for filename, name in [("image.py", "SplitImages"), ("video.py", "SplitVideos"), ("audio.py", "SplitAudios")]:
            path = easy_root / "nodes" / filename
            definition = next(item for item in ast.parse(path.read_text(encoding="utf-8")).body
                              if isinstance(item, ast.ClassDef) and item.name == name)
            exec(compile(ast.Module(body=[definition], type_ignores=[]), str(path), "exec",
                         flags=__future__.annotations.compiler_flag), scope)
            nodes.NODE_CLASS_MAPPINGS[f"YtonTestEasy{name}"] = scope[name]
        nodes.NODE_CLASS_MAPPINGS["YtonEasyMediaLoader"] = media_nodes.YtonEasyMediaLoader
        received = []

        class CheckMedia:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"first": ("IMAGE",), "second": ("IMAGE",), "video": ("VIDEO",), "audio": ("AUDIO",)}}

            RETURN_TYPES = ()
            FUNCTION = "check"
            OUTPUT_NODE = True

            def check(self, first, second, video, audio):
                received.append((tuple(first.shape), tuple(second.shape), video.get_dimensions(), audio["sample_rate"]))
                return ()

        class TestServer:
            client_id = None
            last_node_id = None

            def send_sync(self, *args):
                pass

        nodes.NODE_CLASS_MAPPINGS["YtonTestNativeOutput"] = CheckMedia
        Image.new("RGB", (12, 10)).save(self.root / "second.png")
        files = {name: "" for name in media_nodes.YtonEasyMediaLoader.INPUT_TYPES()["required"]}
        files.update(image_1="nested/alpha.png", image_9="second.png", video_3="clip.mp4", audio_2="voice.wav")
        prompt = {
            "1": {"class_type": "YtonEasyMediaLoader", "inputs": files},
            "2": {"class_type": "YtonTestEasySplitImages", "inputs": {"images": ["1", 0]}},
            "3": {"class_type": "YtonTestEasySplitVideos", "inputs": {"videos": ["1", 1]}},
            "4": {"class_type": "YtonTestEasySplitAudios", "inputs": {"audios": ["1", 2]}},
            "5": {"class_type": "YtonTestNativeOutput", "inputs": {"first": ["2", 0], "second": ["2", 1], "video": ["3", 0], "audio": ["4", 0]}},
        }

        async def run():
            valid, errors, outputs, node_errors = await execution.validate_prompt("yton-easy-media-test", prompt, None)
            self.assertTrue(valid, (errors, node_errors))
            executor = execution.PromptExecutor(TestServer(), cache_type=execution.CacheType.CLASSIC,
                                                cache_args={"ram": 0, "ram_inactive": 0})
            await executor.execute_async(prompt, "yton-easy-media-test", execute_outputs=outputs)
            self.assertTrue(executor.success, executor.status_messages)

        asyncio.run(run())
        self.assertEqual(received, [((1, 6, 8, 3), (1, 10, 12, 3), (16, 16), 16000)])


if __name__ == "__main__":
    unittest.main()
