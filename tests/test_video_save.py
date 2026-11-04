"""CPU integration coverage for output survival, audio, fps and real filenames."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fractions import Fraction
import logging
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import av

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN.parents[1]))
sys.argv = [sys.argv[0], "--cpu"]
import comfy.options
comfy.options.enable_args_parsing()
import folder_paths
import torch
from comfy_api.latest import InputImpl, Types, io
import execution
import nodes

package = types.ModuleType("video_save_test_plugin")
package.__path__ = [str(PLUGIN)]
sys.modules[package.__name__] = package
from video_save_test_plugin import video_save
from video_save_test_plugin.nodes.video_save_node import YtonVideoSave


class VideoSaveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="yton-video-save-test-")
        self.root = Path(self.directory.name)
        for name in ("output", "temp"):
            (self.root / name).mkdir()
        self.patches = [patch.object(folder_paths, f"get_{name}_directory", return_value=str(self.root / name))
                        for name in ("output", "temp")]
        for item in self.patches:
            item.start()
        self.node = type("VideoSaveTestNode", (YtonVideoSave,), {})
        self.node.hidden = io.HiddenHolder.from_dict({})
        self.images = torch.zeros(12, 48, 64, 3)
        self.images[:, :, :32, 0] = .8
        self.images[:, :, 32:, 2] = .8
        self.audio = {"waveform": torch.sin(torch.arange(24000) * .06).reshape(1, 1, -1) * .2,
                      "sample_rate": 48000}
        self.source = InputImpl.VideoFromComponents(Types.VideoComponents(
            images=self.images, audio=self.audio, frame_rate=Fraction(24)))

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.directory.cleanup()

    def result(self, result):
        self.assertEqual(len(result.result), 1)
        state = result.ui["yton_video_save"][0]
        if state["saved"]:
            self.assertTrue(Path(state["path"]).is_file())
            video_save.valid_video(Path(state["path"]))
        return state

    def test_schema_supports_both_native_video_and_frames(self):
        schema = self.node.define_schema()
        self.assertTrue(schema.is_output_node)
        self.assertEqual(schema.node_id, "YtonVideoSave")

    def test_native_video_output_and_history_preview(self):
        result = self.node.execute(video=self.source)
        state = self.result(result)
        self.assertTrue(state["saved"])
        self.assertFalse(state["warnings"])
        self.assertEqual(result.result[0].get_frame_count(), 12)
        self.assertEqual(result.result[0].get_dimensions(), (64, 48))
        self.assertEqual(result.ui["images"][0]["type"], "output")
        self.assertTrue(result.ui["animated"][0])
        with av.open(state["path"]) as container:
            self.assertTrue(container.streams.audio)

    def test_image_sequence_and_audio(self):
        result = self.node.execute(images=self.images, audio=self.audio, fps=30)
        self.assertTrue(self.result(result)["saved"])
        self.assertEqual(result.result[0].get_frame_rate(), Fraction(30))
        self.assertAlmostEqual(result.result[0].get_duration(), .4, places=2)
        self.assertIsNotNone(result.result[0].get_components().audio)

    def test_video_fps_resampling_preserves_duration(self):
        result = self.node.execute(video=self.source, fps=12)
        self.assertTrue(self.result(result)["saved"])
        self.assertEqual(result.result[0].get_frame_rate(), Fraction(12))
        self.assertEqual(result.result[0].get_frame_count(), 6)
        self.assertAlmostEqual(result.result[0].get_duration(), .5, places=2)

    def test_video_without_audio_fps_resampling(self):
        source = InputImpl.VideoFromComponents(Types.VideoComponents(images=self.images, frame_rate=Fraction(24)))
        result = self.node.execute(video=source, fps=48)
        self.assertTrue(self.result(result)["saved"])
        self.assertFalse(self.result(result)["warnings"])
        self.assertEqual(result.result[0].get_frame_count(), 24)

    def test_separate_audio_replaces_native_track(self):
        silent = {**self.audio, "waveform": torch.zeros_like(self.audio["waveform"])}
        result = self.node.execute(video=self.source, audio=silent)
        self.assertTrue(self.result(result)["saved"])
        components = result.result[0].get_components()
        self.assertLess(float(components.audio["waveform"].abs().max()), .002)
        self.assertEqual(components.images.shape[0], 12)

    def test_short_audio_does_not_truncate_video(self):
        short = {**self.audio, "waveform": self.audio["waveform"][..., :4800]}
        result = self.node.execute(video=self.source, audio=short)
        self.assertTrue(self.result(result)["saved"])
        self.assertEqual(result.result[0].get_frame_count(), 12)

    def test_path_tags_and_actual_resolution(self):
        class FixedTime:
            @staticmethod
            def now():
                return datetime(2026, 11, 4, 14, 0, 30)
        template = "视频/{date}/{time}/{resolution}-{fps}fps-{frames}f-{duration}/片段-{index}"
        with patch.object(video_save, "datetime", FixedTime):
            result = self.node.execute(video=self.source, save_path=template, index=7)
        state = self.result(result)
        self.assertEqual(Path(state["path"]).relative_to(self.root / "output").as_posix(),
                         "视频/2026-11-04/14-00-30/64x48-24fps-12f-0.50s/片段-00007.mp4")

    def test_existing_file_is_not_overwritten(self):
        first = self.node.execute(video=self.source, save_path="same-{index}", index=1)
        state = self.result(first)
        before = Path(state["path"]).read_bytes()
        second = self.node.execute(video=self.source, save_path="same-{index}", index=1)
        self.assertNotEqual(self.result(second)["path"], state["path"])
        self.assertEqual(Path(state["path"]).read_bytes(), before)

    def test_concurrent_publish_uses_distinct_names(self):
        first = self.node.execute(video=self.source)
        source = Path(self.result(first)["path"])
        def publish(_):
            return video_save.publish(source, self.root / "output", "并发-{index}", {}, 0)
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(publish, range(8)))
        self.assertEqual(len(set(paths)), 8)
        self.assertTrue(all(path.read_bytes() == source.read_bytes() for path in paths))
        self.assertFalse(list((self.root / "output").glob("*.part")))

    def test_invalid_paths_save_to_recovery_and_log_actual_path(self):
        for template in ("bad:name/file", "../outside", "C:/outside/file", "/absolute/file", "CON/file", "ok/{unknown}", "trailing./file"):
            with self.subTest(template=template), self.assertLogs(video_save.LOGGER, level=logging.WARNING) as logs:
                result = self.node.execute(video=self.source, save_path=template)
                state = self.result(result)
                self.assertTrue(state["saved"])
                self.assertIn("video/恢复/", Path(state["path"]).as_posix())
                self.assertIn(state["path"], "\n".join(logs.output))

    def test_symlink_destination_cannot_escape_output(self):
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (self.root / "output" / "link").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Windows needs symlink permission")
        state = self.result(self.node.execute(video=self.source, save_path="link/escaped-{index}"))
        self.assertTrue(state["saved"])
        self.assertFalse(list(outside.iterdir()))

    def test_destination_permission_failure_keeps_temporary_video_and_preview(self):
        with patch.object(video_save, "publish", side_effect=PermissionError("禁止写入")):
            result = self.node.execute(video=self.source)
        state = self.result(result)
        self.assertTrue(state["saved"])
        self.assertIn("保留临时文件", "\n".join(state["warnings"]))
        self.assertEqual(result.ui["images"][0]["type"], "temp")

    def test_primary_encoder_failure_uses_mp4_and_keeps_video(self):
        save = self.source.save_to
        calls = []
        def fail_once(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("指定编码不可用")
            return save(*args, **kwargs)
        with patch.object(self.source, "save_to", side_effect=fail_once):
            result = self.node.execute(video=self.source, format="mov", codec="prores")
        self.assertTrue(self.result(result)["saved"])
        self.assertTrue(self.result(result)["path"].endswith(".mp4"))
        self.assertEqual(result.result[0].get_frame_count(), 12)

    def test_all_encoding_failure_returns_original_without_raising(self):
        with patch.object(self.source, "save_to", side_effect=RuntimeError("磁盘已满")):
            result = self.node.execute(video=self.source)
        state = self.result(result)
        self.assertFalse(state["saved"])
        self.assertIs(result.result[0], self.source)
        self.assertIn("未保存", "\n".join(state["warnings"]))
        self.assertNotIn("images", result.ui)

    def test_temp_disk_full_retries_encoding_on_output_disk(self):
        save = self.source.save_to
        def fail_temp(path, **kwargs):
            if Path(path).is_relative_to(self.root / "temp"):
                raise OSError("临时盘已满")
            return save(path, **kwargs)
        with patch.object(self.source, "save_to", side_effect=fail_temp):
            result = self.node.execute(video=self.source)
        state = self.result(result)
        self.assertTrue(state["saved"])
        self.assertEqual(result.result[0].get_frame_count(), 12)

    def test_temp_and_output_disk_full_uses_system_temp(self):
        save = self.source.save_to
        recovery_root = self.root / "system-temp"
        recovery_root.mkdir()
        def fail_primary_disks(path, **kwargs):
            if not Path(path).is_relative_to(recovery_root):
                raise OSError("临时盘和输出盘已满")
            return save(path, **kwargs)
        with (patch.object(self.source, "save_to", side_effect=fail_primary_disks),
              patch.object(video_save.tempfile, "gettempdir", return_value=str(recovery_root)),
              patch.object(video_save, "publish", side_effect=OSError("输出盘已满"))):
            result = self.node.execute(video=self.source)
        state = self.result(result)
        self.assertTrue(state["saved"])
        self.assertTrue(Path(state["path"]).is_relative_to(recovery_root))
        self.assertEqual(result.result[0].get_frame_count(), 12)

    def test_all_staging_locations_unwritable_returns_original(self):
        with patch.object(video_save, "staging_directory", side_effect=OSError("没有可写位置")):
            result = self.node.execute(video=self.source)
        self.assertFalse(self.result(result)["saved"])
        self.assertIs(result.result[0], self.source)

    def test_comfy_executor_runs_downstream_when_saving_fails(self):
        original = self.source
        received = []

        class Source:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {}}
            RETURN_TYPES = ("VIDEO",)
            FUNCTION = "run"
            def run(self):
                return (original,)

        class Destination:
            @classmethod
            def INPUT_TYPES(cls):
                return {"required": {"video": ("VIDEO",)}}
            RETURN_TYPES = ()
            FUNCTION = "run"
            OUTPUT_NODE = True
            def run(self, video):
                received.append(video)
                return ()

        server = types.SimpleNamespace(client_id=None, last_node_id=None, send_sync=lambda *args: None)
        executor = execution.PromptExecutor(server, cache_args={"ram": 0, "ram_inactive": 0})
        prompt = {
            "1": {"class_type": "TestVideoSource", "inputs": {}},
            "2": {"class_type": "YtonVideoSave", "inputs": {
                "video": ["1", 0], "save_path": "视频/{date}/片段-{index}", "format": "mp4", "codec": "auto",
                "fps": 0, "crf": 18, "preset": "fast", "index": 0, "save_metadata": False}},
            "3": {"class_type": "TestVideoDestination", "inputs": {"video": ["2", 0]}},
        }
        classes = {"TestVideoSource": Source, "YtonVideoSave": YtonVideoSave, "TestVideoDestination": Destination}
        with patch.dict(nodes.NODE_CLASS_MAPPINGS, classes), patch.object(self.source, "save_to", side_effect=OSError("磁盘已满")):
            executor.execute(prompt, "save-failure-test", execute_outputs=["3"])
        self.assertTrue(executor.success, executor.status_messages)
        self.assertEqual(received, [original])
        self.assertFalse(executor.history_result["outputs"]["2"]["yton_video_save"][0]["saved"])

    def test_fps_adjustment_failure_preserves_already_encoded_video(self):
        with patch.object(video_save, "transform", side_effect=RuntimeError("编码器停止")):
            result = self.node.execute(video=self.source, fps=30)
        self.assertTrue(self.result(result)["saved"])
        self.assertEqual(result.result[0].get_frame_count(), 12)
        self.assertIn("调整失败", "\n".join(self.result(result)["warnings"]))

    def test_invalid_encoder_settings_are_recovered(self):
        result = self.node.execute(video=self.source, format="../../bad", codec="bad", preset="bad")
        self.assertTrue(self.result(result)["saved"])
        self.assertTrue(self.result(result)["path"].endswith(".mp4"))

    def test_real_containers_are_decodable(self):
        for container, codec in (("mkv", "h264"), ("mov", "prores"), ("webm", "av1")):
            with self.subTest(container=container):
                result = self.node.execute(video=self.source, format=container, codec=codec)
                state = self.result(result)
                self.assertTrue(state["saved"])
                self.assertTrue(state["path"].endswith("." + container))
                with av.open(state["path"]) as saved:
                    self.assertEqual(sum(1 for frame in saved.decode(video=0)), 12)

    def test_odd_dimensions_recover_to_playable_mp4(self):
        result = self.node.execute(images=torch.zeros(4, 47, 63, 3))
        state = self.result(result)
        self.assertTrue(state["saved"])
        self.assertEqual(result.result[0].get_dimensions(), (64, 48))
        self.assertEqual(result.result[0].get_frame_count(), 4)

    def test_no_input_is_reported_without_raising(self):
        result = self.node.execute()
        self.assertFalse(self.result(result)["saved"])
        self.assertIsNone(result.result[0])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
