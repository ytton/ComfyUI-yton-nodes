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
from fractions import Fraction

import av
import folder_paths
import numpy as np
import torch
from PIL import Image


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
            self.assertEqual(list(parser.INPUT_TYPES()["required"]), [kind])
            outputs = parser().parse_list(**{kind: items})
            self.assertEqual(len(outputs), media_nodes.MEDIA_SLOTS[kind])
            self.assertIs(outputs[0], items[0])
            self.assertTrue(all(output is None for output in outputs[1:]))
            self.assertTrue(all(output is None for output in parser().parse_list(**{kind: []})))
        self.assertEqual(loader.load_media(), ([], [], []))

    def test_empty_media_passes_through_item_parsers(self):
        self.assertEqual(media_nodes.YtonImageParser().parse_image(None), (None, None))
        self.assertEqual(media_nodes.YtonVideoParser().parse_video(None), (None, None, None, None))
        self.assertEqual(media_nodes.YtonVideoParser().parse_video(None, force_rate=24), (None, None, None, None))
        self.assertEqual(media_nodes.YtonAudioParser().parse_audio(None), (None,))

    def test_qwen_encoder_accepts_all_nine_connected_outputs(self):
        import execution
        import nodes
        from comfy_extras.nodes_qwen import TextEncodeQwenImage21

        encoded_counts = []
        completed = []

        class Clip:
            def tokenize(self, text, images, **kwargs):
                encoded_counts.append(len(images))
                return text

            def encode_from_tokens_scheduled(self, tokens):
                return [[torch.zeros(1, 1, 4), {}]]

        class ClipLoader:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {}}

            RETURN_TYPES = ("CLIP",)
            FUNCTION = "load"

            def load(self):
                return (Clip(),)

        class Output:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"positive": ("CONDITIONING",), "latent": ("LATENT",)}}

            RETURN_TYPES = ()
            FUNCTION = "consume"
            OUTPUT_NODE = True

            def consume(self, positive, latent):
                completed.append(tuple(latent["samples"].shape))
                return ()

        class Server:
            client_id = None
            last_node_id = None

            def send_sync(self, *args):
                pass

        nodes.NODE_CLASS_MAPPINGS.update({
            "YtonEasyMediaLoader": media_nodes.YtonEasyMediaLoader,
            "YtonImageListParser": media_nodes.YtonImageListParser,
            "YtonTestClipLoader": ClipLoader,
            "YtonTestQwenEncoder": TextEncodeQwenImage21,
            "YtonTestQwenOutput": Output,
        })

        async def run():
            for count in [0, 1, 3, 9]:
                with self.subTest(images=count):
                    files = {name: "" for name in media_nodes.YtonEasyMediaLoader.INPUT_TYPES()["required"]}
                    # Fill from the end to also verify sparse media-loader slots.
                    for index in range(10 - count, 10):
                        files[f"image_{index}"] = "nested/alpha.png"
                    prompt = {
                        "1": {"class_type": "YtonEasyMediaLoader", "inputs": files},
                        "2": {"class_type": "YtonImageListParser", "inputs": {"image": ["1", 0]}},
                        "3": {"class_type": "YtonTestClipLoader", "inputs": {}},
                        "4": {"class_type": "YtonTestQwenEncoder", "inputs": {
                            "clip": ["3", 0], "prompt": "编辑已有参考图", "negative_prompt": "", "resolution": 64,
                            **{f"images.image_{index}": ["2", index - 1] for index in range(1, 10)},
                        }},
                        "5": {"class_type": "YtonTestQwenOutput", "inputs": {"positive": ["4", 0], "latent": ["4", 2]}},
                    }
                    prompt_id = f"yton-qwen-{count}"
                    valid, errors, outputs, node_errors = await execution.validate_prompt(prompt_id, prompt, None)
                    self.assertTrue(valid, (errors, node_errors))
                    executor = execution.PromptExecutor(Server(), cache_type=execution.CacheType.CLASSIC,
                                                        cache_args={"ram": 0, "ram_inactive": 0})
                    await executor.execute_async(prompt, prompt_id, execute_outputs=outputs)
                    self.assertTrue(executor.success, executor.status_messages)
                    self.assertEqual(encoded_counts[-2:], [count, count])
                    self.assertEqual(len(completed), [0, 1, 3, 9].index(count) + 1)

        asyncio.run(run())

    def test_image_alpha_audio_and_native_video(self):
        images, videos, audios = media_nodes.YtonEasyMediaLoader().load_media(
            image_1="nested/alpha.png [input]", video_1="clip.mp4", audio_1="voice.wav")
        image, mask = media_nodes.YtonImageParser().parse_image(images[0])
        self.assertEqual(tuple(image.shape), (1, 6, 8, 3))
        self.assertEqual(tuple(mask.shape), (1, 6, 8))
        self.assertAlmostEqual(mask[0, 0, 0].item(), 1 - 128 / 255, places=5)
        rgba = torch.full((1, 6, 8, 4), 128 / 255)
        _, alpha_mask = media_nodes.YtonImageParser().parse_image(rgba)
        self.assertAlmostEqual(alpha_mask[0, 0, 0].item(), 1 - 128 / 255, places=5)
        audio, = media_nodes.YtonAudioParser().parse_audio(audios[0])
        self.assertEqual(audio["sample_rate"], 16000)
        self.assertEqual(tuple(audio["waveform"].shape), (1, 1, 1600))
        frames, count, track, info = media_nodes.YtonVideoParser().parse_video(videos[0])
        self.assertEqual(tuple(frames.shape), (3, 16, 16, 3))
        self.assertEqual(count, 3)
        self.assertIsNone(track)
        self.assertEqual(media_nodes.YtonVideoParser.RETURN_TYPES, ("IMAGE", "INT", "AUDIO", "VHS_VIDEOINFO"))
        self.assertEqual(info, {
            "source_fps": 5.0, "source_frame_count": 3, "source_duration": 0.6,
            "source_width": 16, "source_height": 16, "loaded_fps": 5.0,
            "loaded_frame_count": 3, "loaded_duration": 0.6, "loaded_width": 16, "loaded_height": 16,
        })

    def test_mask_editor_image_keeps_rgb_and_mask_through_list_parser(self):
        rgba = np.full((6, 8, 4), 255, dtype=np.uint8)
        rgba[:, :, :3] = (220, 120, 40)
        rgba[1:4, 2:6, 3] = 0
        Image.fromarray(rgba).save(self.root / "masked.png")
        Image.new("RGB", (8, 6), (30, 80, 140)).save(self.root / "plain.png")
        images, _, _ = media_nodes.YtonEasyMediaLoader().load_media(
            image_1="masked.png [input]", image_2="plain.png")
        self.assertEqual(tuple(images[0].shape), (1, 6, 8, 3))
        first, second, *_ = media_nodes.YtonImageListParser().parse_list(image=images)
        image, mask = media_nodes.YtonImageParser().parse_image(first)
        torch.testing.assert_close(image, torch.tensor([220, 120, 40]).float().div(255).expand(1, 6, 8, 3))
        expected_mask = torch.zeros(1, 6, 8)
        expected_mask[:, 1:4, 2:6] = 1
        torch.testing.assert_close(mask, expected_mask)
        _, plain_mask = media_nodes.YtonImageParser().parse_image(second)
        torch.testing.assert_close(plain_mask, torch.zeros(1, 6, 8))

    def test_video_audio_extraction_and_vhs_info(self):
        with av.open(str(self.root / "with-audio.mkv"), "w") as output:
            video_stream = output.add_stream("mpeg4", rate=5)
            video_stream.width, video_stream.height, video_stream.pix_fmt = 16, 16, "yuv420p"
            audio_stream = output.add_stream("pcm_s16le", rate=16000)
            audio_stream.layout = "mono"
            for _ in range(3):
                frame = av.VideoFrame.from_ndarray(np.full((16, 16, 3), 150, dtype=np.uint8), format="rgb24")
                for packet in video_stream.encode(frame):
                    output.mux(packet)
            for packet in video_stream.encode():
                output.mux(packet)
            audio_frame = av.AudioFrame.from_ndarray(np.arange(9600, dtype=np.int16).reshape(1, -1), format="s16", layout="mono")
            audio_frame.sample_rate, audio_frame.pts, audio_frame.time_base = 16000, 0, Fraction(1, 16000)
            for packet in audio_stream.encode(audio_frame):
                output.mux(packet)
            for packet in audio_stream.encode():
                output.mux(packet)
        _, videos, _ = media_nodes.YtonEasyMediaLoader().load_media(video_1="with-audio.mkv")
        frames, count, audio, info = media_nodes.YtonVideoParser().parse_video(videos[0])
        self.assertEqual(tuple(frames.shape), (3, 16, 16, 3))
        self.assertEqual(count, 3)
        self.assertEqual(audio["sample_rate"], 16000)
        self.assertEqual(tuple(audio["waveform"].shape), (1, 1, 9600))
        torch.testing.assert_close(audio["waveform"][0, 0], torch.arange(9600).float() / 32768)
        # Feed the resulting dictionary into the installed VHS information parser.
        path = Path(folder_paths.base_path) / "custom_nodes" / "ComfyUI-VideoHelperSuite" / "videohelpersuite" / "nodes.py"
        if path.is_file():
            definition = next(item for item in ast.parse(path.read_text(encoding="utf-8")).body
                              if isinstance(item, ast.ClassDef) and item.name == "VideoInfo")
            scope = {}
            exec(compile(ast.Module(body=[definition], type_ignores=[]), str(path), "exec"), scope)
            result = scope["VideoInfo"]().get_video_info(info)
            self.assertEqual(result, (5.0, 3, 0.6, 16, 16, 5.0, 3, 0.6, 16, 16))

    def test_in_memory_video_and_fractional_fps(self):
        from comfy_api.latest import InputImpl, Types

        video = InputImpl.VideoFromComponents(Types.VideoComponents(
            images=torch.zeros(30, 12, 20, 3), frame_rate=Fraction(30000, 1001)))
        frames, count, audio, info = media_nodes.YtonVideoParser().parse_video(video)
        self.assertEqual(tuple(frames.shape), (30, 12, 20, 3))
        self.assertEqual(count, 30)
        self.assertIsNone(audio)
        self.assertEqual(info["loaded_fps"], float(Fraction(30000, 1001)))
        self.assertAlmostEqual(info["loaded_duration"], 1.001)
        self.assertEqual((info["loaded_width"], info["loaded_height"]), (20, 12))

    def test_video_rate_conversion_keeps_duration_audio_and_source_info(self):
        from comfy_api.latest import InputImpl, Types

        images = torch.arange(150).float().reshape(150, 1, 1, 1).expand(150, 12, 20, 3)
        audio = {"waveform": torch.zeros(1, 1, 80000), "sample_rate": 16000}
        video = InputImpl.VideoFromComponents(Types.VideoComponents(
            images=images, audio=audio, frame_rate=Fraction(30)))
        frames, count, track, info = media_nodes.YtonVideoParser().parse_video(video, force_rate=24)
        self.assertEqual(count, 120)
        torch.testing.assert_close(frames[:, 0, 0, 0], (torch.arange(120) * 30 / 24).long().float())
        self.assertIs(track, audio)
        self.assertEqual(info["source_fps"], 30)
        self.assertEqual(info["source_frame_count"], 150)
        self.assertEqual(info["loaded_fps"], 24)
        self.assertEqual(info["loaded_duration"], 5)
        self.assertEqual(info["source_duration"], 5)

    def test_h3_accepts_all_connected_media_slots_with_empty_partial_and_full_inputs(self):
        import execution
        import nodes
        from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo

        with av.open(str(self.root / "reference.mkv"), "w") as output:
            video_stream = output.add_stream("mpeg4", rate=5)
            video_stream.width, video_stream.height, video_stream.pix_fmt = 16, 16, "yuv420p"
            audio_stream = output.add_stream("pcm_s16le", rate=16000)
            audio_stream.layout = "mono"
            for _ in range(3):
                frame = av.VideoFrame.from_ndarray(np.full((16, 16, 3), 150, dtype=np.uint8), format="rgb24")
                for packet in video_stream.encode(frame):
                    output.mux(packet)
            for packet in video_stream.encode():
                output.mux(packet)
            frame = av.AudioFrame.from_ndarray(np.zeros((1, 9600), dtype=np.int16), format="s16", layout="mono")
            frame.sample_rate, frame.pts, frame.time_base = 16000, 0, Fraction(1, 16000)
            for packet in audio_stream.encode(frame):
                output.mux(packet)
            for packet in audio_stream.encode():
                output.mux(packet)

        encoded, completed = [], []

        class Clip:
            def tokenize(self, text, minimax_ref_items):
                encoded.append([item['type'] for item in minimax_ref_items])
                return text

            def encode_from_tokens_scheduled(self, tokens):
                return [[torch.zeros(1, 1, 4), {}]]

        class ClipLoader:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {}}
            RETURN_TYPES, FUNCTION = ("CLIP",), "load"
            def load(self):
                return (Clip(),)

        class Output:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"positive": ("CONDITIONING",), "latent": ("LATENT",)}}
            RETURN_TYPES, FUNCTION, OUTPUT_NODE = (), "consume", True
            def consume(self, positive, latent):
                completed.append(True)
                return ()

        class Server:
            client_id = last_node_id = None
            def send_sync(self, *args):
                pass

        for name in ["YtonEasyMediaLoader", "YtonImageListParser", "YtonVideoListParser", "YtonAudioListParser", "YtonVideoParser"]:
            nodes.NODE_CLASS_MAPPINGS[name] = getattr(media_nodes, name)
        nodes.NODE_CLASS_MAPPINGS.update({"YtonTestH3Clip": ClipLoader, "YtonTestH3": MiniMaxH3ReferenceToVideo, "YtonTestH3Output": Output})

        async def run():
            for image_count, video_count, audio_count in [(0, 0, 0), (2, 1, 0), (1, 0, 0), (0, 0, 2), (0, 3, 0), (9, 0, 0), (9, 3, 3)]:
                with self.subTest(images=image_count, videos=video_count, audios=audio_count):
                    files = {name: "" for name in media_nodes.YtonEasyMediaLoader.INPUT_TYPES()["required"]}
                    for kind, count, filename in [("image", image_count, "nested/alpha.png"), ("video", video_count, "reference.mkv"), ("audio", audio_count, "voice.wav")]:
                        for index in range(media_nodes.MEDIA_SLOTS[kind] - count + 1, media_nodes.MEDIA_SLOTS[kind] + 1):
                            files[f"{kind}_{index}"] = filename
                    prompt = {
                        "1": {"class_type": "YtonEasyMediaLoader", "inputs": files},
                        "2": {"class_type": "YtonImageListParser", "inputs": {"image": ["1", 0]}},
                        "3": {"class_type": "YtonVideoListParser", "inputs": {"video": ["1", 1]}},
                        "4": {"class_type": "YtonAudioListParser", "inputs": {"audio": ["1", 2]}},
                        **{str(5 + index): {"class_type": "YtonVideoParser", "inputs": {"video": ["3", index], "force_rate": 24.0}} for index in range(3)},
                        "8": {"class_type": "YtonTestH3Clip", "inputs": {}},
                        "9": {"class_type": "YtonTestH3", "inputs": {
                            "clip": ["8", 0], "prompt": "验证素材传入", "width": 64, "height": 64, "length": 22, "ref_image_size": "match",
                            **{f"ref_images.ref_image_{index}": ["2", index] for index in range(9)},
                            **{f"ref_videos.ref_video_{index}": [str(5 + index), 0] for index in range(3)},
                            **{f"ref_video_audios.ref_video_audio_{index}": [str(5 + index), 2] for index in range(3)},
                            **{f"ref_audios.ref_audio_{index}": ["4", index] for index in range(3)},
                        }},
                        "10": {"class_type": "YtonTestH3Output", "inputs": {"positive": ["9", 0], "latent": ["9", 1]}},
                    }
                    label = f"yton-h3-{image_count}-{video_count}-{audio_count}"
                    valid, errors, outputs, node_errors = await execution.validate_prompt(label, prompt, None)
                    self.assertTrue(valid, (errors, node_errors))
                    executor = execution.PromptExecutor(Server(), cache_type=execution.CacheType.CLASSIC, cache_args={"ram": 0, "ram_inactive": 0})
                    await executor.execute_async(prompt, label, execute_outputs=outputs)
                    self.assertTrue(executor.success, executor.status_messages)
                    self.assertEqual(encoded[-1], ['image'] * image_count + ['audio', 'video'] * video_count + ['audio'] * audio_count)
            self.assertEqual(len(completed), 7)

        asyncio.run(run())

    def test_missing_files_and_modified_files(self):
        loader = media_nodes.YtonEasyMediaLoader
        self.assertIn("素材文件不存在", loader.VALIDATE_INPUTS(image_1="missing.png"))
        before = loader.IS_CHANGED(image_1="nested/alpha.png")
        path = self.root / "nested" / "alpha.png"
        stamp = path.stat().st_mtime_ns
        os.utime(path, ns=(stamp, stamp + 1_000_000_000))
        self.assertNotEqual(before, loader.IS_CHANGED(image_1="nested/alpha.png"))
        self.assertEqual(loader.VALIDATE_INPUTS(), True)

    def test_comfy_execution_graph_keeps_populated_and_empty_inputs(self):
        import execution
        import nodes

        received = []

        class OutputCheck:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"image": ("IMAGE",), "frames": ("IMAGE",), "frame_count": ("INT",),
                                     "video_info": ("VHS_VIDEOINFO",), "audio": ("AUDIO",)}}

            RETURN_TYPES = ()
            FUNCTION = "consume"
            OUTPUT_NODE = True

            def consume(self, image, frames, frame_count, video_info, audio):
                received.append((tuple(image.shape) if image is not None else None, tuple(frames.shape), frame_count,
                                 video_info["loaded_fps"], audio["sample_rate"]))
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
            prompt[list_id] = {"class_type": f"Yton{kind}ListParser", "inputs": {kind.lower(): ["1", loader_slot]}}
            prompt[item_id] = {"class_type": f"Yton{kind}Parser", "inputs": {kind.lower(): [list_id, item_slot]}}
            if kind == "Video":
                prompt[item_id]["inputs"]["force_rate"] = 0.0
        video_outputs = {"frames": ["5", 0], "frame_count": ["5", 1], "video_info": ["5", 3], "audio": ["7", 0]}
        prompt["8"] = {"class_type": "YtonTestOutput", "inputs": {"image": ["3", 0], **video_outputs}}
        prompt["9"] = {"class_type": "YtonImageParser", "inputs": {"image": ["2", 1]}}
        prompt["10"] = {"class_type": "YtonTestOutput", "inputs": {"image": ["9", 0], **video_outputs}}

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
        self.assertCountEqual(received, [((1, 6, 8, 3), (3, 16, 16, 3), 3, 5.0, 16000),
                                         (None, (3, 16, 16, 3), 3, 5.0, 16000)])

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
