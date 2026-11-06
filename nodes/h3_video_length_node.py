"""Frame-exact H3 tail padding and restoration, independent of task configuration."""

from fractions import Fraction
from math import ceil

import torch
import torch.nn.functional as F
from comfy_api.latest import InputImpl, Types, io


FPS = 24


def aligned_frames(count):
    return max(5, count + (5 - count) % 17)


def adjust(video, original_frames=0):
    if type(original_frames) is not int or original_frames < 0:
        raise ValueError("原长度须为非负整数；0 表示自动补帧。")
    components = video.get_components()
    rate = Fraction(components.frame_rate)
    images = components.images
    if rate <= 0 or not len(images):
        raise ValueError("视频没有有效帧率或画面。")
    count = ceil(Fraction(len(images) * FPS, 1) / rate)
    if rate != FPS:
        indices = torch.arange(count, device=images.device) * rate.numerator // (rate.denominator * FPS)
        images = images[indices.long().clamp_max(len(images) - 1)]
    if original_frames > count:
        raise ValueError(f"当前视频只有 {count} 帧，无法恢复为 {original_frames} 帧。")
    target = original_frames or aligned_frames(count)
    if target > count:
        images = torch.cat([images, images[-1:].expand(target - count, -1, -1, -1)])
    elif target < count:
        images = images[:target].clone()
    audio = components.audio
    if audio is not None:
        samples = round(target * audio["sample_rate"] / FPS)
        # Padded video tails get silence, even if the input audio outlasts the source frames.
        source_samples = round(min(count, target) * audio["sample_rate"] / FPS)
        waveform = audio["waveform"][..., :source_samples].clone()
        audio = {**audio, "waveform": F.pad(waveform, (0, max(0, samples - waveform.shape[-1])))}
    result = InputImpl.VideoFromComponents(Types.VideoComponents(images=images, frame_rate=Fraction(FPS), audio=audio))
    return result, images, audio, len(images), original_frames or count


class YtonH3VideoLength(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonH3VideoLength", display_name="H3 视频长度调整", category="yton-nodes/MiniMax H3",
            description="统一为 24fps。原长度为 0 时重复末帧补到 17n+5；原长度大于 0 时裁尾至指定帧数。原长度输出可连接生成后的同名输入。",
            inputs=[io.Video.Input("video", display_name="视频"),
                    io.Int.Input("original_frames", default=0, min=0, display_name="原长度（帧）",
                                 tooltip="0：自动补到 H3 支持的帧数。正整数：裁回该帧数；可连接生成前节点的原长度输出。")],
            outputs=[io.Video.Output(display_name="视频"), io.Image.Output(display_name="视频帧"),
                     io.Audio.Output(display_name="音频"), io.Int.Output(display_name="长度（帧）"),
                     io.Int.Output(display_name="原长度（帧）", tooltip="输入视频按 24fps 换算后的帧数；恢复时输出指定的原长度。")])

    @classmethod
    def execute(cls, video, original_frames=0):
        return io.NodeOutput(*adjust(video, original_frames))
