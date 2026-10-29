"""Persist both sampling stages and the displayed tail for one H3 clip."""
import os
from pathlib import Path
import uuid

import folder_paths
import torch
from comfy.nested_tensor import NestedTensor
from safetensors import safe_open
from safetensors.torch import load_file, save_file

CONTEXT_FRAMES = 22
CONTEXT_TOKENS = 7
CONTRACT = "yton-h3-omni-context"


def context_file(relative):
    root = Path(folder_paths.get_output_directory()).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target.suffix != ".safetensors":
        raise ValueError("上下文文件必须位于 ComfyUI output 目录内，格式为 safetensors。")
    return target


def context_name(directory, index):
    return directory.rstrip("/\\") + f"/clip_{index:05d}.safetensors"


class YtonH3LoadOmniContext:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "context_path": ("STRING",),
            "main_width": ("INT",), "main_height": ("INT",),
            "width": ("INT",), "height": ("INT",),
        }}

    RETURN_TYPES = ("LATENT", "LATENT", "IMAGE", "INT")
    RETURN_NAMES = ("main_latent", "final_latent", "tail_frames", "tail_count")
    FUNCTION = "load"
    CATEGORY = "yton-nodes/MiniMax H3"

    @classmethod
    def IS_CHANGED(cls, context_path, **kwargs):
        stat = context_file(context_path).stat()
        return f"{context_path}:{stat.st_size}:{stat.st_mtime_ns}"

    def load(self, context_path, main_width, main_height, width, height):
        file = context_file(context_path)
        with safe_open(str(file), framework="pt", device="cpu") as handle:
            metadata = handle.metadata()
        if metadata.get("contract") != CONTRACT:
            raise ValueError("请选择 H3 全模态生成节点保存的片段上下文。")
        tensors = load_file(str(file), device="cpu")
        main = {"samples": NestedTensor((tensors["main.video"], tensors["main.audio"]))}
        final = main if metadata["sampling_mode"] == "单采" else {
            "samples": NestedTensor((tensors["final.video"], tensors["final.audio"]))}
        for label, latent, target_w, target_h in (
            ("主采样", main, main_width, main_height), ("最终采样", final, width, height)
        ):
            video, _ = latent["samples"].unbind()
            if tuple(video.shape[-2:]) != (target_h // 16, target_w // 16):
                raise ValueError(f"{label}的上下文分辨率不一致，请保持整条接续链的分辨率及首采比例相同。")
            if video.shape[2] < CONTEXT_TOKENS:
                raise ValueError("上一段不足 22 帧，无法提取接续需要的 latent 尾部。")
        tail = tensors["tail_frames"].float()
        if tuple(tail.shape[1:]) != (height, width, 3) or not len(tail):
            raise ValueError("上下文尾部画面与当前输出分辨率不一致。")
        return main, final, tail, len(tail)


class YtonH3SaveOmniContext:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO",), "main_latent": ("LATENT",), "final_latent": ("LATENT",),
            "sampling_mode": (["单采", "二采"],), "latent_path": ("STRING",), "clip_index": ("INT",),
        }}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "yton-nodes/MiniMax H3"

    def save(self, video, main_latent, final_latent, sampling_mode, latent_path, clip_index):
        path = context_file(context_name(latent_path, clip_index))
        tensors = {}
        stages = [("main", main_latent)]
        if sampling_mode == "二采":
            stages.append(("final", final_latent))
        for prefix, latent in stages:
            v, a = latent["samples"].unbind()
            tensors[prefix + ".video"] = v.to(device="cpu", copy=True).contiguous()
            tensors[prefix + ".audio"] = a.to(device="cpu", copy=True).contiguous()
        # Keep the full physical context window for seam matching. The next
        # segment uses these frames only as a visual reference; its latent
        # context remains the authoritative continuation state.
        frames = video.get_components().images
        tensors["tail_frames"] = frames[-min(CONTEXT_FRAMES, len(frames)):].to(
            device="cpu", dtype=torch.float16, copy=True).contiguous()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
        try:
            save_file(tensors, str(temporary), metadata={"contract": CONTRACT, "sampling_mode": sampling_mode})
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        relative = path.relative_to(Path(folder_paths.get_output_directory()).resolve())
        item = {"filename": relative.name, "subfolder": relative.parent.as_posix(),
                "type": "output", "clip_index": clip_index}
        return {"ui": {"h3_omni_context": [item]}, "result": (relative.as_posix(),)}


NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in (YtonH3LoadOmniContext, YtonH3SaveOmniContext)}
NODE_DISPLAY_NAME_MAPPINGS = {"YtonH3LoadOmniContext": "H3 读取分段上下文", "YtonH3SaveOmniContext": "H3 保存分段上下文"}
