"""Frame-exact reference padding and output trimming for H3 video replacement."""

from fractions import Fraction
from math import ceil

import torch
import torch.nn.functional as F
from comfy_api.latest import InputImpl, Types


FPS = 24


def fit_audio(audio, frames):
    if audio is None:
        return None
    waveform = audio["waveform"]
    samples = round(frames * audio["sample_rate"] / FPS)
    waveform = waveform[..., :samples].clone()
    if waveform.shape[-1] < samples:
        waveform = F.pad(waveform, (0, samples - waveform.shape[-1]))
    return {**audio, "waveform": waveform}


class YtonH3VideoReplacementPrepare:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "enabled": ("BOOLEAN", {"default": False}),
            "manual_length": ("INT", {"default": 124, "min": 5, "forceInput": True}),
            "context_frames": ("INT", {"default": 0, "min": 0, "forceInput": True}),
        }, "optional": {"video": ("VIDEO",)}}

    INPUT_IS_LIST = True
    RETURN_TYPES = ("VIDEO", "INT", "INT", "BOOLEAN")
    RETURN_NAMES = ("video", "length", "source_frames", "match_context_tail")
    OUTPUT_IS_LIST = (True, False, False, False)
    FUNCTION = "prepare"
    CATEGORY = "yton-nodes/MiniMax H3"
    DESCRIPTION = (
        "开启后以媒体加载器第一个视频的完整时长计算生成长度（24fps 向上取整）。"
        "预留上下文帧，向上补到 5+17k；只重复末帧，音轨补静音。"
        "上下文参考前缀使用首帧和静音占位，真实上下文仍由 Motion Mask 提供。"
        "关闭时保留原视频列表和手动时长。"
    )

    def prepare(self, enabled, manual_length, context_frames, video=None):
        videos = list(video or [])
        if not enabled[0]:
            return videos, manual_length[0], 0, True
        if not videos or videos[0] is None:
            raise ValueError("人物替换：请在媒体加载器的第一个视频槽位加载并启用参考视频。")

        components = videos[0].get_components()
        images = components.images
        rate = Fraction(components.frame_rate)
        count = int(images.shape[0])
        if count == 0 or rate <= 0:
            raise ValueError("人物替换：参考视频没有有效画面或帧率。")
        source_frames = ceil(Fraction(count * FPS, 1) / rate)
        indexes = torch.arange(source_frames, device=images.device)
        indexes = (indexes * rate.numerator // (rate.denominator * FPS)).long()
        images = images[indexes.clamp_max(count - 1)]

        prefix = int(context_frames[0])
        length = max(5, source_frames + prefix)
        length += (5 - length) % 17
        tail = length - source_frames - prefix
        images = torch.cat((
            images[:1].expand(prefix, -1, -1, -1), images,
            images[-1:].expand(tail, -1, -1, -1),
        ))

        audio = fit_audio(components.audio, source_frames)
        if audio is not None:
            before = round(prefix * audio["sample_rate"] / FPS)
            total = round(length * audio["sample_rate"] / FPS)
            after = total - before - audio["waveform"].shape[-1]
            audio = {**audio, "waveform": F.pad(audio["waveform"], (before, after))}
        videos[0] = InputImpl.VideoFromComponents(Types.VideoComponents(
            images=images, frame_rate=Fraction(FPS), audio=audio,
        ))
        return videos, length, source_frames, False


class YtonH3VideoReplacementTrim:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "source_frames": ("INT", {"default": 0, "min": 0, "forceInput": True}),
        }, "optional": {"audio": ("AUDIO",)}}

    RETURN_TYPES = ("IMAGE", "AUDIO")
    RETURN_NAMES = ("images", "audio")
    FUNCTION = "trim"
    CATEGORY = "yton-nodes/MiniMax H3"
    DESCRIPTION = "在 Motion 上下文裁头之后，声画同步裁回原视频的 24fps 帧数。只裁尾或补静音，不变速；0 表示关闭人物替换。"

    def trim(self, images, source_frames, audio=None):
        if source_frames == 0:
            return images, audio
        if images.shape[0] < source_frames:
            raise ValueError("人物替换：生成画面短于参考视频，请检查上下文开关和生成长度连线。")
        return images[:source_frames].clone(), fit_audio(audio, source_frames)
