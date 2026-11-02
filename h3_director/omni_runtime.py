"""A grouped H3 generation node, expanded by ComfyUI into existing nodes."""
import math

import torch


def plan_context_length(target_frames, context_frames, context_auto_extend):
    requested = target_frames + (context_frames if context_auto_extend else 0)
    if requested <= context_frames:
        raise ValueError("关闭自动增加上下文时长时，片段总帧数必须大于上下文帧数。")
    length = 5 + 17 * max(0, math.ceil((requested - 5) / 17))
    if length > 3592:
        raise ValueError("当前片段加上上下文后超出H3最大采样帧数3592，请先拆分视频。")
    return length, context_frames, length - requested


class YtonH3ReplicaPlan:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO",),
            "context_frames": ("INT", {"default": 0, "min": 0, "max": 56}),
            "context_auto_extend": ("BOOLEAN", {"default": True}),
        }}

    INPUT_IS_LIST = True
    RETURN_TYPES = ("INT", "INT", "INT")
    RETURN_NAMES = ("length", "head_trim_frames", "tail_trim_frames")
    FUNCTION = "plan"
    CATEGORY = "yton-nodes/MiniMax H3"
    DESCRIPTION = "全模态复刻模式内部时长规划：只读取第一个视频，补足上下文与H3帧格。"

    def plan(self, video, context_frames, context_auto_extend):
        if not video or video[0] is None:
            raise ValueError("复刻模式需要传入至少一个视频，时长取第一个视频。")
        duration = float(video[0].get_duration())
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("复刻模式的第一个视频时长无效。")
        target = max(1, math.floor(duration * 24 + 0.5))
        overlap = int(context_frames[0])
        return plan_context_length(target, overlap, context_auto_extend[0])


class YtonH3SegmentPlan:
    """Plan one visible source segment and its H3 context prefix."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "duration": ("FLOAT", {"min": 0.21, "max": 149.66}),
            "clip_index": ("INT", {"min": 1, "max": 9999}),
            "context_frames": ("INT", {"min": 0, "max": 56}),
        }}

    RETURN_TYPES = ("INT", "INT", "INT", "INT", "INT")
    RETURN_NAMES = ("length", "head_trim_frames", "tail_trim_frames", "start_frame", "visible_frames")
    FUNCTION = "plan"
    CATEGORY = "yton-nodes/MiniMax H3"

    def plan(self, duration, clip_index, context_frames):
        visible = max(1, math.floor(float(duration) * 24 + 0.5))
        overlap = int(context_frames)
        length = 5 + 17 * max(0, math.ceil((visible + overlap - 5) / 17))
        if length > 3592:
            raise ValueError("当前片段加上 22 帧上下文后超出 H3 最大采样帧数 3592，请缩短时长。")
        # Trim the context prefix from the head and the H3 alignment surplus
        # from the tail. This keeps frame `visible` aligned with the source
        # timeline while still delivering exactly the requested duration.
        return (length, overlap, length - visible - overlap,
                max(0, (int(clip_index) - 1) * visible - overlap), visible)


class YtonH3SegmentTrim:
    """Trim H3 context from the head and frame-grid surplus from the tail."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "head_trim_frames": ("INT", {"default": 0, "min": 0, "max": 4096}),
            "tail_trim_frames": ("INT", {"default": 0, "min": 0, "max": 4096}),
        }, "optional": {
            "audio": ("AUDIO",),
            "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 240.0, "step": 0.001}),
        }}

    RETURN_TYPES = ("IMAGE", "AUDIO")
    RETURN_NAMES = ("images", "audio")
    FUNCTION = "trim"
    CATEGORY = "yton-nodes/MiniMax H3"

    def trim(self, images, head_trim_frames, tail_trim_frames, audio=None, fps=24.0):
        head = max(0, int(head_trim_frames))
        tail = max(0, int(tail_trim_frames))
        total = int(images.shape[0])
        if head + tail >= total:
            raise ValueError("H3 分段裁切不能移除全部画面帧。")
        end = total - tail if tail else total
        out_images = images[head:end]
        if audio is None:
            return out_images, None

        waveform = audio["waveform"]
        sample_rate = int(audio["sample_rate"])
        start_sample = int(round(head / float(fps) * sample_rate))
        want_samples = int(round((end - head) / float(fps) * sample_rate))
        if start_sample >= int(waveform.shape[-1]):
            raise ValueError("H3 分段裁切后的音频为空，请检查帧率和裁切参数。")
        out_waveform = waveform[..., start_sample:start_sample + want_samples]
        have_samples = int(out_waveform.shape[-1])
        if have_samples > want_samples:
            out_waveform = out_waveform[..., :want_samples]
        elif have_samples < want_samples:
            out_waveform = torch.nn.functional.pad(out_waveform, (0, want_samples - have_samples))
        out_audio = {"waveform": out_waveform, "sample_rate": sample_rate}
        return out_images, out_audio


NODE_CLASS_MAPPINGS = {"YtonH3ReplicaPlan": YtonH3ReplicaPlan,
                       "YtonH3SegmentPlan": YtonH3SegmentPlan,
                       "YtonH3SegmentTrim": YtonH3SegmentTrim}
NODE_DISPLAY_NAME_MAPPINGS = {"YtonH3ReplicaPlan": "H3 复刻时长规划",
                              "YtonH3SegmentPlan": "H3 分段时长规划",
                              "YtonH3SegmentTrim": "H3 分段头尾裁切"}
