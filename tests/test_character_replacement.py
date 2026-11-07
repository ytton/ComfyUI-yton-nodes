"""CPU integration tests: real files, audio, segment boundaries and loop state."""

from copy import deepcopy
import asyncio
from dataclasses import dataclass, field
from fractions import Fraction
from datetime import date, datetime
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid

import av

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN.parents[1]))
sys.argv = [sys.argv[0], "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()
import torch
from comfy_api.latest import InputImpl, Types, io
from comfy_execution.graph import DynamicPrompt
import folder_paths

package = types.ModuleType("replacement_test_plugin")
package.__path__ = [str(PLUGIN)]
sys.modules[package.__name__] = package
from replacement_test_plugin.llm_connection import LLMConnection
from replacement_test_plugin.replacement.media import contact_sheet, encode, ffmpeg, inspect, output_size, reference_images, reference_size, segment_video
from replacement_test_plugin.replacement.nodes import CLASSES, DEFAULT_CONFIG, YtonCharacterReplacement, YtonReplacementPlan, YtonReplacementSegment, YtonReplacementVideoSave
from replacement_test_plugin.replacement.plan import make_plan, shot_segments
from replacement_test_plugin.replacement.shots import shot_plan, _cut_frames
from replacement_test_plugin.replacement.media import plan_for
from replacement_test_plugin.replacement.prompts import SYSTEM, load_skill, optimize, save_skill, signature
from replacement_test_plugin.replacement.save import execution_state, save_segment
from PIL import Image


def camera_cut_video(root):
    source = root / "input/camera-cuts.mp4"
    encode(["-f", "lavfi", "-i", "color=red:size=160x96:rate=24:duration=1.5",
            "-f", "lavfi", "-i", "color=lime:size=160x96:rate=24:duration=2",
            "-f", "lavfi", "-i", "color=blue:size=160x96:rate=24:duration=3",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", source])
    return source


@dataclass(frozen=True)
class FakeLLM:
    calls: list = field(default_factory=list, compare=False, hash=False)

    def generate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return "【主体替换】将 <Video 1> 的人物替换为 <Picture 1>。\n【角色外观】依照参考图。\n【背景】保留原背景。\n【同步要求】逐帧同步。\n【负面提示】重影、身份漂移。"


class ReplacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="yton-replacement-test-")
        cls.root = Path(cls.directory.name)
        for name in ("input", "output", "temp", "user"):
            (cls.root / name).mkdir()
        cls.patches = [patch.object(folder_paths, f"get_{name}_directory", return_value=str(cls.root / name))
                       for name in ("input", "output", "temp", "user")]
        for item in cls.patches:
            item.start()
        # Motion, colored patches and a real audio stream, all on CPU.
        encode(["-f", "lavfi", "-i", "testsrc2=size=160x96:rate=24:duration=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cls.root / "input/source.mp4"])
        Image.new("RGB", (120, 240), "red").save(cls.root / "input/red.png")
        Image.new("RGB", (240, 90), "blue").save(cls.root / "input/blue.png")

    @classmethod
    def tearDownClass(cls):
        for item in cls.patches:
            item.stop()
        cls.directory.cleanup()

    def config(self):
        config = deepcopy(DEFAULT_CONFIG)
        config.update(video="source.mp4", images=["red.png", "", "blue.png", "", "", ""], image_scale=.5)
        config["plan"].update(enabled=True, frames=39, overlap=5)
        config["compression"]["max_edge"] = 160
        return config

    def node(self, dynprompt=None, uid="config"):
        cls = type("ReplacementTestNode", (YtonCharacterReplacement,), {})
        cls.hidden = io.HiddenHolder.from_dict({io.Hidden.unique_id: uid, io.Hidden.dynprompt: dynprompt or DynamicPrompt({})})
        return cls

    def test_h3_and_ordinary_plans(self):
        settings = dict(enabled=True, mode="MiniMax H3", frames=175, overlap=22, output="完整片段")
        self.assertEqual(make_plan(settings,18)["segments"], [{"start":0,"end":175},{"start":153,"end":328},{"start":306,"end":432}])
        settings["output"]="仅新增片段"
        self.assertEqual(make_plan(settings,18)["segments"], [{"start":0,"end":175},{"start":175,"end":350},{"start":350,"end":432}])
        settings.update(mode="普通", seconds=7.91)
        self.assertEqual(make_plan(settings,18)["raw_frames"],190)
        settings.update(start=1/48,end=2)
        self.assertEqual(make_plan(settings,18)["segments"][0]["start"],1)

    def test_segment_crop_frames_audio_and_scaling(self):
        config=self.config()
        config["crop"]=[.1,0,.8,1]
        video,plan=segment_video(config,1)
        components=video.get_components()
        self.assertEqual(components.images.shape[0],38) # 34..71 inclusive.
        self.assertEqual(components.frame_rate,Fraction(24))
        self.assertIsNotNone(components.audio)
        self.assertLessEqual(max(components.images.shape[1:3]),160)
        self.assertEqual([image.size for image in reference_images(config)],[(60,120),(120,45)])
        self.assertEqual(contact_sheet(video).size,(960,600))
        with self.assertRaisesRegex(ValueError,"超出范围"):
            segment_video(config,99)

    def test_shot_boundaries_limit_context_and_cover_the_whole_range(self):
        settings = dict(enabled=True, mode="MiniMax H3", frames=175, overlap=22,
                        output="完整片段", split="shots", cuts=[72, 360], min_seconds=.5)
        segments = make_plan(settings, 18)["segments"]
        self.assertEqual(segments[0]["start"], 0)
        self.assertEqual(segments[-1]["end"], 432)
        self.assertEqual([s["start"] for s in segments if s["cut_before"]], [72, 360])
        for index, segment in enumerate(segments):
            self.assertLessEqual(segment["end"] - segment["start"], 175)
            self.assertFalse(any(segment["start"] < cut < segment["end"] for cut in (72, 360)))
            if index:
                self.assertEqual(segments[index - 1]["end"] - segment["start"], segment["context_frames"])
                self.assertEqual(segment["context_frames"], 0 if segment["cut_before"] else 22)
        settings.update(start=2, end=17, output="仅新增片段")
        cropped = make_plan(settings, 18)["segments"]
        self.assertEqual((cropped[0]["start"], cropped[-1]["end"]), (48, 408))
        self.assertTrue(all(a["end"] == b["start"] for a, b in zip(cropped, cropped[1:])))

    def test_short_shots_merge_only_when_the_combination_fits(self):
        merged = shot_segments(0, 192, [8, 72], 96, 24, 0)
        self.assertNotIn(8, [s["start"] for s in merged])
        self.assertIn(72, [s["start"] for s in merged])
        retained = shot_segments(0, 210, [10], 100, 24, 0)
        self.assertIn(10, [s["start"] for s in retained])
        self.assertTrue(all(s["end"] - s["start"] <= 100 for s in retained))

    def test_manual_segment_lengths_control_media_and_preserve_context(self):
        config = self.config()
        config["plan"]["manual_segments"] = [{"start": 0, "end": 30}, {"start": 25, "end": 72}]
        _, plan = plan_for(config)
        self.assertEqual([(s["start"], s["end"], s["context_frames"]) for s in plan["segments"]], [(0,30,0),(25,72,5)])
        result, _ = segment_video(config, 1)
        self.assertEqual(result.get_frame_count(), 47)
        config["plan"]["manual_segments"][1]["start"] = 26
        with self.assertRaisesRegex(ValueError, "上下文长度"):
            plan_for(config)
        config["plan"]["manual_segments"] = [{"start": 0, "end": 30}, {"start": 30, "end": 72, "cut_before": True}]
        self.assertEqual(plan_for(config)[1]["segments"][1]["context_frames"], 0)
        config["plan"]["manual_segments"][1]["end"] = 71
        with self.assertRaisesRegex(ValueError, "完整覆盖"):
            plan_for(config)

    def test_real_cut_detection_and_saved_plan_do_not_reanalyse_on_generation(self):
        source = camera_cut_video(self.root)
        config = self.config()
        config["video"] = source.name
        config["plan"].update(frames=56, split="shots", min_seconds=.2, sensitivity=.8)
        for detector in ("adaptive", "content"):
            with self.subTest(detector=detector):
                result = shot_plan(source.name, {**config["plan"], "detector": detector})
                self.assertEqual(result["settings"]["cuts"], [36, 84])
                self.assertEqual([s["start"] for s in result["plan"]["segments"] if s["cut_before"]], [36, 84])
                config["plan"] = result["settings"]
                with patch("replacement_test_plugin.replacement.shots._cut_frames", side_effect=AssertionError("detector reran")):
                    _, saved = plan_for(config)
                    self.assertEqual(saved, result["plan"])
                    cut_index = next(i for i, s in enumerate(saved["segments"]) if s["start"] == 36)
                    video, _ = segment_video(config, cut_index)
                    pixels = video.get_components().images
                    self.assertEqual(len(pixels), 48)
                    self.assertGreater(float(pixels[0, :, :, 1].mean()), .9)
        self.assertGreaterEqual(_cut_frames.cache_info().currsize, 2)
        config["video"] = "source.mp4"
        with self.assertRaisesRegex(ValueError, "原视频已改变"):
            plan_for(config)

    def test_config_parser_disables_previous_context_at_a_camera_cut(self):
        config = self.config()
        config["plan"].update(split="shots", cuts=[34], shot_source=config["video"], min_seconds=0)
        _, planned = plan_for(config)
        parser = type("CameraCutParser", (YtonReplacementSegment,), {})
        parser.hidden = self.node().hidden
        previous, _ = segment_video(config, 0)
        plan = {"config": json.dumps(config), "llm": None, "index": 1,
                "segment": planned["segments"][1], "previous_video": previous}
        self.assertEqual(parser.execute(plan=plan).result[10:], (None, False, []))
        plan["segment"] = {**plan["segment"], "cut_before": False}
        self.assertEqual(parser.execute(plan=plan).result[10:], (previous, True, []))

    def test_output_contract_and_alias_identity(self):
        config=self.config()
        config["original"]="将 @视频 的人物替换成 @图片3。"
        output=self.node().execute(config=json.dumps(config), index=0)
        self.assertEqual(len(output.result),10)
        self.assertIn("<Picture 2>",output.result[2])
        self.assertEqual([tuple(i.shape) for i in output.result[0]],[(1,120,60,3),(1,45,120,3)])
        self.assertEqual(len(output.result[1]),1)
        self.assertEqual(output.result[7:9],(1,2))
        self.assertEqual(output.result[3:7],(800,480,39,39/24))
        self.assertEqual(output.result[1][0].get_dimensions(),(160,96))
        self.assertEqual(output.result[9], "video/人物替换/%date:yyyy-MM-dd%/source/")
        config["images"]=[""]*6
        self.assertEqual(self.node().execute(config=json.dumps(config), index=0).result[0],[])

    def test_target_dimensions_and_reference_length(self):
        config=self.config()
        tail=self.node().execute(config=json.dumps(config), index=1)
        self.assertEqual(tail.result[3:7],(800,480,38,38/24))
        config["crop"]=[.1,0,.8,1]
        config["plan"].update(enabled=False,seconds=1.25)
        config["compression"].update(width=96,height=64,fps=12)
        output=self.node().execute(config=json.dumps(config), index=0)
        self.assertEqual(output.result[3:7],(640,480,15,1.25))
        video=output.result[1][0].get_components()
        self.assertEqual((video.images.shape[2],video.images.shape[1],video.images.shape[0]),(96,64,15))

    def test_selected_segment_without_index_and_external_zero_takes_priority(self):
        config = self.config()
        config["prompts"] = {"0": "first segment", "1": "second segment", "shared": "shared prompt"}
        for shared in (False, True):
            with self.subTest(shared=shared):
                config["shared"] = shared
                node = self.node()
                selected = node.execute(config=json.dumps(config), selected_index=1)
                self.assertEqual(selected.result[5:9], (38, 38/24, 2, 2))
                self.assertEqual(selected.result[2], "shared prompt" if shared else "second segment")
                self.assertEqual(selected.result[1][0].get_stream_source(), segment_video(config, 1)[0].get_stream_source())
                first = node.execute(config=json.dumps(config), selected_index=1, index=0)
                self.assertEqual(first.result[5:9], (39, 39/24, 1, 2))
                self.assertEqual(first.result[2], "shared prompt" if shared else "first segment")

    def test_config_parser_only_accepts_the_current_segment_configuration(self):
        config = self.config()
        planner = type("SelectedPlanTestNode", (YtonReplacementPlan,), {})
        parser = type("SelectedSegmentTestNode", (YtonReplacementSegment,), {})
        for node in (planner, parser):
            node.hidden = io.HiddenHolder.from_dict({io.Hidden.unique_id: node.__name__, io.Hidden.dynprompt: DynamicPrompt({})})
        plan = planner.execute(json.dumps(config), selected_index=1).result[0]
        self.assertEqual(parser.execute(plan=plan).result[5:9], (38, 38/24, 2, 2))
        self.assertEqual([item.id for item in parser.define_schema().inputs], ["plan"])
        self.assertEqual(len(planner.define_schema().outputs), 1)
        self.assertEqual(parser.execute(plan=plan).result[10:], (None, False, []))

    def test_index_selection_inputs_validate_and_execute(self):
        import execution
        import nodes
        from server import PromptServer

        config = self.config()
        for node in (YtonCharacterReplacement, YtonReplacementPlan):
            inputs = node.GET_NODE_INFO_V1()["input"]
            self.assertIn("selected_index", inputs["optional"])
            self.assertNotIn("selected_index", inputs["required"])
        prompt = {
            "save": {"class_type": "YtonReplacementVideoSave", "inputs": {
                "video": ["media", 1], "current": ["media", 7], "total": ["media", 8],
                "filename_prefix": "selected/segment", "container": "mp4", "fps": 24, "crf": 18,
                "reuse_existing": False, "save_full": False}},
        }
        mapping = {cls.__name__: cls for cls in CLASSES}
        server = types.SimpleNamespace(client_id=None, last_node_id=None,
            send_sync=lambda *args: None, send_progress_text=lambda *args: None)
        cases = [
            ("panel", False, {"selected_index": 1}, 2, 38),
            ("external", False, {"index": 1}, 2, 38),
            ("initial", False, {}, 1, 39),
            ("parser_selected", True, {"selected_index": 1}, 2, 38),
            ("parser_initial", True, {}, 1, 39),
        ]
        for name, parser, selection, expected_segment, expected_frames in cases:
            with self.subTest(name=name):
                submitted = deepcopy(prompt)
                submitted["save"]["inputs"]["filename_prefix"] = f"selected/{name}"
                if parser:
                    submitted["plan"] = {"class_type": "YtonReplacementPlan", "inputs": {"config": json.dumps(config), "loop_generation": False, **selection}}
                    submitted["media"] = {"class_type": "YtonReplacementSegment", "inputs": {"plan": ["plan", 0]}}
                else:
                    submitted["media"] = {"class_type": "YtonCharacterReplacement", "inputs": {"config": json.dumps(config), **selection}}
                with patch.dict(nodes.NODE_CLASS_MAPPINGS, mapping), patch.object(PromptServer, "instance", server, create=True):
                    valid, error, outputs, errors = asyncio.run(execution.validate_prompt(name, submitted, None))
                    self.assertTrue(valid, (error, errors))
                    executor = execution.PromptExecutor(server, cache_type=execution.CacheType.CLASSIC,
                                                        cache_args={"ram": 0, "ram_inactive": 0})
                    asyncio.run(executor.execute_async(submitted, uuid.uuid4().hex, execute_outputs=outputs))
                    self.assertTrue(executor.success, executor.status_messages)
                manifest = next((self.root / "output/selected").glob(f"{name}_*/segments.json"))
                self.assertEqual(list(json.loads(manifest.read_text())["segments"]), [str(expected_segment)])
                video = InputImpl.VideoFromFile(str(manifest.parent / f"segment_{expected_segment:04d}.mp4"))
                self.assertEqual(video.get_frame_count(), expected_frames)

    def test_original_ratio_resolution_uses_short_edge(self):
        config = self.config()
        config["ratio"] = "原视频"
        config["compression"]["max_edge"] = 0
        for resolution, portrait, landscape, square in (
            ("480p", (480, 864), (864, 480), (480, 480)),
            ("720p", (704, 1280), (1280, 704), (704, 704)),
            ("1080p", (1088, 1920), (1920, 1088), (1088, 1088)),
        ):
            config["resolution"] = resolution
            for size, expected in (((1080, 1918), portrait), ((1920, 1080), landscape), ((1080, 1080), square)):
                with self.subTest(resolution=resolution, source=size):
                    self.assertEqual(output_size(config, dict(zip(("width", "height"), size))), expected)
        config["crop"] = [0, 0, .31640625, 1]  # A 9:16 crop from 1920x1080.
        self.assertEqual(output_size(config, {"width": 1920, "height": 1080}), (1088, 1920))

    def test_portrait_1080p_target_keeps_reference_dimensions(self):
        encode(["-f", "lavfi", "-i", "color=c=blue:size=90x160:rate=24:duration=0.25",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", self.root / "input/portrait.mp4"])
        config = self.config()
        config.update(video="portrait.mp4", ratio="原视频", resolution="1080p")
        config["compression"]["max_edge"] = 0
        for ratio, size in (("原视频", (1088, 1920)), ("9:16", (1088, 1920)), ("16:9", (1920, 1088))):
            with self.subTest(ratio=ratio):
                config["ratio"] = ratio
                output = self.node().execute(config=json.dumps(config), index=0)
                self.assertEqual(output.result[3:6], (*size, 6))
                self.assertEqual((output.ui["replacement_prompt"][0]["width"], output.ui["replacement_prompt"][0]["height"]), size)
                video = output.result[1][0]
                self.assertEqual(video.get_dimensions(), (90, 160))
                self.assertEqual(tuple(video.get_components().images.shape), (6, 160, 90, 3))

    def test_generation_size_is_independent_of_reference_compression(self):
        config = self.config()
        metadata = {"width": 1080, "height": 1918}
        config.update(ratio="9:16", resolution="1080p")
        config["compression"]["max_edge"] = 0
        self.assertEqual(output_size(config, metadata), (1088, 1920))
        config["compression"]["max_edge"] = 160
        self.assertEqual(output_size(config, metadata), (1088, 1920))
        self.assertEqual(reference_size(config, metadata), (90, 160))
        config["compression"].update(width=768, height=1024, max_edge=0)
        self.assertEqual(output_size(config, metadata), (1088, 1920))
        self.assertEqual(reference_size(config, metadata), (768, 1024))

    def test_compressed_540p_reference_with_1080p_generation(self):
        config = self.config()
        config.update(ratio="9:16", resolution="1080p")
        config["compression"].update(width=540, height=960, max_edge=0)
        output = self.node().execute(config=json.dumps(config), index=0)
        video = output.result[1][0]
        self.assertEqual(video.get_dimensions(), (540, 960))
        self.assertEqual(output.result[3:7], (1088, 1920, 39, 39/24))
        self.assertEqual((output.ui["replacement_prompt"][0]["width"], output.ui["replacement_prompt"][0]["height"]), (1088, 1920))
        config.update(ratio="16:9", resolution="720p")
        changed = self.node().execute(config=json.dumps(config), index=0)
        self.assertEqual(changed.result[3:5], (1280, 704))
        self.assertEqual(changed.result[1][0].get_stream_source(), video.get_stream_source())

    def test_reference_dimensions_preserve_source_and_resize_options(self):
        config = self.config()
        config["compression"]["max_edge"] = 0
        metadata = {"width": 1080, "height": 1920}
        self.assertEqual(reference_size(config, metadata), (1080, 1920))
        config["compression"].update(width=540, height=0)
        self.assertEqual(reference_size(config, metadata), (540, 960))
        config["compression"].update(width=0, height=960)
        self.assertEqual(reference_size(config, metadata), (540, 960))
        config["compression"].update(width=540, height=540, resize_method="maintain aspect ratio")
        self.assertEqual(reference_size(config, metadata), (304, 540))
        config["compression"].update(width=0, height=0)
        config["crop"] = [0, 0, 1, .5]
        self.assertEqual(reference_size(config, metadata), (1080, 960))

    def test_project_directory_uses_source_video_name_for_every_segment(self):
        source = self.root / "input/引用视频/舞蹈参考.v1.mp4"
        source.parent.mkdir(exist_ok=True)
        source.write_bytes((self.root / "input/source.mp4").read_bytes())
        config = self.config()
        config["video"] = "引用视频/舞蹈参考.v1.mp4 [input]"
        node = self.node()
        for index in (0, 1):
            self.assertEqual(node.execute(config=json.dumps(config), index=index).result[9],
                             "video/人物替换/%date:yyyy-MM-dd%/舞蹈参考.v1/")

    def test_auto_shared_once_per_run_and_per_segment(self):
        config=self.config(); config.update(auto=True,shared=True)
        llm=FakeLLM(); node=self.node()
        node.execute(config=json.dumps(config), index=0, llm=llm); node.execute(config=json.dumps(config), index=1, llm=llm)
        self.assertEqual(len(llm.calls),1)
        self.assertEqual(len(llm.calls[0][1]["images"]),3)
        self.node().execute(config=json.dumps(config), index=0, llm=llm)
        self.assertEqual(len(llm.calls),2)
        config["shared"]=False
        node=self.node(); node.execute(config=json.dumps(config), index=0, llm=llm);node.execute(config=json.dumps(config), index=1, llm=llm)
        self.assertEqual(len(llm.calls),4)
        with self.assertRaisesRegex(ValueError,"连接"):
            node.execute(config=json.dumps(config), index=0)

    def test_manual_result_invalidated_by_media_changes(self):
        config=self.config();config["optimized"]["0"]={"text":"manual optimized", "signature":signature(config,0)}
        self.assertEqual(self.node().execute(config=json.dumps(config), index=0).result[2],"manual optimized")
        config["image_scale"]=.75
        self.assertNotEqual(self.node().execute(config=json.dumps(config), index=0).result[2],"manual optimized")

    def test_compression_changes_preserve_optimized_prompt_for_shared_and_segment_modes(self):
        for shared in (False, True):
            with self.subTest(shared=shared):
                config = self.config()
                config["shared"] = shared
                slot = "shared" if shared else "0"
                expected = signature(config, 0)
                config["optimized"][slot] = {"text": "keep optimized", "signature": expected}
                config["compression"].update(width=80, height=48, max_edge=0, crf=28,
                                             resize_method="maintain aspect ratio")
                # The editor derives this informational value from the H3 frame count.
                config["plan"]["seconds"] = config["plan"]["frames"] / 24
                config["plan"]["end"] = 3
                self.assertEqual(signature(config, 0), expected)
                output = self.node().execute(config=json.dumps(config), index=0).result
                self.assertEqual(output[2], "keep optimized")
                self.assertEqual(output[1][0].get_dimensions(), (80, 48))
                self.assertEqual(output[5], 39)

    def test_prompt_signature_changes_for_segment_content_and_crop(self):
        config = self.config()
        expected = signature(config, 0)
        for field, value in (("start", 1 / 24), ("frames", 56), ("overlap", 22)):
            changed = deepcopy(config)
            changed["plan"][field] = value
            self.assertNotEqual(signature(changed, 0), expected)
        changed = deepcopy(config)
        changed["crop"] = [0.1, 0, 0.9, 1]
        self.assertNotEqual(signature(changed, 0), expected)

    def test_custom_skill_persists_and_drives_manual_and_automatic_optimization(self):
        path = self.root / "user/yton-replacement-skill.md"
        self.addCleanup(path.unlink, missing_ok=True)
        self.assertEqual(load_skill(), SYSTEM)
        custom = "保留角色引用，只写两部分：替换要求与动作同步。\n遵循用户自己的叙述方式。"
        self.assertEqual(save_skill(custom), {"skill": custom, "default_skill": SYSTEM})
        self.assertEqual(path.read_text(encoding="utf-8"), custom)
        self.assertEqual(load_skill(), custom)
        config = self.config()
        video, _ = segment_video(config, 0)
        llm = FakeLLM()
        optimize(llm, config, 0, video, reference_images(config))
        config["auto"] = True
        self.node().execute(config=json.dumps(config), index=0, llm=llm)
        self.assertEqual(len(llm.calls), 2)
        self.assertTrue(all(call[1]["system"] == custom for call in llm.calls))
        save_skill(SYSTEM)
        self.assertEqual(load_skill(), SYSTEM)

    def test_skill_changes_invalidate_optimized_results_and_reject_blank_saves(self):
        path = self.root / "user/yton-replacement-skill.md"
        self.addCleanup(path.unlink, missing_ok=True)
        config = self.config()
        config["optimized"]["0"] = {"text": "old optimized", "signature": signature(config, 0)}
        self.assertEqual(self.node().execute(config=json.dumps(config), index=0).result[2], "old optimized")
        save_skill("只根据当前角色参考与用户要求编写提示词。")
        self.assertNotEqual(self.node().execute(config=json.dumps(config), index=0).result[2], "old optimized")
        for value in ("", " \n ", None):
            with self.assertRaisesRegex(ValueError, "不能为空"):
                save_skill(value)
        self.assertEqual(load_skill(), "只根据当前角色参考与用户要求编写提示词。")

    def test_native_loop_expansions_share_correct_owner(self):
        dyn=DynamicPrompt({})
        dyn.add_ephemeral_node("loop.1.config",{},"loop.end","config")
        dyn.add_ephemeral_node("loop.2.config",{},"loop.1.end","config")
        dyn.add_ephemeral_node("loop.1.save",{},"loop.end","save")
        with patch("replacement_test_plugin.replacement.save.datetime") as clock:
            clock.now.return_value = datetime(2026, 11, 3, 14, 0, 30).astimezone()
            a=execution_state(dyn,"loop.1.config")
        self.assertIs(a,execution_state(dyn,"loop.2.config"))
        save_state=execution_state(dyn,"loop.1.save")
        self.assertIsNot(a,save_state)
        self.assertEqual(save_state["started_at"],a["started_at"])
        self.assertEqual(save_state["started_at"].strftime("%H-%M-%S"),"14-00-30")
        self.assertIsNot(a,execution_state(DynamicPrompt({}),"config"))

    def test_loop_plan_does_not_prepare_media_or_optimize(self):
        config = self.config()
        config.update(auto=True, shared=True)
        llm = FakeLLM()
        planner = type("ReplacementPlanTestNode", (YtonReplacementPlan,), {})
        planner.hidden = io.HiddenHolder.from_dict({io.Hidden.unique_id: "plan", io.Hidden.dynprompt: DynamicPrompt({})})
        with patch("replacement_test_plugin.replacement.nodes.segment_video") as prepare:
            plan = planner.execute(json.dumps(config), llm)
        prepare.assert_not_called()
        self.assertEqual(llm.calls, [])
        self.assertEqual(plan.result[0]["total"], 2)
        self.assertIs(plan.result[0]["llm"], llm)
        config["plan"]["frames"] = 22
        self.assertEqual(planner.execute(json.dumps(config)).result[0]["total"], 4)

    def test_internal_loop_starts_at_selected_segment_when_reuse_has_no_project(self):
        import execution
        import nodes
        from server import PromptServer

        config = self.config()
        config["plan"].update(frames=22, overlap=0)

        prompt = {
            "plan": {"class_type": "YtonReplacementPlan", "inputs": {
                "config": json.dumps(config), "selected_index": 1, "loop_generation": True}},
            "segment": {"class_type": "YtonReplacementSegment", "inputs": {"plan": ["plan", 0]}},
            "save": {"class_type": "YtonReplacementVideoSave", "inputs": {
                "video": ["segment", 1], "current": ["segment", 7], "total": ["segment", 8],
                "filename_prefix": "internal-loop/video", "container": "mp4", "fps": 24, "crf": 18,
                "reuse_existing": True, "save_full": True}},
        }
        server = types.SimpleNamespace(client_id=None, last_node_id=None,
            send_sync=lambda *args: None, send_progress_text=lambda *args: None)
        mapping = {cls.__name__: cls for cls in CLASSES}
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, mapping), patch.object(PromptServer, "instance", server, create=True):
            valid, error, outputs, errors = asyncio.run(execution.validate_prompt("internal-replacement-loop", prompt, None))
            self.assertTrue(valid, (error, errors))
            executor = execution.PromptExecutor(server, cache_type=execution.CacheType.CLASSIC,
                cache_args={"ram": 0, "ram_inactive": 0})
            asyncio.run(executor.execute_async(prompt, uuid.uuid4().hex, execute_outputs=outputs))
            self.assertTrue(executor.success, executor.status_messages)
        manifests = list((self.root / "output/internal-loop").glob("video_*/segments.json"))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text())
        self.assertEqual(manifest["total"], 4)
        self.assertEqual(sorted(manifest["segments"]), ["2", "3", "4"])
        self.assertEqual(len(list(manifests[0].parent.glob("segment_*.mp4"))), 3)

    def test_saved_internal_loop_workflow_has_no_official_loop_controls(self):
        workflow = json.loads((PLUGIN / "examples/人物替换专用流-内置循环.json").read_text(encoding="utf-8"))
        prompt = json.loads((PLUGIN / "tests/fixtures/replacement_internal_loop_prompt.json").read_text(encoding="utf-8"))
        self.assertFalse({"StartLoop", "EndLoop", "ComfyNotNode"} & {n["type"] for n in workflow["nodes"]})
        self.assertTrue(prompt["59"]["inputs"]["loop_generation"])
        self.assertEqual(prompt["59"]["inputs"]["selected_index"], 0)
        self.assertEqual(prompt["657"]["inputs"], {"plan": ["59", 0]})
        self.assertEqual(prompt["22"]["inputs"]["video"], ["657", 1])
        self.assertEqual(prompt["60"]["inputs"]["video"], ["22", 0])
        self.assertEqual(prompt["60"]["inputs"]["filename_prefix"], ["657", 9])
        self.assertEqual(prompt["22"]["inputs"]["previous_video"], ["657", 10])
        self.assertEqual(prompt["22"]["inputs"]["enable_context"], ["657", 11])
        self.assertTrue(prompt["22"]["inputs"]["enable_add_guide"])
        self.assertEqual(prompt["22"]["inputs"]["anchor_images"], ["657", 12])
        planner = next(node for node in workflow["nodes"] if node["id"] == 59)
        self.assertEqual(len(planner["outputs"]), 1)
        parser = next(node for node in workflow["nodes"] if node["id"] == 657)
        self.assertEqual(parser["outputs"][12]["name"], "替换关键帧")

    def test_internal_loop_reconnects_previous_video_context_between_segments(self):
        import execution
        import nodes
        from server import PromptServer

        config = self.config()
        config["plan"].update(frames=22, overlap=0)
        from replacement_test_plugin.replacement.anchors import segment_info
        config["anchors"] = {}
        for i in range(4):
            path, _, _ = segment_info(config, i)
            config["anchors"][path.stem] = [{"frame": i, "image": "red.png" if i % 2 == 0 else "blue.png"}]
        observed_anchors = []
        observed = []
        generated = []

        class MockOmni(io.ComfyNode):
            @classmethod
            def define_schema(cls):
                return io.Schema(node_id="YtonH3TraditionalOmniGenerate",
                    inputs=[io.Video.Input("video"), io.Video.Input("previous_video", optional=True),
                            io.Boolean.Input("enable_context"), io.Custom("YTON_H3_ANCHORS").Input("anchor_images")], outputs=[io.Video.Output()])

            @classmethod
            def execute(cls, video, enable_context, anchor_images, previous_video=None):
                observed_anchors.append(anchor_images)
                observed.append((enable_context, previous_video))
                generated.append(video)
                return io.NodeOutput(video)

        saved = []

        class MockSave(io.ComfyNode):
            OUTPUT_NODE = True

            @classmethod
            def define_schema(cls):
                return io.Schema(node_id="YtonReplacementVideoSave",
                    inputs=[io.Video.Input("video"), io.Int.Input("current"), io.Int.Input("total")],
                    outputs=[io.Video.Output()])

            @classmethod
            def execute(cls, video, current, total):
                result = segment_video(config, current - 1)[0]
                saved.append(result)
                return io.NodeOutput(result)

        prompt = {
            "plan": {"class_type": "YtonReplacementPlan", "inputs": {
                "config": json.dumps(config), "selected_index": 0, "loop_generation": True}},
            "segment": {"class_type": "YtonReplacementSegment", "inputs": {"plan": ["plan", 0]}},
            "generate": {"class_type": "YtonH3TraditionalOmniGenerate", "inputs": {
                "anchor_images": ["segment", 12], "video": ["segment", 1], "previous_video": ["segment", 10], "enable_context": ["segment", 11]}},
            "save": {"class_type": "YtonReplacementVideoSave", "inputs": {
                "video": ["generate", 0], "current": ["segment", 7], "total": ["segment", 8]}},
        }
        server = types.SimpleNamespace(client_id=None, last_node_id=None,
            send_sync=lambda *args: None, send_progress_text=lambda *args: None)
        mapping = {cls.__name__: cls for cls in CLASSES}
        mapping["YtonH3TraditionalOmniGenerate"] = MockOmni
        mapping["YtonReplacementVideoSave"] = MockSave
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, mapping), patch.object(PromptServer, "instance", server, create=True):
            valid, error, outputs, errors = asyncio.run(execution.validate_prompt("internal-context-loop", prompt, None))
            self.assertTrue(valid, (error, errors))
            executor = execution.PromptExecutor(server, cache_type=execution.CacheType.CLASSIC,
                cache_args={"ram": 0, "ram_inactive": 0})
            asyncio.run(executor.execute_async(prompt, uuid.uuid4().hex, execute_outputs=outputs))
            self.assertTrue(executor.success, executor.status_messages)
        self.assertEqual([[a["frame"] for a in anchors] for anchors in observed_anchors], [[0], [1], [2], [3]])
        self.assertEqual([float(a[0]["image"][0,0,0,0]) for a in observed_anchors], [1, 0, 1, 0])
        self.assertEqual([enabled for enabled, _ in observed], [False, True, True, True])
        self.assertIsNone(observed[0][1])
        self.assertIs(observed[1][1], saved[0])
        self.assertIs(observed[2][1], saved[1])
        self.assertIsNot(observed[1][1], generated[0])

    def test_retry_and_resume_restore_previous_segment_and_preserve_length(self):
        import execution
        import nodes
        from server import PromptServer

        config = self.config()
        config["plan"].update(frames=39, overlap=22, end=56 / 24)
        video, _ = segment_video(config, 0)
        observed = []

        class MockOmni(io.ComfyNode):
            @classmethod
            def define_schema(cls):
                return io.Schema(node_id="YtonH3TraditionalOmniGenerate",
                    inputs=[io.Video.Input("video"), io.Video.Input("previous_video", optional=True),
                            io.Boolean.Input("enable_context")], outputs=[io.Video.Output()])

            @classmethod
            def execute(cls, video, enable_context, previous_video=None):
                observed.append((enable_context, previous_video.get_frame_count() if previous_video else None))
                components = video.get_components()
                images = components.images[22:] if enable_context and previous_video else components.images
                return io.NodeOutput(InputImpl.VideoFromComponents(Types.VideoComponents(
                    images=images, frame_rate=components.frame_rate)))

        server = types.SimpleNamespace(client_id=None, last_node_id=None,
            send_sync=lambda *args: None, send_progress_text=lambda *args: None)
        mapping = {cls.__name__: cls for cls in CLASSES}
        mapping["YtonH3TraditionalOmniGenerate"] = MockOmni
        for loop, connected in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(loop=loop, connected=connected):
                prefix = "video/人物替换/%date:yyyy-MM-dd%/source/" if connected else f"restore-context/{loop}/"
                initial = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(), prefix=prefix)
                first = save_segment(video, 1, 2, **initial)
                if not loop:
                    save_segment(video, 2, 2, **initial)
                root = self.root / "output" / first["saved_segment"]["subfolder"]
                first_file = root / "segment_0001.mp4"
                before = first_file.stat().st_mtime_ns
                prompt = {
                    "plan": {"class_type": "YtonReplacementPlan", "inputs": {
                        "config": json.dumps(config), "selected_index": 1, "loop_generation": loop}},
                    "segment": {"class_type": "YtonReplacementSegment", "inputs": {"plan": ["plan", 0]}},
                    "generate": {"class_type": "YtonH3TraditionalOmniGenerate", "inputs": {
                        "video": ["segment", 1], "previous_video": ["segment", 10], "enable_context": ["segment", 11]}},
                    "save": {"class_type": "YtonReplacementVideoSave", "inputs": {
                        "video": ["generate", 0], "current": ["segment", 7], "total": ["segment", 8],
                        "filename_prefix": ["segment", 9] if connected else prefix, "container": "mp4", "fps": 24, "crf": 18,
                        "reuse_existing": True, "save_full": True}},
                }
                with patch.dict(nodes.NODE_CLASS_MAPPINGS, mapping), patch.object(PromptServer, "instance", server, create=True):
                    valid, error, outputs, errors = asyncio.run(execution.validate_prompt("restore-context", prompt, None))
                    self.assertTrue(valid, (error, errors))
                    executor = execution.PromptExecutor(server, cache_type=execution.CacheType.CLASSIC,
                        cache_args={"ram": 0, "ram_inactive": 0})
                    asyncio.run(executor.execute_async(prompt, uuid.uuid4().hex, execute_outputs=outputs))
                    self.assertTrue(executor.success, executor.status_messages)
                self.assertEqual(observed[-1], (True, 39))
                self.assertEqual(first_file.stat().st_mtime_ns, before)
                manifest = json.loads((root / "segments.json").read_text())
                self.assertEqual([manifest["segments"][str(i)]["frames"] for i in (1, 2)], [39, 17])
                self.assertEqual(InputImpl.VideoFromFile(str(root / "complete.mp4")).get_frame_count(), 56)

    def test_internal_loop_uses_plan_count_carries_video_and_finishes_saving(self):
        import execution
        import nodes
        from server import PromptServer

        config = self.config()
        config.update(auto=True, shared=True)
        config["plan"]["overlap"] = 0
        llm = FakeLLM()
        rendered = []
        test = self

        class Connector(io.ComfyNode):
            @classmethod
            def define_schema(cls):
                return io.Schema(node_id="ReplacementTestConnector", inputs=[],
                                 outputs=[io.Custom("YTON_LLM").Output()])

            @classmethod
            def execute(cls):
                return io.NodeOutput(llm)

        class Render(io.ComfyNode):
            @classmethod
            def define_schema(cls):
                return io.Schema(node_id="ReplacementTestRender",
                    inputs=[io.Video.Input("video"), io.Int.Input("index"),
                            io.Video.Input("previous", optional=True)], outputs=[io.Video.Output()])

            @classmethod
            def execute(cls, video, index, previous=None):
                index -= 1
                if index == 0:
                    test.assertIsNone(previous)
                else:
                    test.assertIs(previous, rendered[-1])
                    manifests = list((test.root/"output/video/人物替换").rglob("segments.json"))
                    test.assertEqual(len(manifests), 1)
                    test.assertEqual(len(json.loads(manifests[0].read_text())["segments"]), index)
                rendered.append(video)
                return io.NodeOutput(video)

        prompt = {
            "llm": {"class_type": "ReplacementTestConnector", "inputs": {}},
            "plan": {"class_type": "YtonReplacementPlan", "inputs": {"config": json.dumps(config), "selected_index": 0,
                "loop_generation": True, "llm": ["llm", 0]}},
            "segment": {"class_type": "YtonReplacementSegment", "inputs": {"plan": ["plan", 0]}},
            "render": {"class_type": "ReplacementTestRender", "inputs": {"video": ["segment", 1],
                        "index": ["segment", 7], "previous": ["segment", 10]}},
            "save": {"class_type": "YtonReplacementVideoSave", "inputs": {"video": ["render", 0],
                      "current": ["segment", 7], "total": ["segment", 8], "filename_prefix": ["segment", 9],
                      "container": "mp4", "fps": 24, "crf": 18, "reuse_existing": False, "save_full": True}},
        }
        mapping = {**{cls.__name__: cls for cls in CLASSES},
                   "ReplacementTestConnector": Connector, "ReplacementTestRender": Render}
        server = types.SimpleNamespace(client_id=None, last_node_id=None, send_sync=lambda *args: None,
                                       send_progress_text=lambda *args: None)
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, mapping), patch.object(PromptServer, "instance", server, create=True):
            valid, error, outputs, errors = asyncio.run(execution.validate_prompt("replacement-loop", prompt, None))
            self.assertTrue(valid, (error, errors))
            executor = execution.PromptExecutor(server, cache_type=execution.CacheType.CLASSIC,
                                                cache_args={"ram": 0, "ram_inactive": 0})
            asyncio.run(executor.execute_async(prompt, uuid.uuid4().hex, execute_outputs=outputs))
            self.assertTrue(executor.success, executor.status_messages)
        self.assertEqual(len(rendered), 2)
        self.assertEqual([video.get_frame_count() for video in rendered], [39, 33])
        self.assertEqual(len(llm.calls), 1)
        manifest = next((self.root/"output/video/人物替换").rglob("segments.json"))
        self.assertEqual(manifest.parent.parent, self.root / "output/video/人物替换" / date.today().isoformat() / "source")
        self.assertEqual(sorted(json.loads(manifest.read_text())["segments"]), ["1", "2"])
        self.assertTrue((manifest.parent/"complete.mp4").is_file())
        self.assertEqual(InputImpl.VideoFromFile(str(manifest.parent/"complete.mp4")).get_frame_count(), 72)

    def test_real_pgs_loop_executes_each_save_and_merges(self):
        import execution
        import nodes
        from replacement_test_plugin.replacement.nodes import YtonReplacementVideoSave
        spec=importlib.util.spec_from_file_location("replacement_pgs_loop",PLUGIN.parent/"ComfyUI-MiniMax-H3-Tool-PGS/nodes_for_loop_PGS.py")
        loops=importlib.util.module_from_spec(spec);spec.loader.exec_module(loops)
        classes={cls.__name__:cls for cls in CLASSES}
        for name in ("WhileLoopStartPGS","WhileLoopEndPGS","ComparePGS"):
            classes[name]=getattr(loops,name)
        config=self.config()
        prompt={
            "start":{"class_type":"WhileLoopStartPGS","inputs":{"condition":True,"initial_value0":0}},
            "config":{"class_type":"YtonCharacterReplacement","inputs":{"index":["start",1],"config":json.dumps(config),"selected_index":0}},
            "save":{"class_type":"YtonReplacementVideoSave","inputs":{"video":["config",1],"current":["config",7],"total":["config",8],
                    "filename_prefix":"native-loop/video","container":"mp4","fps":24,"crf":18,
                    "reuse_existing":False,"save_full":True}},
            "compare":{"class_type":"ComparePGS","inputs":{"a":["config",7],"b":["config",8],"comparison":"a < b"}},
            "end":{"class_type":"WhileLoopEndPGS","inputs":{"flow":["start",0],"condition":["compare",0],
                   "initial_value0":["config",7],"initial_value1":["save",0]}},
        }
        events=[]
        server=types.SimpleNamespace(client_id=None,last_node_id=None,send_sync=lambda *args:events.append(args))
        with patch.dict(nodes.NODE_CLASS_MAPPINGS,classes):
            executor=execution.PromptExecutor(server,cache_args={"ram":0,"ram_inactive":0})
            executor.execute(prompt,uuid.uuid4().hex,execute_outputs=["end","save"])
            self.assertTrue(executor.success, executor.status_messages)
        manifests=list((self.root/"output/native-loop").rglob("segments.json"))
        self.assertEqual(len(manifests),1)
        manifest=json.loads(manifests[0].read_text())
        self.assertEqual(sorted(manifest["segments"]),["1","2"])
        self.assertTrue((manifests[0].parent/"complete.mp4").exists())
        saved_outputs = [output for output in executor.history_result["outputs"].values()
                         if "replacement_saved" in output]
        self.assertEqual([item["filename"] for output in saved_outputs for item in output["images"]],
                         ["segment_0001.mp4", "segment_0002.mp4", "complete.mp4"])
        self.assertTrue(all(output["animated"] for output in saved_outputs))

    def test_save_node_reports_current_segment_and_persistent_complete_video(self):
        from comfy_execution.asset_enrichment import register_executed_outputs

        video, _ = segment_video(self.config(), 0)
        for save_full in (True, False):
            with self.subTest(save_full=save_full):
                node = type("ReplacementSaveTestNode", (YtonReplacementVideoSave,), {})
                node.hidden = io.HiddenHolder.from_dict({io.Hidden.unique_id: "save", io.Hidden.dynprompt: DynamicPrompt({})})
                options = dict(filename_prefix="reported/video", container="mp4", fps=24, crf=18, save_full=save_full)
                second = node.execute(video, 2, 2, **options)
                self.assertEqual([item["filename"] for item in second.ui["images"]], ["segment_0002.mp4"])
                first = node.execute(video, 1, 2, **options)
                names = [item["filename"] for item in first.ui["images"]]
                self.assertEqual(names, ["segment_0001.mp4", "complete.mp4"] if save_full else ["segment_0001.mp4"])
                self.assertTrue(all(item["type"] == "output" for item in first.ui["images"]))
                self.assertEqual(first.ui["animated"], (True,))
                self.assertTrue(first.ui["replacement_saved"][0]["complete"])
                for item in first.ui["images"]:
                    self.assertTrue((self.root / "output" / item["subfolder"] / item["filename"]).is_file())
                registered = []

                def register(path, job, preview_ref=None):
                    registered.append(Path(path).name)
                    return types.SimpleNamespace(id=uuid.uuid4().hex, preview_id=None)

                assets = register_executed_outputs(first.ui, "replacement-test",
                    types.SimpleNamespace(enabled=True, register_executed_output=register))
                self.assertEqual(registered, names)
                self.assertTrue(all(item["id"] for item in assets["images"]))

    def test_save_out_of_order_repeat_index_and_preview_only(self):
        video,_=segment_video(self.config(),0)
        run=uuid.uuid4().hex
        started_at=datetime(2026,11,3,14,0,30).astimezone()
        options=dict(run=run,started_at=started_at,prefix="replacement/test",save_full=False)
        second=save_segment(video,2,2,**options)
        self.assertFalse(second["complete"])
        first=save_segment(video,1,2,**options)
        self.assertTrue(first["complete"])
        self.assertEqual(first["merged"]["type"],"temp")
        repeat=save_segment(video,1,2,**options)
        self.assertEqual(len(repeat["segments"]),2)
        full=self.root/"temp"/repeat["merged"]["subfolder"]/repeat["merged"]["filename"]
        merged=InputImpl.VideoFromFile(str(full))
        self.assertEqual(merged.get_frame_count(),78)
        self.assertIsNotNone(merged.get_components().audio)
        self.assertEqual(len(list((self.root/"output/replacement/test_14-00-30").glob("segment_*.mp4"))),2)
        self.assertFalse((self.root/"output/replacement/test_14-00-30/complete.mp4").exists())
        new=save_segment(video,1,2,run=uuid.uuid4().hex,started_at=started_at,prefix="replacement/test")
        self.assertFalse(new["complete"])
        self.assertEqual(Path(new["saved_segment"]["subfolder"]).name,"test_14-00-30-2")

    def test_reuse_existing_project_overwrites_only_an_existing_segment(self):
        video, _ = segment_video(self.config(), 0)
        started_at = datetime(2026, 11, 3, 14, 0, 30).astimezone()
        initial = dict(run=uuid.uuid4().hex, started_at=started_at, prefix="replacement/retry",
                       save_full=True)
        original = save_segment(video, 1, 2, **initial)
        save_segment(video, 2, 2, **initial)
        project = self.root / "output" / original["saved_segment"]["subfolder"]
        first_file = project / "segment_0001.mp4"
        before = first_file.stat().st_mtime_ns

        retried = save_segment(video, 1, 2, run=uuid.uuid4().hex, started_at=started_at,
            prefix="replacement/retry", reuse_existing=True, save_full=True)
        self.assertEqual(Path(retried["saved_segment"]["subfolder"]), Path(original["saved_segment"]["subfolder"]))
        self.assertEqual(len(list((self.root / "output/replacement").glob("retry_14-00-30*/segments.json"))), 1)
        self.assertGreaterEqual(first_file.stat().st_mtime_ns, before)
        manifest = json.loads((project / "segments.json").read_text())
        self.assertEqual(manifest["run"], retried["run"])

    def test_reuse_without_project_creates_and_completes_a_new_project(self):
        video, _ = segment_video(self.config(), 0)
        for prefix in ("new-project/video", "new-project/directory/"):
            with self.subTest(prefix=prefix):
                options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(),
                    prefix=prefix, reuse_existing=True)
                first = save_segment(video, 1, 2, **options)
                second = save_segment(video, 2, 2, **options)
                self.assertEqual(first["_project_root"], second["_project_root"])
                project = Path(second["_project_root"])
                self.assertTrue((project / "segment_0001.mp4").is_file())
                self.assertTrue((project / "segment_0002.mp4").is_file())
                self.assertTrue(second["complete"])
                self.assertEqual(InputImpl.VideoFromFile(str(project / "complete.mp4")).get_frame_count(), 78)

    def test_reuse_with_changed_save_settings_preserves_other_segments_and_merges(self):
        started_at = datetime.now().astimezone()
        for name, changes in (
            ("format", {"container": "mkv"}),
            ("fps", {"fps": 12}),
            ("quality", {"crf": 28}),
            ("size", {"size": (96, 64)}),
            ("combined", {"container": "mkv", "fps": 12, "crf": 28, "size": (96, 64)}),
        ):
            with self.subTest(settings=name):
                prefix = f"changed-settings/{name}/"
                initial = dict(run=uuid.uuid4().hex, started_at=started_at, prefix=prefix)
                for index, color in ((1, .5), (2, 1.)):
                    video = InputImpl.VideoFromComponents(Types.VideoComponents(
                        images=torch.full((12, 48, 64, 3), color), frame_rate=Fraction(24)))
                    original = save_segment(video, index, 2, **initial)
                project = Path(original["_project_root"])
                other = project / "segment_0002.mp4"
                before = other.read_bytes()
                options = {"container": "mp4", "fps": 24, "crf": 18, **changes}
                width, height = options.pop("size", (64, 48))
                replacement = InputImpl.VideoFromComponents(Types.VideoComponents(
                    images=torch.zeros((12, height, width, 3)), frame_rate=Fraction(24)))
                result = save_segment(replacement, 1, 2, run=uuid.uuid4().hex,
                    started_at=started_at, prefix=prefix, reuse_existing=True, **options)
                self.assertEqual(result["_project_root"], str(project))
                self.assertTrue(result["complete"])
                self.assertEqual(other.read_bytes(), before)
                manifest = json.loads((project / "segments.json").read_text())
                self.assertEqual((manifest["format"], manifest["fps"], manifest["crf"], manifest["size"]),
                    (options["container"], options["fps"], options["crf"], [width, height]))
                self.assertEqual(manifest["segments"]["1"]["frames"], options["fps"] // 2)
                self.assertEqual(manifest["segments"]["2"], {"file": other.name, "frames": 12})
                self.assertEqual(sorted(path.name for path in project.glob("segment_*")),
                    sorted([f"segment_0001.{options['container']}", "segment_0002.mp4"]))
                merged = InputImpl.VideoFromFile(str(project / "complete.mp4")).get_components()
                self.assertEqual(tuple(merged.images.shape), (options["fps"], height, width, 3))
                self.assertEqual(merged.frame_rate, Fraction(options["fps"]))
                self.assertLess(float(merged.images[0].mean()), .05)
                self.assertGreater(float(merged.images[-1, height // 2, width // 2].mean()), .95)
                if "size" in changes:
                    self.assertLess(float(merged.images[-1, :, 0].mean()), .05)
                self.assertIsNotNone(merged.audio)
                self.assertAlmostEqual(merged.audio["waveform"].shape[-1] / merged.audio["sample_rate"], 1, delta=.04)
                with av.open(str(project / "complete.mp4")) as opened:
                    self.assertAlmostEqual(opened.duration / av.time_base, 1, delta=.03)
                self.assertFalse(list(project.glob("merge_*")))
                self.assertFalse(list(project.glob("*.writing.*")))
                self.assertFalse((project / "concat.txt").exists())

    def test_changed_settings_follow_the_execution_project_and_preview_only_mode(self):
        video, _ = segment_video(self.config(), 0)
        options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(),
            prefix="changed-settings/execution/", save_full=False)
        first = save_segment(video, 1, 2, **options)
        project = Path(first["_project_root"])
        before = (project / "segment_0001.mp4").read_bytes()
        second = save_segment(video, 2, 2, project_root=project, fps=12, **options)
        self.assertEqual(second["_project_root"], str(project))
        self.assertEqual((project / "segment_0001.mp4").read_bytes(), before)
        self.assertEqual(second["merged"]["type"], "temp")
        merged = self.root / "temp" / second["merged"]["subfolder"] / second["merged"]["filename"]
        self.assertEqual(InputImpl.VideoFromFile(str(merged)).get_frame_count(), 40)
        self.assertFalse((project / "complete.mp4").exists())

    def test_failed_replacement_keeps_the_saved_segment_and_manifest(self):
        video, _ = segment_video(self.config(), 0)
        options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(),
            prefix="changed-settings/failed/")
        first = save_segment(video, 1, 2, **options)
        project = Path(first["_project_root"])
        manifest = (project / "segments.json").read_bytes()
        saved = (project / "segment_0001.mp4").read_bytes()
        with patch("replacement_test_plugin.replacement.save.encode", side_effect=ValueError("encode failed")):
            with self.assertRaisesRegex(ValueError, "encode failed"):
                save_segment(video, 1, 2, run=uuid.uuid4().hex, started_at=options["started_at"],
                    prefix=options["prefix"], reuse_existing=True, container="mkv", fps=12, crf=28)
        self.assertEqual((project / "segments.json").read_bytes(), manifest)
        self.assertEqual((project / "segment_0001.mp4").read_bytes(), saved)
        self.assertFalse((project / "segment_0001.mkv").exists())

    def test_reuse_without_requested_segment_adds_it_to_the_existing_project(self):
        video, _ = segment_video(self.config(), 0)
        started_at = datetime.now().astimezone()
        prefix = "missing-segment/project/"
        original = save_segment(video, 2, 2, run=uuid.uuid4().hex, started_at=started_at, prefix=prefix)
        original_manifest = Path(original["_project_root"]) / "segments.json"
        second_file = Path(original["_project_root"]) / "segment_0002.mp4"
        before = second_file.read_bytes()
        created = save_segment(video, 1, 2, run=uuid.uuid4().hex, started_at=started_at,
            prefix=prefix, reuse_existing=True)
        self.assertEqual(created["_project_root"], original["_project_root"])
        self.assertEqual(second_file.read_bytes(), before)
        self.assertEqual(sorted(json.loads(original_manifest.read_text())["segments"]), ["1", "2"])
        self.assertTrue(created["complete"])
        self.assertTrue((Path(created["_project_root"]) / "segment_0001.mp4").is_file())

    def test_invalid_encoded_replacement_keeps_the_saved_segment_and_manifest(self):
        video, _ = segment_video(self.config(), 0)
        options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(),
                       prefix="save-priority/invalid-encode/")
        first = save_segment(video, 1, 2, **options)
        project = Path(first["_project_root"])
        saved = (project / "segment_0001.mp4").read_bytes()
        manifest = (project / "segments.json").read_bytes()
        with patch("replacement_test_plugin.replacement.save.encode",
                   side_effect=lambda arguments: Path(arguments[-1]).write_bytes(b"invalid video")):
            with self.assertRaises(av.FFmpegError):
                save_segment(video, 1, 2, **options, reuse_existing=True)
        self.assertEqual((project / "segment_0001.mp4").read_bytes(), saved)
        self.assertEqual((project / "segments.json").read_bytes(), manifest)
        self.assertFalse(list(project.glob("*.writing.*")))

    def test_cleanup_failure_does_not_block_the_saved_replacement(self):
        video, _ = segment_video(self.config(), 0)
        options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(),
                       prefix="save-priority/cleanup/")
        first = save_segment(video, 1, 2, **options)
        project = Path(first["_project_root"])
        locked = {project / "segment_0001.mkv", project / "complete.mp4"}
        for path in locked:
            path.write_bytes(b"old output")
        real_unlink = Path.unlink

        def fail_locked_cleanup(path, *args, **kwargs):
            if path in locked:
                raise PermissionError("file in use")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_locked_cleanup):
            with self.assertLogs(level="WARNING"):
                result = save_segment(video, 1, 2, **options, reuse_existing=True)
        self.assertIsNone(result["merged"])
        self.assertEqual(InputImpl.VideoFromFile(str(project / result["saved_segment"]["filename"])).get_frame_count(), 39)
        self.assertEqual(json.loads((project / "segments.json").read_text())["segments"]["1"]["file"],
                         "segment_0001.mp4")

    def test_reuse_with_changed_segment_count_replaces_the_same_sequence_number(self):
        video, _ = segment_video(self.config(), 0)
        options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(),
                       prefix="save-priority/count/")
        first = save_segment(video, 1, 2, **options)
        project = Path(first["_project_root"])
        (project / "segment_0001.mkv").write_bytes(b"obsolete same-sequence file")
        result = save_segment(video, 1, 3, **{**options, "run": uuid.uuid4().hex}, reuse_existing=True)
        self.assertEqual(result["_project_root"], str(project))
        self.assertEqual(result["total"], 3)
        self.assertFalse(result["complete"])
        self.assertFalse((project / "segment_0001.mkv").exists())
        self.assertEqual(InputImpl.VideoFromFile(str(project / "segment_0001.mp4")).get_frame_count(), 39)

    def test_missing_old_segment_does_not_block_the_new_save_or_show_a_stale_merge(self):
        video, _ = segment_video(self.config(), 0)
        options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(),
                       prefix="save-priority/missing/")
        for index in (1, 2):
            first = save_segment(video, index, 2, **options)
        project = Path(first["_project_root"])
        self.assertTrue((project / "complete.mp4").exists())
        (project / "segment_0002.mp4").unlink()
        result = save_segment(video, 1, 2, **{**options, "run": uuid.uuid4().hex}, reuse_existing=True)
        self.assertTrue((project / result["saved_segment"]["filename"]).is_file())
        self.assertFalse(result["complete"])
        self.assertIsNone(result["merged"])
        self.assertEqual(len(result["segments"]), 1)
        self.assertFalse((project / "complete.mp4").exists())

    def test_missing_or_invalid_manifest_is_rebuilt_from_existing_segments(self):
        video, _ = segment_video(self.config(), 0)
        for invalid in (None, "{broken json", "[]"):
            for explicit_root in (False, True):
                with self.subTest(manifest=invalid, explicit_root=explicit_root):
                    options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(),
                                   prefix=f"save-priority/rebuild-{uuid.uuid4().hex}/")
                    first = save_segment(video, 1, 2, **options)
                    project = Path(first["_project_root"])
                    previous = (project / "segment_0001.mp4").read_bytes()
                    manifest = project / "segments.json"
                    if invalid is None:
                        manifest.unlink()
                    else:
                        manifest.write_text(invalid, encoding="utf-8")
                    result = save_segment(video, 2, 2, **options, reuse_existing=True,
                                          project_root=project if explicit_root else None)
                    self.assertEqual(result["_project_root"], str(project))
                    self.assertEqual((project / "segment_0001.mp4").read_bytes(), previous)
                    self.assertTrue(result["complete"])
                    self.assertEqual(InputImpl.VideoFromFile(str(project / "complete.mp4")).get_frame_count(), 78)

    def test_merge_failure_still_returns_the_saved_replacement(self):
        video, _ = segment_video(self.config(), 0)
        options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(),
                       prefix="save-priority/merge-failure/")
        for index in (1, 2):
            first = save_segment(video, index, 2, **options)
        project = Path(first["_project_root"])
        replacement = InputImpl.VideoFromComponents(Types.VideoComponents(
            images=torch.zeros((12, 48, 64, 3)), frame_rate=Fraction(24)))
        real_encode = encode

        def fail_merge(arguments):
            if "concat" in arguments:
                raise ValueError("merge failed")
            return real_encode(arguments)

        with patch("replacement_test_plugin.replacement.save.encode", side_effect=fail_merge):
            with self.assertLogs(level="WARNING") as captured:
                result = save_segment(replacement, 1, 2, **{**options, "run": uuid.uuid4().hex},
                                      reuse_existing=True)
        self.assertTrue(result["complete"])
        self.assertIsNone(result["merged"])
        saved = project / result["saved_segment"]["filename"]
        self.assertEqual(InputImpl.VideoFromFile(str(saved)).get_frame_count(), 12)
        self.assertLess(float(InputImpl.VideoFromFile(str(saved)).get_components().images.mean()), .05)
        self.assertIn("已保存", captured.output[0])
        self.assertEqual(json.loads((project / "segments.json").read_text())["segments"]["1"]["frames"], 12)
        self.assertFalse((project / "complete.mp4").exists())
        self.assertFalse(list(project.glob("merge_*")))
        self.assertFalse(list(project.glob("*.writing.*")))

    def test_reuse_directory_prefix_finds_the_same_project_at_a_different_time(self):
        video, _ = segment_video(self.config(), 0)
        first = save_segment(video, 1, 1, run=uuid.uuid4().hex,
            started_at=datetime(2026, 11, 3, 14, 0, 30).astimezone(), prefix="retry-directory/project/")
        retried = save_segment(video, 1, 1, run=uuid.uuid4().hex,
            started_at=datetime(2026, 11, 3, 15, 0, 30).astimezone(), prefix="retry-directory/project/",
            reuse_existing=True)
        self.assertEqual(retried["saved_segment"], first["saved_segment"])
        self.assertEqual(retried["merged"], first["merged"])

    def test_save_directory_uses_configuration_start_time_for_all_segments(self):
        config = self.config()
        dynprompt = DynamicPrompt({})
        planner = type("TimedReplacementPlan", (YtonReplacementPlan,), {})
        saver = type("TimedReplacementSave", (YtonReplacementVideoSave,), {})
        for node, uid in ((planner, "plan"), (saver, "save")):
            node.hidden = io.HiddenHolder.from_dict({io.Hidden.unique_id: uid, io.Hidden.dynprompt: dynprompt})
        started_at = datetime(2026, 11, 3, 14, 0, 30).astimezone()
        with patch("replacement_test_plugin.replacement.save.datetime") as clock:
            clock.now.return_value = started_at
            planner.execute(json.dumps(config))
            clock.now.return_value = datetime(2026, 11, 3, 14, 36, 0).astimezone()
            options = dict(filename_prefix="timestamp/project/", container="mp4", fps=24, crf=18, save_full=True)
            for index in (1, 2):
                video, _ = segment_video(config, index - 1)
                result = saver.execute(video, index, 2, **options).ui["replacement_saved"][0]
                self.assertEqual(result["saved_segment"]["subfolder"], "timestamp/project/14-00-30")
        manifest = json.loads((self.root / "output/timestamp/project/14-00-30/segments.json").read_text())
        self.assertEqual(manifest["started_at"], started_at.isoformat())
        self.assertEqual(result["merged"]["subfolder"], "timestamp/project/14-00-30")
        other_run = uuid.uuid4().hex
        for index in (1, 2):
            result = save_segment(video, index, 2, run=other_run, started_at=started_at, prefix="timestamp/project/")
            self.assertEqual(result["saved_segment"]["subfolder"], "timestamp/project/14-00-30-2")

    def test_save_normalizes_silent_audio_and_preserves_order(self):
        run=uuid.uuid4().hex
        options=dict(run=run,started_at=datetime.now().astimezone(),prefix="replacement/colors",container="mkv",save_full=True)
        for index,color in enumerate((0.,1.),1):
            frames=torch.full((12,48,64,3),color)
            video=InputImpl.VideoFromComponents(Types.VideoComponents(images=frames,frame_rate=Fraction(24)))
            result=save_segment(video,index,2,**options)
        merged=self.root/"output"/result["merged"]["subfolder"]/result["merged"]["filename"]
        components=InputImpl.VideoFromFile(str(merged)).get_components()
        self.assertEqual(components.images.shape[0],24)
        self.assertLess(float(components.images[0].mean()),.05)
        self.assertGreater(float(components.images[-1].mean()),.95)
        self.assertIsNotNone(components.audio)

    def test_save_preserves_h3_segment_frames_and_final_frame(self):
        executables = {ffmpeg()}
        if importlib.util.find_spec("imageio_ffmpeg") is not None:
            executables.add(importlib.import_module("imageio_ffmpeg").get_ffmpeg_exe())
        for executable in executables:
            for container in ("mp4", "mkv"):
                for with_audio in (False, True):
                    with self.subTest(ffmpeg=executable, container=container, audio=with_audio):
                        options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(), prefix="replacement/frame-count", container=container)
                        for index, count in enumerate((124, 79), 1):
                            frames = torch.zeros((count, 32, 48, 3))
                            frames[-1] = 1
                            audio = ({"waveform": torch.zeros((1, 2, round(count * 32000 / 24))),
                                      "sample_rate": 32000} if with_audio else None)
                            video = InputImpl.VideoFromComponents(Types.VideoComponents(
                                images=frames, audio=audio, frame_rate=Fraction(24)))
                            with patch("replacement_test_plugin.replacement.media.ffmpeg", return_value=executable):
                                result = save_segment(video, index, 2, **options)
                            saved = self.root / "output" / result["saved_segment"]["subfolder"] / result["saved_segment"]["filename"]
                            with av.open(str(saved)) as opened:
                                self.assertAlmostEqual(opened.duration / av.time_base, count / 24, delta=.03)
                            images = InputImpl.VideoFromFile(str(saved)).get_components().images
                            self.assertEqual(len(images), count)
                            self.assertGreater(float(images[-1].mean()), .95)
                        merged = self.root / "output" / result["merged"]["subfolder"] / result["merged"]["filename"]
                        images = InputImpl.VideoFromFile(str(merged)).get_components().images
                        self.assertEqual(len(images), 203)
                        self.assertGreater(float(images[123].mean()), .95)
                        self.assertLess(float(images[124].mean()), .05)
                        self.assertGreater(float(images[-1].mean()), .95)

    def test_save_trims_long_audio_to_video_duration(self):
        frames = torch.zeros((124, 32, 48, 3))
        frames[-1] = 1
        for audio_seconds in (1, 10):
            for container in ("mp4", "mkv"):
                with self.subTest(audio_seconds=audio_seconds, container=container):
                    video = InputImpl.VideoFromComponents(Types.VideoComponents(images=frames, frame_rate=Fraction(24),
                        audio={"waveform": torch.zeros((1, 2, 32000 * audio_seconds)), "sample_rate": 32000}))
                    options = dict(run=uuid.uuid4().hex, started_at=datetime.now().astimezone(),
                                   prefix="replacement/audio-duration", container=container)
                    result = save_segment(video, 1, 1, **options)
                    for record in (result["saved_segment"], result["merged"]):
                        saved = self.root / "output" / record["subfolder"] / record["filename"]
                        with av.open(str(saved)) as opened:
                            self.assertAlmostEqual(opened.duration / av.time_base, 124 / 24, delta=.03)
                            self.assertTrue(opened.streams.audio)
                        restored = InputImpl.VideoFromFile(str(saved)).get_components()
                        self.assertEqual(len(restored.images), 124)
                        self.assertGreater(float(restored.images[-1].mean()), .95)
                        self.assertAlmostEqual(restored.audio["waveform"].shape[-1] / restored.audio["sample_rate"], 124 / 24, delta=.04)

    def test_llm_request_includes_task_owned_images(self):
        with patch("replacement_test_plugin.llm_connection.get_store") as store, patch("replacement_test_plugin.llm_connection.resolve_model",return_value=({},"vision")), patch("replacement_test_plugin.llm_connection.request_json",return_value={"choices":[{"message":{"content":"done"}}]}) as request:
            connection=LLMConnection()
            self.assertEqual(connection.generate("user",system="task",images=[Image.new("RGB",(8,8))]),"done")
            payload=request.call_args.args[2]
            self.assertEqual(payload["messages"][0]["content"],"task")
            self.assertTrue(payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
            with self.assertRaisesRegex(ValueError,"不支持"):
                connection.generate("user",parameters={"messages":[]})

    def test_file_boundaries(self):
        config=self.config();config["video"]=str(Path(__file__).resolve())
        with self.assertRaises(ValueError):
            segment_video(config,0)
        video,_=segment_video(self.config(),0)
        with self.assertRaises(Exception):
            save_segment(video,1,1,run=uuid.uuid4().hex,started_at=datetime.now().astimezone(),prefix="../../escape")


if __name__=="__main__":
    unittest.main(argv=[sys.argv[0]])
