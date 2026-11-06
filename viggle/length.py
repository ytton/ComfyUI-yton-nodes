"""Pad the tail only, then restore source timing and remove overlap once."""

from fractions import Fraction
from math import ceil

import torch
import torch.nn.functional as F
from comfy_api.latest import InputImpl, Types, io


def aligned_frames(count):
    if type(count) is not int or count < 1:
        raise ValueError("视频没有有效画面。")
    result = max(56, ceil((count - 5) / 17) * 17 + 5)
    if result > 345:
        raise ValueError("当前片段超过 Viggle 的 345 帧上限，请缩短分段后再生成。")
    return result


def at_24fps(components):
    rate = Fraction(components.frame_rate)
    images = components.images
    if rate <= 0 or not len(images):
        raise ValueError("视频没有有效帧率或画面。")
    if rate == 24:
        return images
    count = ceil(Fraction(len(images) * 24, 1) / rate)
    indices = torch.arange(count, device=images.device) * rate.numerator // (rate.denominator * 24)
    return images[indices.long().clamp_max(len(images) - 1)]


def audio_range(audio, start, count):
    if audio is None:
        return None
    rate = audio["sample_rate"]
    left, size = round(start * rate / 24), round(count * rate / 24)
    waveform = audio["waveform"][..., left:left + size].clone()
    return {**audio, "waveform": F.pad(waveform, (0, max(0, size - waveform.shape[-1])))}


def adjust(video, mode, context, first_segment, segment_info=None, length_info=None):
    if context == "按片段配置":
        source = segment_info if mode == "适配 H3" else length_info
        if source is None:
            raise ValueError("自动读取上下文需要连接片段信息或长度信息。")
        overlap = source["context_frames"]
    elif context in ("无上下文", "5 帧"):
        overlap = 5 if context == "5 帧" else 0
    else:
        raise ValueError("上下文选择无效。")
    components = video.get_components()
    images = at_24fps(components)
    if mode == "适配 H3":
        count = len(images)
        if segment_info is not None:
            if segment_info["context_frames"] != overlap:
                raise ValueError("长度调整的上下文与配置器不一致，请选择相同的上下文。")
            if segment_info["source_frames"] != count:
                raise ValueError("视频帧数与配置器的当前片段不一致。")
            head = segment_info["overlap_frames"]
        else:
            head = 0 if first_segment else overlap
        if count <= head:
            raise ValueError("片段长度必须大于重叠帧数。")
        target = aligned_frames(count)
        info = {"source_frames": count, "padded_frames": target, "overlap_frames": head,
                "context_frames": overlap, "fps": 24}
        if target > count:
            images = torch.cat([images, images[-1:].expand(target - count, -1, -1, -1)])
        audio = audio_range(components.audio, 0, target)
    elif mode == "恢复原长度":
        if length_info is None:
            raise ValueError("请连接生成前“适配 H3”节点输出的长度信息。")
        info = dict(length_info)
        if info["context_frames"] != overlap:
            raise ValueError("恢复原长度与生成前节点的上下文选择不一致。")
        count, head = info["source_frames"], info["overlap_frames"]
        if len(images) < count:
            raise ValueError("生成结果短于原视频片段，无法恢复原长度。")
        images = images[head:count].clone()
        audio = audio_range(components.audio, head, count - head)
    else:
        raise ValueError("视频长度调整模式无效。")
    result = InputImpl.VideoFromComponents(Types.VideoComponents(images=images, frame_rate=Fraction(24), audio=audio))
    return result, images, audio, len(images), info["source_frames"], info


class YtonViggleVideoLength(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonViggleVideoLength", display_name="Viggle 视频长度调整", category="yton-nodes/Viggle",
            description="生成前仅复制末帧补到 17n+5；生成后依据长度信息裁尾，并从后续段去除重复开头。全程 24fps，不重排原有帧。",
            inputs=[io.Video.Input("video", display_name="视频"),
                    io.Combo.Input("mode", options=["适配 H3", "恢复原长度"], default="适配 H3", display_name="处理模式"),
                    io.Combo.Input("context", options=["按片段配置", "无上下文", "5 帧"], default="按片段配置", display_name="上下文",
                                   tooltip="按片段配置时，从片段信息或长度信息读取视频编辑器保存的重叠帧数。"),
                    io.Boolean.Input("first_segment", default=True, display_name="首段", tooltip="未连接片段信息时使用；首段保留开头。"),
                    io.Custom("YTON_VIGGLE_SEGMENT").Input("segment_info", optional=True, display_name="片段信息"),
                    io.Custom("YTON_VIGGLE_LENGTH").Input("length_info", optional=True, display_name="长度信息")],
            outputs=[io.Video.Output(display_name="视频"), io.Image.Output(display_name="视频帧"),
                     io.Audio.Output(display_name="音频"), io.Int.Output(display_name="长度（帧）"),
                     io.Int.Output(display_name="原始帧数"), io.Custom("YTON_VIGGLE_LENGTH").Output(display_name="长度信息")])

    @classmethod
    def execute(cls, video, mode, context, first_segment, segment_info=None, length_info=None):
        return io.NodeOutput(*adjust(video, mode, context, first_segment, segment_info, length_info))
