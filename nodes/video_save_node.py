"""A non-blocking output node for native VIDEO or IMAGE + AUDIO."""

from fractions import Fraction

from comfy.cli_args import args
from comfy_api.latest import InputImpl, Types, io, ui

from ..video_save import DEFAULT_PATH, preview_result, save_video, warn


class YtonVideoSave(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="YtonVideoSave", display_name="保存视频", category="yton-nodes/媒体",
            description="保存 VIDEO 或图片序列帧与音频。VIDEO 优先；视频与音频同时接入时替换音轨。路径相对于 output，支持点击插入标签。同名文件自动递增；保存失败时尝试备用位置，最终失败仍输出原视频并记录警告。",
            is_output_node=True,
            inputs=[
                io.Video.Input("video", optional=True, display_name="视频"),
                io.Image.Input("images", optional=True, display_name="序列帧"),
                io.Audio.Input("audio", optional=True, display_name="音频"),
                io.String.Input("save_path", default=DEFAULT_PATH, display_name="保存路径",
                                tooltip="相对于 ComfyUI/output，包含目录与文件名前缀，不必填写扩展名。"),
                io.Combo.Input("format", options=["mp4", "mkv", "webm", "mov"], default="mp4", display_name="格式"),
                io.Combo.Input("codec", options=["auto", "h264", "av1", "prores"], default="auto", display_name="编码"),
                io.Float.Input("fps", default=0, min=0, max=240, step=.01, display_name="帧率",
                               tooltip="0：沿用视频帧率，序列帧使用 24 fps。视频修改帧率时保持时长。"),
                io.Int.Input("crf", default=18, min=0, max=51, display_name="质量 CRF", tooltip="越小越清晰、文件越大；ProRes 不使用此项。"),
                io.Combo.Input("preset", options=["ultrafast", "fast", "medium", "slow"], default="fast", display_name="编码速度",
                               tooltip="H.264 编码速度；slow 压缩效率更高。"),
                io.Int.Input("index", default=0, min=0, max=2147483647, display_name="文件序号",
                             tooltip="0 自动递增；大于 0 从指定编号开始，同名时继续递增，不覆盖成片。"),
                io.Boolean.Input("save_metadata", default=True, display_name="保存工作流信息"),
            ],
            outputs=[io.Video.Output(display_name="视频")],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
        )

    @classmethod
    def execute(cls, save_path=DEFAULT_PATH, format="mp4", codec="auto", fps=0, crf=18,
                preset="fast", index=0, save_metadata=True, video=None, images=None, audio=None):
        source = video
        messages = []
        state = {"saved": False, "path": "", "warnings": messages}
        preview = {}
        try:
            override_audio = audio if video is not None else None
            if source is None:
                if images is None:
                    raise ValueError("没有接入视频或图片序列帧")
                source = InputImpl.VideoFromComponents(Types.VideoComponents(
                    images=images, audio=audio, frame_rate=Fraction(fps or 24).limit_denominator(100000)))
            metadata = None
            if save_metadata and not args.disable_metadata and cls.hidden:
                metadata = dict(cls.hidden.extra_pnginfo or {})
                if cls.hidden.prompt is not None:
                    metadata["prompt"] = cls.hidden.prompt
            path = save_video(source, save_path, index, format, codec, fps, crf, preset, override_audio, metadata, messages)
            state.update(saved=True, path=str(path))
            result = preview_result(path)
            if result:
                preview = ui.PreviewVideo([result]).as_dict()
            source = InputImpl.VideoFromFile(str(path))
        except Exception as error:
            # This output node must not turn a completed generation into a failed job.
            warn(messages, f"{'预览登记失败' if state['saved'] else '未保存'}：{error}；继续输出视频，不中断工作流。")
        return io.NodeOutput(source, ui={**preview, "yton_video_save": [state]})
