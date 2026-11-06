"""CPU checks for real VIDEO padding, source-time overlap and pin ordering."""

from copy import deepcopy
from fractions import Fraction
import json
import unittest
from unittest.mock import patch
import types
import asyncio
import uuid

import test_character_replacement as fixture
from replacement_test_plugin.nodes.h3_video_length_node import YtonH3VideoLength, adjust
from replacement_test_plugin.viggle.media import DEFAULT_CONFIG, parse_config, plan_for, previous_frame, references, segment, segment_metadata
from replacement_test_plugin.viggle.nodes import CLASSES, YtonViggleReplacementSegment
from replacement_test_plugin.viggle.prompts import optimize, signature

torch, io, InputImpl, Types = fixture.torch, fixture.io, fixture.InputImpl, fixture.Types


class ViggleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ReplacementTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.ReplacementTests.tearDownClass()

    def config(self):
        config = deepcopy(DEFAULT_CONFIG)
        config.update(video="source.mp4", images=["red.png", "", "blue.png", ""], resolution="320p")
        config["plan"].update(seconds=1.5)
        return config

    def video(self, count, rate=24):
        images = torch.arange(count).float().view(-1, 1, 1, 1).expand(-1, 4, 4, 3)
        audio = {"waveform": torch.arange(round(count / float(rate) * 48000)).float().view(1, 1, -1), "sample_rate":48000}
        return InputImpl.VideoFromComponents(Types.VideoComponents(images=images, frame_rate=Fraction(rate), audio=audio))

    def test_editor_context_drives_plan_and_length_restore(self):
        for overlap in (0, 6, 12, 22):
            with self.subTest(overlap=overlap):
                config = self.config()
                config["plan"]["overlap"] = overlap
                config = parse_config(config)
                source, _ = segment(config, 1)
                info, _, _ = segment_metadata(config, 1)
                self.assertEqual(info["overlap_frames"], overlap)
                self.assertEqual(info["context_frames"], overlap)
                padded = adjust(source)
                restored = adjust(padded[0], "复原", padded[4], info["overlap_frames"], False)
                self.assertEqual(restored[3], source.get_frame_count() - overlap)
                self.assertTrue(torch.equal(restored[1], source.get_components().images[overlap:]))

    def test_reference_and_pin_order(self):
        config=self.config()
        images,pins=references(config,0)
        self.assertEqual(pins,"")
        self.assertEqual(images[0].getpixel((0,0)),(255,0,0))
        config["mode"]="keyframe"
        config["keyframes"]={"0":[{"frame":20,"image":"blue.png"},{"frame":0,"image":"red.png"},{"frame":30,"image":""}]}
        images,pins=references(config,0)
        self.assertEqual(pins,"0, 20")
        self.assertEqual(images[0].getpixel((0,0)),(255,0,0))
        self.assertEqual(images[1].getpixel((0,0)),(0,0,255))
        config["keyframes"]["0"].append({"frame":20,"image":"red.png"})
        with self.assertRaisesRegex(ValueError,"不同"):
            references(config,0)

    def test_actual_segment_and_dimensions(self):
        config=self.config()
        video,plan=segment(config,1)
        info,_,_=segment_metadata(config,1)
        self.assertEqual(video.get_frame_count(),info["source_frames"])
        self.assertEqual(video.get_frame_rate(),24)
        self.assertEqual(info["overlap_frames"],5)
        self.assertEqual(min(video.get_dimensions()),320)
        config["plan"]["enabled"]=False
        video,plan=segment(config,0)
        self.assertEqual(len(plan["segments"]),1)
        self.assertEqual(video.get_frame_count(),72)

    def test_real_executor_loop_restores_and_merges_once(self):
        import execution
        import nodes
        from server import PromptServer

        config=self.config()
        config["plan"]["overlap"] = 6
        prompt={
            "plan":{"class_type":"YtonViggleReplacementPlan","inputs":{"config":json.dumps(config),"selected_index":0,"loop_generation":True}},
            "parse":{"class_type":"YtonViggleReplacementSegment","inputs":{"plan":["plan",0]}},
            "pad":{"class_type":"YtonH3VideoLength","inputs":{"video":["parse",0],"mode":"延长","original_frames":0,"context_frames":0,"first_segment":True}},
            # The padded video stands in for a generated result, preserving the
            # true source frames so duplicate removal can be verified exactly.
            "restore":{"class_type":"YtonH3VideoLength","inputs":{"video":["pad",0],"mode":"复原","original_frames":["pad",4],"context_frames":["parse",12],"first_segment":["parse",13]}},
            "save":{"class_type":"YtonReplacementVideoSave","inputs":{"video":["restore",0],"current":["parse",8],"total":["parse",10],
                    "filename_prefix":["parse",9],"container":"mp4","fps":24,"crf":18,"reuse_existing":False,"save_full":True}},
        }
        mapping={cls.__name__:cls for cls in [*fixture.CLASSES,*CLASSES,YtonH3VideoLength]}
        events=[]
        server=types.SimpleNamespace(client_id=None,last_node_id=None,send_sync=lambda *args:events.append(args),send_progress_text=lambda *args:None)
        with patch.dict(nodes.NODE_CLASS_MAPPINGS,mapping),patch.object(PromptServer,"instance",server,create=True):
            valid,error,outputs,errors=asyncio.run(execution.validate_prompt("viggle-loop",prompt,None))
            self.assertTrue(valid,(error,errors))
            executor=execution.PromptExecutor(server,cache_type=execution.CacheType.CLASSIC,cache_args={"ram":0,"ram_inactive":0})
            executor.execute(prompt,uuid.uuid4().hex,execute_outputs=outputs)
            self.assertTrue(executor.success,executor.status_messages)
        manifests=list((fixture.ReplacementTests.root/"output/video/Viggle").rglob("segments.json"))
        self.assertEqual(len(manifests),1)
        manifest=json.loads(manifests[0].read_text())
        self.assertEqual([manifest["segments"][str(i)]["frames"] for i in (1,2,3)],[36,30,6])
        self.assertEqual(InputImpl.VideoFromFile(str(manifests[0].parent/"complete.mp4")).get_frame_count(),72)

    def test_overlap_ignores_padding_and_handles_restored_previous(self):
        config=self.config()
        # 36 source frames, then 31..67. Frame zero belongs to prior frame 31,
        # even when H3 padded that prior video all the way to 56 frames.
        self.assertEqual(previous_frame(config,1,0,self.video(56))[1],31)
        # Third segment starts at 62. Prior result may already have had its
        # first five duplicate frames removed: (62 - 31) - 5 = 26.
        self.assertEqual(previous_frame(config,2,0,self.video(31))[1],26)
        with self.assertRaisesRegex(ValueError,"重叠"):
            previous_frame(config,1,5,self.video(56))

    def test_optimizer_sees_pins_and_the_same_images(self):
        config=self.config();config["mode"]="keyframe"
        config["keyframes"]={"0":[{"frame":20,"image":"blue.png"},{"frame":0,"image":"red.png"}]}
        video,_=segment(config,0);images,pins=references(config,0);llm=fixture.FakeLLM()
        optimize(llm,config,0,video,images,pins)
        user,options=llm.calls[0]
        self.assertIn("<Picture 1> 对应零基帧索引 0",user)
        self.assertIn("20",user)
        self.assertEqual(len(options["images"]),3)
        before=signature(config,0);config["keyframes"]["0"][0]["frame"]=21
        self.assertNotEqual(signature(config,0),before)

    def test_parser_and_registered_schemas(self):
        config=self.config()
        node=type("ViggleParserTest",(YtonViggleReplacementSegment,),{})
        node.hidden=io.HiddenHolder.from_dict({io.Hidden.unique_id:"parser",io.Hidden.dynprompt:fixture.DynamicPrompt({})})
        result=node.execute({"config":json.dumps(config),"index":0,"previous_video":None,"llm":None})
        self.assertEqual(len(result.result),14)
        self.assertIsNone(result.result[4])
        self.assertEqual(result.result[6],"")
        self.assertEqual(result.result[12:], (0, True))
        self.assertTrue(result.result[9].startswith("video/Viggle/"))
        for cls in CLASSES:
            self.assertEqual(cls.GET_NODE_INFO_V1()["name"],cls.__name__)
        config["images"]=[""]*6
        with self.assertRaisesRegex(ValueError,"四个"):
            parse_config(config)

    def test_parser_context_and_first_segment_outputs(self):
        node=type("ViggleContextParser",(YtonViggleReplacementSegment,),{})
        node.hidden=io.HiddenHolder.from_dict({io.Hidden.unique_id:"context-parser",io.Hidden.dynprompt:fixture.DynamicPrompt({})})
        config=self.config()
        for overlap in (0, 6, 12, 22):
            config["plan"]["overlap"] = overlap
            for index in (0, 1):
                with self.subTest(overlap=overlap,index=index):
                    result=node.execute({"config":json.dumps(config),"index":index,"previous_video":None,"llm":None})
                    self.assertEqual(result.result[12:], (overlap if index else 0, index == 0))
        config["plan"].update(split="shots", min_seconds=.1, cuts=[0,36,72], shot_source=config["video"])
        result=node.execute({"config":json.dumps(config),"index":1,"previous_video":None,"llm":None})
        self.assertEqual(result.result[12:], (0, False))
        definition=YtonViggleReplacementSegment.GET_NODE_INFO_V1()
        self.assertEqual(definition["output"][-2:], ["INT", "BOOLEAN"])


if __name__ == "__main__":
    unittest.main(argv=[__file__])
