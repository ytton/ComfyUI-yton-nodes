"""Context files for the SelfLift-style H3 continuation path.

The SelfLift reference workflow carries the previous shot through pixel/audio
guides.  It deliberately does not use the previous shot's latent as a hard
head replacement, because that can make the decoded boundary disagree with
the first generated frame.  Keep this contract separate from the original
latent-continuation node so the two workflows cannot accidentally share files.
"""

import os
from pathlib import Path
import uuid

import folder_paths
import torch
from safetensors import safe_open
from safetensors.torch import load_file, save_file

from .omni_context import CONTEXT_FRAMES, context_name


CONTRACT = "yton-h3-selflift-context-v1"


def context_file(relative):
    root = Path(folder_paths.get_output_directory()).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target.suffix != ".safetensors":
        raise ValueError("SelfLift 上下文文件必须位于 ComfyUI output 目录内，格式为 safetensors。")
    return target


def selflift_context_name(directory, index):
    return context_name(directory, index)


def _audio_components(video):
    """Return the waveform and sample rate from ComfyUI's VIDEO components."""
    components = video.get_components()
    audio = getattr(components, "audio", None)
    if audio is None and isinstance(components, dict):
        audio = components.get("audio")
    if audio is None:
        return None
    if isinstance(audio, dict):
        waveform = audio.get("waveform")
        sample_rate = audio.get("sample_rate")
    else:
        waveform = getattr(audio, "waveform", None)
        sample_rate = getattr(audio, "sample_rate", None)
    if waveform is None or sample_rate is None or int(waveform.shape[-1]) == 0:
        return None
    return waveform, int(sample_rate)


class YtonH3LoadSelfLiftContext:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"context_path": ("STRING",)}}

    RETURN_TYPES = ("IMAGE", "AUDIO", "INT")
    RETURN_NAMES = ("tail_frames", "tail_audio", "tail_count")
    FUNCTION = "load"
    CATEGORY = "yton-nodes/MiniMax H3"

    @classmethod
    def IS_CHANGED(cls, context_path, **kwargs):
        stat = context_file(context_path).stat()
        return f"{context_path}:{stat.st_size}:{stat.st_mtime_ns}"

    def load(self, context_path):
        file = context_file(context_path)
        with safe_open(str(file), framework="pt", device="cpu") as handle:
            metadata = handle.metadata()
        if metadata.get("contract") != CONTRACT:
            raise ValueError("请选择 SelfLift 无缝接续节点保存的上下文。")
        tensors = load_file(str(file), device="cpu")
        tail = tensors.get("tail_frames")
        if tail is None or tail.ndim != 4 or tail.shape[-1] < 3 or not len(tail):
            raise ValueError("SelfLift 上下文缺少有效的尾部画面。")
        if int(tail.shape[0]) < CONTEXT_FRAMES:
            raise ValueError("SelfLift 上下文至少需要 22 帧尾部画面，请把片段时长设为 1 秒以上。")
        tail = tail[..., :3].float()
        audio = None
        if "tail_audio" in tensors:
            sample_rate = int(metadata.get("tail_audio_sample_rate", "0"))
            if sample_rate > 0:
                audio = {"waveform": tensors["tail_audio"].float(), "sample_rate": sample_rate}
        return tail, audio, int(tail.shape[0])


class YtonH3SaveSelfLiftContext:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO",),
            "latent_path": ("STRING",),
            "clip_index": ("INT",),
        }}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "yton-nodes/MiniMax H3"

    def save(self, video, latent_path, clip_index):
        path = context_file(selflift_context_name(latent_path, clip_index))
        components = video.get_components()
        frames = components.images
        if frames is None or not len(frames):
            raise ValueError("SelfLift 上下文不能保存空视频。")
        tail_count = min(CONTEXT_FRAMES, int(frames.shape[0]))
        tensors = {
            "tail_frames": frames[-tail_count:, ..., :3].to(
                device="cpu", dtype=torch.float16, copy=True).contiguous()
        }
        metadata = {"contract": CONTRACT}

        audio_info = _audio_components(video)
        if audio_info is not None:
            waveform, sample_rate = audio_info
            fps = float(video.get_frame_rate())
            duration = tail_count / max(fps, 1e-6)
            want_samples = max(1, int(round(duration * sample_rate)))
            tensors["tail_audio"] = waveform[..., -want_samples:].to(
                device="cpu", dtype=torch.float32, copy=True).contiguous()
            metadata["tail_audio_sample_rate"] = str(sample_rate)

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
        try:
            save_file(tensors, str(temporary), metadata=metadata)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        relative = path.relative_to(Path(folder_paths.get_output_directory()).resolve())
        item = {"filename": relative.name, "subfolder": relative.parent.as_posix(),
                "type": "output", "clip_index": int(clip_index)}
        return {"ui": {"h3_selflift_context": [item]}, "result": (relative.as_posix(),)}


NODE_CLASS_MAPPINGS = {
    "YtonH3LoadSelfLiftContext": YtonH3LoadSelfLiftContext,
    "YtonH3SaveSelfLiftContext": YtonH3SaveSelfLiftContext,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "YtonH3LoadSelfLiftContext": "H3 读取 SelfLift 无缝上下文",
    "YtonH3SaveSelfLiftContext": "H3 保存 SelfLift 无缝上下文",
}
