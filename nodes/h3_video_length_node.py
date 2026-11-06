"""Frame-exact H3 tail padding and restoration, independent of task configuration."""

from fractions import Fraction
from math import ceil

import torch
import torch.nn.functional as F
from comfy_api.latest import InputImpl, Types, io


FPS = 24


def aligned_frames(count):
    return max(5, count + (5 - count) % 17)


def adjust(video, mode="延长", original_frames=0, context_frames=0, first_segment=True):
    if mode not in ("延长", "复原"):
        raise ValueError("请选择延长或复原。")
    if type(original_frames) is not int or original_frames < 0:
        raise ValueError("原长度须为非负整数。")
    if type(context_frames) is not int or context_frames < 0:
        raise ValueError("上下文长度须为非负整数。")
    if mode == "复原" and original_frames == 0:
        raise ValueError("复原时请填写原长度，或连接延长节点的“原长度（帧）”输出。")
    components = video.get_components()
    rate = Fraction(components.frame_rate)
    images = components.images
    if rate <= 0 or not len(images):
        raise ValueError("视频没有有效帧率或画面。")
    count = ceil(Fraction(len(images) * FPS, 1) / rate)
    if rate != FPS:
        indices = torch.arange(count, device=images.device) * rate.numerator // (rate.denominator * FPS)
        images = images[indices.long().clamp_max(len(images) - 1)]
    original = count if mode == "延长" else original_frames
    target = aligned_frames(count) if mode == "延长" else original
    head = context_frames if mode == "复原" and not first_segment else 0
    if mode == "复原":
        if target > count:
            raise ValueError(f"当前视频只有 {count} 帧，无法恢复为 {original_frames} 帧。")
        if head >= target:
            raise ValueError("上下文长度须小于原长度。")
    if target > count:
        images = torch.cat([images, images[-1:].expand(target - count, -1, -1, -1)])
    elif head or target < count:
        images = images[head:target].clone()
    audio = components.audio
    if audio is not None:
        samples = round(len(images) * audio["sample_rate"] / FPS)
        # Padded video tails get silence, even if the input audio outlasts the source frames.
        source_samples = round(min(count, target) * audio["sample_rate"] / FPS)
        start = round(head * audio["sample_rate"] / FPS)
        waveform = audio["waveform"][..., start:source_samples][..., :samples].clone()
        audio = {**audio, "waveform": F.pad(waveform, (0, max(0, samples - waveform.shape[-1])))}
    result = InputImpl.VideoFromComponents(Types.VideoComponents(images=images, frame_rate=Fraction(FPS), audio=audio))
    return result, images, audio, len(images), original


class YtonH3VideoLength(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonH3VideoLength", display_name="H3 视频长度调整", category="yton-nodes/MiniMax H3",
            description="统一为 24fps。延长：重复末帧补到 17n+5。复原：尾部裁去补帧，非首段再从开头裁去上下文；音轨同步处理。",
            inputs=[io.Video.Input("video", display_name="视频"),
                    io.Combo.Input("mode", options=["延长", "复原"], default="延长", display_name="处理模式"),
                    io.Int.Input("original_frames", default=0, min=0, display_name="原长度（帧）",
                                 tooltip="复原时使用：连接延长节点的原长度输出，表示补帧前的总帧数（包含上下文）。延长模式自动读取视频长度。"),
                    io.Int.Input("context_frames", default=0, min=0, display_name="上下文长度（帧）",
                                 tooltip="复原非首段时，从开头裁去这些重叠帧；可连接配置解析器的同名输出。"),
                    io.Boolean.Input("first_segment", default=True, display_name="是否首段",
                                     tooltip="复原时，首段保留开头；非首段裁去上下文。可连接配置解析器的布尔输出。")],
            outputs=[io.Video.Output(display_name="视频"), io.Image.Output(display_name="视频帧"),
                     io.Audio.Output(display_name="音频"), io.Int.Output(display_name="长度（帧）"),
                     io.Int.Output(display_name="原长度（帧）", tooltip="输入视频按 24fps 换算后的帧数；恢复时输出指定的原长度。")])

    @classmethod
    def execute(cls, video, mode="延长", original_frames=0, context_frames=0, first_segment=True):
        return io.NodeOutput(*adjust(video, mode, original_frames, context_frames, first_segment))
