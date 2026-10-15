"""Run with ComfyUI's Python, its root on PYTHONPATH, and --cpu in sys.argv."""

import asyncio
from fractions import Fraction
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

import av
from comfy_api.latest import InputImpl, Types, io
from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo
import execution
import folder_paths
import nodes
import numpy as np
from PIL import Image
import torch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("yton_h3_test", ROOT / "__init__.py",
                                            submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
ReferenceNode = package.NODE_CLASS_MAPPINGS["YtonMiniMaxH3ReferenceToVideo"]


class Clip:
    def __init__(self):
        self.references = []
        self.prompts = []

    def tokenize(self, prompt, minimax_ref_items):
        self.prompts.append(prompt)
        self.references.append(minimax_ref_items)
        return prompt

    def encode_from_tokens_scheduled(self, tokens):
        return [[torch.zeros(1, 2, 4), {}]]


class VideoVae:
    def encode(self, frames):
        return torch.full((1, 24, 2, frames.shape[1] // 16, frames.shape[2] // 16),
                          float(frames.mean()))


class AudioVae:
    audio_sample_rate = 32000

    def encode(self, waveform):
        return torch.full((1, 32, 2, 4), float(waveform.mean()))


def audio(value):
    return {"waveform": torch.full((1, 1, 3200), value), "sample_rate": 32000}


def video(value, soundtrack=None):
    return InputImpl.VideoFromComponents(Types.VideoComponents(
        images=torch.full((60, 32, 32, 3), value), frame_rate=Fraction(30), audio=soundtrack))


class ReferenceNodeTests(unittest.TestCase):
    def inputs(self, **extra):
        return {"clip": [Clip()], "prompt": ["参考生成"], "width": [32], "height": [32],
                "length": [22], "ref_image_size": ["match"], **extra}

    def test_official_parameters_and_outputs_are_preserved(self):
        official = MiniMaxH3ReferenceToVideo.INPUT_TYPES()
        actual = ReferenceNode.INPUT_TYPES()
        self.assertEqual(actual["required"], official["required"])
        for name in ["vae", "audio_vae"]:
            self.assertEqual(actual["optional"][name], official["optional"][name])
        self.assertEqual(list(actual["optional"]), ["vae", "audio_vae", "image", "video", "audio"])
        self.assertEqual([actual["optional"][name][0] for name in ["image", "video", "audio"]],
                         ["IMAGE", "VIDEO", "AUDIO"])
        self.assertEqual(ReferenceNode.RETURN_TYPES, MiniMaxH3ReferenceToVideo.RETURN_TYPES)
        self.assertEqual(ReferenceNode.RETURN_NAMES, MiniMaxH3ReferenceToVideo.RETURN_NAMES)
        self.assertTrue(ReferenceNode.INPUT_IS_LIST)
        self.assertFalse(MiniMaxH3ReferenceToVideo.INPUT_IS_LIST)

    def test_lists_and_scalar_settings_delegate_once_with_paired_soundtracks(self):
        first, second = torch.zeros(1, 32, 32, 3), torch.ones(1, 32, 32, 3)
        soundtrack, standalone = audio(0.2), audio(0.8)
        vae, audio_vae, clip = VideoVae(), AudioVae(), Clip()
        expected = io.NodeOutput(object(), object())
        with patch.object(MiniMaxH3ReferenceToVideo, "execute", return_value=expected) as official:
            result = ReferenceNode.execute(**self.inputs(
                clip=[clip], width=[64], height=[96], length=[39], ref_image_size=["max"],
                vae=[vae], audio_vae=[audio_vae], image=[first, None, second],
                video=[None, video(0.4, soundtrack), video(0.6)], audio=[None, standalone]))
        self.assertIs(result, expected)
        official.assert_called_once()
        inputs = official.call_args.kwargs
        for name, value in {"clip": clip, "vae": vae, "audio_vae": audio_vae,
                            "width": 64, "height": 96, "length": 39, "ref_image_size": "max"}.items():
            self.assertEqual(inputs[name], value)
        self.assertIs(inputs["ref_images"]["ref_image_1"], first)
        self.assertIsNone(inputs["ref_images"]["ref_image_2"])
        self.assertIs(inputs["ref_images"]["ref_image_3"], second)
        self.assertIsNone(inputs["ref_videos"]["ref_video_1"])
        self.assertEqual(inputs["ref_videos"]["ref_video_2"].shape[0], 48)
        self.assertIs(inputs["ref_video_audios"]["ref_video_audio_2"], soundtrack)
        self.assertIsNone(inputs["ref_video_audios"]["ref_video_audio_3"])
        self.assertIsNone(inputs["ref_audios"]["ref_audio_1"])
        self.assertIs(inputs["ref_audios"]["ref_audio_2"], standalone)

    def test_actual_official_conditioning_and_latent_match(self):
        first, second = torch.zeros(1, 64, 32, 3), torch.ones(1, 32, 64, 3)
        soundtrack, standalone = audio(0.2), audio(0.8)
        source = video(0.4, soundtrack)
        frames, _, track, _ = package.nodes.media_loader_node.YtonVideoParser().parse_video(source, 24)
        for size in ["match", "max"]:
            with self.subTest(size=size):
                actual_clip, official_clip = Clip(), Clip()
                actual = ReferenceNode.execute(**self.inputs(
                    clip=[actual_clip], ref_image_size=[size], vae=[VideoVae()], audio_vae=[AudioVae()],
                    image=[first, None, second], video=[None, source], audio=[None, standalone]))
                expected = MiniMaxH3ReferenceToVideo.execute(
                    official_clip, "参考生成", 32, 32, 22, ref_image_size=size,
                    vae=VideoVae(), audio_vae=AudioVae(), ref_images={"ref_image_1": first, "ref_image_3": second},
                    ref_videos={"ref_video_2": frames}, ref_video_audios={"ref_video_audio_2": track},
                    ref_audios={"ref_audio_2": standalone})
                actual_items, expected_items = actual_clip.references[0], official_clip.references[0]
                self.assertEqual([item["type"] for item in actual_items], ["image", "image", "audio", "video", "audio"])
                for received, wanted in zip(actual_items, expected_items):
                    self.assertEqual(set(received), set(wanted))
                    for key in received:
                        if isinstance(received[key], torch.Tensor):
                            torch.testing.assert_close(received[key], wanted[key])
                        else:
                            self.assertEqual(received[key], wanted[key])
                blocks = actual[0][0][1]["minimax_refs"]
                self.assertEqual([block["kind"] for block in blocks], ["image", "image", "video_audio", "audio"])
                for received, wanted in zip(blocks, expected[0][0][1]["minimax_refs"]):
                    for key in received:
                        if isinstance(received[key], torch.Tensor):
                            torch.testing.assert_close(received[key], wanted[key])
                        else:
                            self.assertEqual(received[key], wanted[key])
                for received, wanted in zip(actual[1]["samples"].tensors, expected[1]["samples"].tensors):
                    torch.testing.assert_close(received, wanted)

    def test_optional_media_and_vaes_can_be_absent(self):
        for media in [{}, {"image": [], "video": [], "audio": []},
                      {"image": [None], "video": [None], "audio": [None]},
                      {"video": [video(0.4, audio(0.2))], "audio": [audio(0.8)]}]:
            inputs = self.inputs(**media)
            result = ReferenceNode.execute(**inputs)
            self.assertEqual(len(inputs["clip"][0].references), 1)
            self.assertNotIn("minimax_refs", result[0][0][1])
            self.assertEqual(len(result[1]["samples"].tensors), 2)

    def test_media_loader_executes_whole_lists_as_one_generation(self):
        with tempfile.TemporaryDirectory(prefix="yton-h3-") as directory:
            previous_input = folder_paths.get_input_directory()
            folder_paths.set_input_directory(directory)
            self.addCleanup(folder_paths.set_input_directory, previous_input)
            root = Path(directory)
            Image.new("RGB", (32, 32), (120, 80, 40)).save(root / "image.png")
            with wave.open(str(root / "audio.wav"), "wb") as file:
                file.setnchannels(1)
                file.setsampwidth(2)
                file.setframerate(32000)
                file.writeframes(np.zeros(3200, dtype=np.int16).tobytes())
            with av.open(str(root / "video.mp4"), "w") as output:
                stream = output.add_stream("mpeg4", rate=30)
                stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
                for _ in range(30):
                    frame = av.VideoFrame.from_ndarray(np.full((32, 32, 3), 100, dtype=np.uint8), format="rgb24")
                    for packet in stream.encode(frame):
                        output.mux(packet)
                for packet in stream.encode():
                    output.mux(packet)

            clip = Clip()
            completed = []

            class ClipLoader:
                INPUT_TYPES = classmethod(lambda cls: {"required": {}})
                RETURN_TYPES = ("CLIP",)
                FUNCTION = "load"

                def load(self):
                    return (clip,)

            class Output:
                INPUT_TYPES = classmethod(lambda cls: {"required": {"positive": ("CONDITIONING",), "latent": ("LATENT",)}})
                RETURN_TYPES = ()
                FUNCTION = "consume"
                OUTPUT_NODE = True

                def consume(self, positive, latent):
                    completed.append(latent)
                    return ()

            class Server:
                client_id = None
                last_node_id = None

                def send_sync(self, *args):
                    pass

            mappings = {**package.NODE_CLASS_MAPPINGS, "YtonH3TestClipLoader": ClipLoader, "YtonH3TestOutput": Output}

            async def run():
                for mode in ["populated", "disabled", "empty", "unconnected"]:
                    files = {name: "" for name in package.NODE_CLASS_MAPPINGS["YtonEasyMediaLoader"].INPUT_TYPES()["required"]}
                    if mode in ["populated", "disabled"]:
                        files.update(image_1="image.png", image_2="image.png", video_1="video.mp4", audio_1="audio.wav")
                    if mode == "disabled":
                        files.update(disable_image_1=True, disable_video_1=True, disable_audio_1=True)
                    inputs = {"clip": ["2", 0], "prompt": "测试", "width": 32, "height": 32, "length": 22,
                              "ref_image_size": "match"}
                    if mode != "unconnected":
                        inputs.update(image=["1", 0], video=["1", 1], audio=["1", 2])
                    prompt = {"1": {"class_type": "YtonEasyMediaLoader", "inputs": files},
                              "2": {"class_type": "YtonH3TestClipLoader", "inputs": {}},
                              "3": {"class_type": "YtonMiniMaxH3ReferenceToVideo", "inputs": inputs},
                              "4": {"class_type": "YtonH3TestOutput", "inputs": {"positive": ["3", 0], "latent": ["3", 1]}}}
                    valid, errors, outputs, node_errors = await execution.validate_prompt(mode, prompt, None)
                    self.assertTrue(valid, (errors, node_errors))
                    executor = execution.PromptExecutor(Server(), cache_type=execution.CacheType.CLASSIC,
                                                        cache_args={"ram": 0, "ram_inactive": 0})
                    before = len(clip.references)
                    await executor.execute_async(prompt, mode, execute_outputs=outputs)
                    self.assertTrue(executor.success, executor.status_messages)
                    self.assertEqual(len(clip.references), before + 1)
                    self.assertEqual(len(completed), before + 1)
                    self.assertEqual([item["type"] for item in clip.references[-1]],
                                     {"populated": ["image", "image", "video", "audio"],
                                      "disabled": ["image"], "empty": [], "unconnected": []}[mode])

            with patch.dict(nodes.NODE_CLASS_MAPPINGS, mappings):
                asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
