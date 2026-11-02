"""CPU integration tests: real files, audio, segment boundaries and loop state."""

from copy import deepcopy
import asyncio
from dataclasses import dataclass, field
from fractions import Fraction
from datetime import date
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid

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
from replacement_test_plugin.replacement.media import contact_sheet, encode, inspect, reference_images, segment_video
from replacement_test_plugin.replacement.nodes import CLASSES, DEFAULT_CONFIG, YtonCharacterReplacement, YtonReplacementPlan, YtonReplacementVideoSave
from replacement_test_plugin.replacement.plan import make_plan
from replacement_test_plugin.replacement.prompts import SYSTEM, load_skill, optimize, save_skill, signature
from replacement_test_plugin.replacement.save import execution_state, save_segment
from PIL import Image


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

    def test_output_contract_and_alias_identity(self):
        config=self.config()
        config["original"]="将 @视频 的人物替换成 @图片3。"
        output=self.node().execute(0,json.dumps(config))
        self.assertEqual(len(output.result),10)
        self.assertIn("<Picture 2>",output.result[2])
        self.assertEqual([tuple(i.shape) for i in output.result[0]],[(1,120,60,3),(1,45,120,3)])
        self.assertEqual(len(output.result[1]),1)
        self.assertEqual(output.result[7:9],(1,2))
        self.assertEqual(output.result[3:7],(160,96,39,39/24))
        self.assertEqual(output.result[9], "video/人物替换/%date:yyyy-MM-dd%/source/")
        config["images"]=[""]*6
        self.assertEqual(self.node().execute(0,json.dumps(config)).result[0],[])

    def test_dimensions_and_length_follow_prepared_segment(self):
        config=self.config()
        tail=self.node().execute(1,json.dumps(config))
        self.assertEqual(tail.result[3:7],(160,96,38,38/24))
        config["crop"]=[.1,0,.8,1]
        config["plan"].update(enabled=False,seconds=1.25)
        config["compression"].update(width=96,height=64,fps=12)
        output=self.node().execute(0,json.dumps(config))
        self.assertEqual(output.result[3:7],(96,64,15,1.25))
        video=output.result[1][0].get_components()
        self.assertEqual(output.result[3:6],(video.images.shape[2],video.images.shape[1],video.images.shape[0]))

    def test_project_directory_uses_source_video_name_for_every_segment(self):
        source = self.root / "input/引用视频/舞蹈参考.v1.mp4"
        source.parent.mkdir(exist_ok=True)
        source.write_bytes((self.root / "input/source.mp4").read_bytes())
        config = self.config()
        config["video"] = "引用视频/舞蹈参考.v1.mp4 [input]"
        node = self.node()
        for index in (0, 1):
            self.assertEqual(node.execute(index, json.dumps(config)).result[9],
                             "video/人物替换/%date:yyyy-MM-dd%/舞蹈参考.v1/")

    def test_auto_shared_once_per_run_and_per_segment(self):
        config=self.config(); config.update(auto=True,shared=True)
        llm=FakeLLM(); node=self.node()
        node.execute(0,json.dumps(config),llm); node.execute(1,json.dumps(config),llm)
        self.assertEqual(len(llm.calls),1)
        self.assertEqual(len(llm.calls[0][1]["images"]),3)
        self.node().execute(0,json.dumps(config),llm)
        self.assertEqual(len(llm.calls),2)
        config["shared"]=False
        node=self.node(); node.execute(0,json.dumps(config),llm);node.execute(1,json.dumps(config),llm)
        self.assertEqual(len(llm.calls),4)
        with self.assertRaisesRegex(ValueError,"连接"):
            node.execute(0,json.dumps(config))

    def test_manual_result_invalidated_by_media_changes(self):
        config=self.config();config["optimized"]["0"]={"text":"manual optimized", "signature":signature(config,0)}
        self.assertEqual(self.node().execute(0,json.dumps(config)).result[2],"manual optimized")
        config["image_scale"]=.75
        self.assertNotEqual(self.node().execute(0,json.dumps(config)).result[2],"manual optimized")

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
        self.node().execute(0, json.dumps(config), llm)
        self.assertEqual(len(llm.calls), 2)
        self.assertTrue(all(call[1]["system"] == custom for call in llm.calls))
        save_skill(SYSTEM)
        self.assertEqual(load_skill(), SYSTEM)

    def test_skill_changes_invalidate_optimized_results_and_reject_blank_saves(self):
        path = self.root / "user/yton-replacement-skill.md"
        self.addCleanup(path.unlink, missing_ok=True)
        config = self.config()
        config["optimized"]["0"] = {"text": "old optimized", "signature": signature(config, 0)}
        self.assertEqual(self.node().execute(0, json.dumps(config)).result[2], "old optimized")
        save_skill("只根据当前角色参考与用户要求编写提示词。")
        self.assertNotEqual(self.node().execute(0, json.dumps(config)).result[2], "old optimized")
        for value in ("", " \n ", None):
            with self.assertRaisesRegex(ValueError, "不能为空"):
                save_skill(value)
        self.assertEqual(load_skill(), "只根据当前角色参考与用户要求编写提示词。")

    def test_native_loop_expansions_share_correct_owner(self):
        dyn=DynamicPrompt({})
        dyn.add_ephemeral_node("loop.1.config",{},"loop.end","config")
        dyn.add_ephemeral_node("loop.2.config",{},"loop.1.end","config")
        dyn.add_ephemeral_node("loop.1.save",{},"loop.end","save")
        a=execution_state(dyn,"loop.1.config")
        self.assertIs(a,execution_state(dyn,"loop.2.config"))
        self.assertIsNot(a,execution_state(dyn,"loop.1.save"))
        self.assertIsNot(a,execution_state(DynamicPrompt({}),"config"))

    def test_loop_plan_does_not_prepare_media_or_optimize(self):
        config = self.config()
        config.update(auto=True, shared=True)
        llm = FakeLLM()
        with patch("replacement_test_plugin.replacement.nodes.segment_video") as prepare:
            plan = YtonReplacementPlan.execute(json.dumps(config), llm)
        prepare.assert_not_called()
        self.assertEqual(llm.calls, [])
        self.assertEqual(plan.result[1], 2)
        self.assertIs(plan.result[0]["llm"], llm)
        config["plan"]["frames"] = 22
        self.assertEqual(YtonReplacementPlan.execute(json.dumps(config)).result[1], 4)

    def test_official_loop_uses_plan_count_carries_video_and_finishes_saving(self):
        import execution
        import nodes
        from comfy_extras import nodes_loop
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
            "plan": {"class_type": "YtonReplacementPlan", "inputs": {"config": json.dumps(config), "llm": ["llm", 0]}},
            "start": {"class_type": "StartLoop", "inputs": {"mode": "For", "mode.start_iteration_index": 0,
                       "mode.max_iteration": ["plan", 1], "mode.step": 1, "cache_iterations": False}},
            "segment": {"class_type": "YtonReplacementSegment", "inputs": {"index": ["start", 0], "plan": ["plan", 0]}},
            "render": {"class_type": "ReplacementTestRender", "inputs": {"video": ["segment", 1],
                        "index": ["start", 0], "previous": ["start", 4]}},
            "save": {"class_type": "YtonReplacementVideoSave", "inputs": {"video": ["render", 0],
                      "current": ["segment", 7], "total": ["plan", 1], "filename_prefix": ["segment", 9],
                      "container": "mp4", "fps": 24, "crf": 18, "save_full": True}},
            "end": {"class_type": "EndLoop", "inputs": {"output_value": ["save", 0],
                     "next_iteration_value": ["save", 0], "accumulate": False}},
        }
        mapping = {**{cls.__name__: cls for cls in CLASSES}, **nodes_loop.NODE_CLASS_MAPPINGS,
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
            "config":{"class_type":"YtonCharacterReplacement","inputs":{"index":["start",1],"config":json.dumps(config)}},
            "save":{"class_type":"YtonReplacementVideoSave","inputs":{"video":["config",1],"current":["config",7],"total":["config",8],
                    "filename_prefix":"native-loop/video","container":"mp4","fps":24,"crf":18,"save_full":True}},
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
        options=dict(run=run,prefix="replacement/test",save_full=False)
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
        self.assertEqual(len(list((self.root/"output/replacement"/f"test_{run}").glob("segment_*.mp4"))),2)
        self.assertFalse((self.root/"output/replacement"/f"test_{run}"/"complete.mp4").exists())
        new=save_segment(video,1,2,run=uuid.uuid4().hex,prefix="replacement/test")
        self.assertFalse(new["complete"])

    def test_save_normalizes_silent_audio_and_preserves_order(self):
        run=uuid.uuid4().hex
        options=dict(run=run,prefix="replacement/colors",container="mkv",save_full=True)
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
            save_segment(video,1,1,run=uuid.uuid4().hex,prefix="../../escape")


if __name__=="__main__":
    unittest.main(argv=[sys.argv[0]])
