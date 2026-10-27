"""Timeline glue for the installed H3 Relay and Motion Context node packs.

The upstream packs own latent slicing, anchoring and AV masking. This module
only aligns source windows and carries sampler output through the native loop.
"""
import json
import math


def upstream(name):
    import nodes
    if name not in nodes.NODE_CLASS_MAPPINGS:
        raise RuntimeError(f"缺少上下文依赖节点：{name}，请安装对应插件并重启 ComfyUI")
    return nodes.NODE_CLASS_MAPPINGS[name]()


def plan_windows(count, size=124, seed=42, head_trim=0, has_context=False):
    if count < 1 or size < 56 or (size - 5) % 17:
        raise ValueError("H3 窗口必须为至少 56 帧的 5+17k 帧数")
    entries, covered = [], 39 if has_context else 0
    while covered < count:
        overlap = 39 if entries or has_context else 0
        start = covered - overlap
        needed = min(size, count - start)
        target = max(56, 5 + 17 * math.ceil((needed - 5) / 17))
        end = min(count, start + target)
        entries.append(dict(contract="h3-relay-window-v2", index=len(entries),
            source_start=start, source_end_exclusive=end, window_frames=target,
            source_frames=count, history_frames=0, initial_history_frames=head_trim,
            discarded_overlap=overlap, delivered_frames=end-covered,
            padded_tail_frames=start+target-end, seed=seed, schedule="latent"))
        covered = end
    return entries


class YuanH3ContextWindowPlan:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source_frames": ("INT", {"default": 120, "min": 1}),
            "window_frames": ("INT", {"default": 124, "min": 56, "step": 17}),
            "seed": ("INT", {"default": 42, "min": 0, "max": 2**64-1})},
            "optional": {"head_trim": ("INT", {"default": 0, "min": 0}),
                         "has_context": ("BOOLEAN", {"default": False})}}
    RETURN_TYPES = ("H3_RELAY_WINDOW", "STRING", "INT", "H3_RELAY_WINDOWS")
    RETURN_NAMES = ("window_list", "timeline", "count", "windows")
    OUTPUT_IS_LIST = (True, False, False, False)
    FUNCTION = "plan"
    CATEGORY = "yton-nodes/H3"

    def plan(self, source_frames, window_frames=124, seed=42, head_trim=0, has_context=False):
        entries = plan_windows(source_frames, window_frames, seed, head_trim, has_context)
        return entries, json.dumps(entries), len(entries), {"windows": entries}


class _WindowContext:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"positive": ("CONDITIONING",), "latent": ("LATENT",),
            "vae": ("VAE",)}, "optional": {"previous": ("H3_RELAY_WINDOW_STATE",)}}
    RETURN_TYPES = ("CONDITIONING", "LATENT", "INT")
    RETURN_NAMES = ("positive", "latent", "trim_frames")
    FUNCTION = "apply"
    CATEGORY = "yton-nodes/H3"

    def apply(self, positive, latent, vae, previous=None):
        if previous is None:
            return positive, latent, 0
        source = previous["latent"]
        if self.engine == "niko":
            conditioning, trim = upstream("YuanH3NikoMotionContext").apply(
                conditioning=positive, latent=latent, vae=vae,
                context_latent=source, context_length=39, audio_context_length=18)
            result = latent
        else:
            result, trim = upstream("MiniMaxH3GeneratedAVMaskedContext").prepare(
                latent=latent, source_latent=source, context_length=39,
                audio_feather_ticks=8)
            # Keep the user's spatial edit mask outside the protected prefix.
            # Upstream initializes a fresh all-ones future mask; intersect it
            # with Relay's mask so unselected people/background remain fixed.
            if "noise_mask" in latent:
                result["noise_mask"] = result["noise_mask"] * latent["noise_mask"]
            conditioning = positive
        if trim != 39:
            raise ValueError(f"上下文插件返回 {trim} 帧，与规划的 39 帧不一致")
        return conditioning, result, trim


class YuanH3NikoWindowContext(_WindowContext):
    engine = "niko"


class YuanH3MultiRefWindowContext(_WindowContext):
    engine = "multiref"


class YuanH3ContextAppendWindow:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"frames": ("IMAGE",), "latent": ("LATENT",),
            "window": ("H3_RELAY_WINDOW",), "trim_frames": ("INT", {"default": 0})},
            "optional": {"previous": ("H3_RELAY_WINDOW_STATE",)}}
    RETURN_TYPES = ("H3_RELAY_WINDOW_STATE",)
    FUNCTION = "append"
    CATEGORY = "yton-nodes/H3"

    def append(self, frames, latent, window, trim_frames=0, previous=None):
        if trim_frames != window["discarded_overlap"]:
            raise ValueError("上下文裁剪与窗口重叠帧数不一致")
        state, = upstream("H3RelayAppendWindow").append(frames, window, previous=previous)
        # Only the current sampler result travels to the next iteration. The
        # displayed frames are never re-encoded to construct its context.
        state["latent"] = {"samples": latent["samples"].cpu()}
        return (state,)


def shot_context_path(relative):
    from pathlib import Path
    import folder_paths
    root = Path(folder_paths.get_output_directory()).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target.suffix != ".safetensors":
        raise ValueError("人物替换上下文必须位于 ComfyUI output 内")
    return target


class YuanH3ShotInputs:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source": ("IMAGE",), "source_frames": ("INT", {"min": 1}),
                             "context_path": ("STRING", {"default": ""})},
                "optional": {"source_audio": ("AUDIO",), "mask": ("MASK",)}}
    RETURN_TYPES = ("IMAGE", "AUDIO", "MASK", "INT", "INT", "BOOLEAN", "H3_RELAY_WINDOW_STATE", "INT", "INT")
    RETURN_NAMES = ("source", "audio", "mask", "source_frames", "head_trim", "has_context", "previous", "first_frame", "last_frame")
    FUNCTION = "prepare"
    CATEGORY = "yton-nodes/H3"

    @classmethod
    def IS_CHANGED(cls, source, context_path="", **kwargs):
        if not context_path:
            return "first-shot"
        path = shot_context_path(context_path)
        stat = path.stat()
        return f"{path}:{stat.st_size}:{stat.st_mtime_ns}"

    def prepare(self, source, source_frames, context_path="", source_audio=None, mask=None):
        import torch
        import torch.nn.functional as F
        from comfy.nested_tensor import NestedTensor
        # Relay's IMAGE output includes trailing H3 shape padding; its separate
        # source_frames output is the real timeline shared by the saved masks.
        if not 1 <= source_frames <= len(source):
            raise ValueError("真实源视频帧数与预处理画面不一致")
        source = source[:source_frames]
        if mask is not None:
            if mask.ndim != 3 or len(mask) < source_frames or mask.shape[1:] != source.shape[1:3]:
                raise ValueError("人物蒙版与真实源视频的帧数或分辨率不一致")
            mask = mask[:source_frames]
        if source_audio is not None:
            source_audio = dict(source_audio, waveform=source_audio["waveform"][..., :round(source_frames * source_audio["sample_rate"] / 24)])
        previous, tail, prior_audio = None, None, None
        if context_path:
            from safetensors import safe_open
            from safetensors.torch import load_file
            path = shot_context_path(context_path)
            with safe_open(str(path), framework="pt", device="cpu") as handle:
                metadata = handle.metadata() or {}
            if metadata.get("contract") != "yuan-h3-shot-context-v1":
                raise ValueError("所选记录没有完整的片段上下文，请重新生成该记录")
            data = load_file(str(path), device="cpu")
            tail = data["tail_frames"].to(source.device, source.dtype) / 255
            if tail.shape != (39, *source.shape[1:]):
                raise ValueError("上一段上下文与当前分辨率不一致，请保持整条链的分辨率相同")
            previous = {"latent": {"samples": NestedTensor([data["video"], data["audio"]])},
                        "frames": tail.cpu(), "windows": [], "audio": None}
            if "source_audio_tail" in data:
                prior_audio = {"sample_rate": int(metadata["source_audio_rate"]), "waveform": data["source_audio_tail"]}
        prefix = 39 if previous is not None else 0
        # Put shape padding before the delivered footage, so the saved sampler
        # latent ends at the actual final output frame, never at a padded future.
        total = max(56, 5 + 17 * math.ceil((prefix + len(source) - 5) / 17))
        padding = total - prefix - len(source)
        head = prefix + padding
        source = torch.cat(([tail] if tail is not None else []) + [source[:1].expand(padding, -1, -1, -1), source])
        if mask is not None:
            mask = torch.cat([torch.zeros((prefix, *mask.shape[1:]), dtype=mask.dtype, device=mask.device), mask[:1].expand(padding, -1, -1), mask])
        if source_audio is not None:
            rate = int(source_audio["sample_rate"])
            wave = source_audio["waveform"]
            history = torch.zeros((*wave.shape[:-1], round(prefix * rate / 24)), dtype=wave.dtype, device=wave.device)
            if prior_audio is not None:
                import comfy.audio
                history = comfy.audio.resample(prior_audio["waveform"], prior_audio["sample_rate"], rate).to(wave)
                history = F.pad(history, (max(0, round(prefix * rate / 24) - history.shape[-1]), 0))[..., -round(prefix * rate / 24):]
            source_audio = {"sample_rate": rate, "waveform": torch.cat([history, wave.new_zeros((*wave.shape[:-1], round(head * rate / 24) - history.shape[-1])), wave], -1)}
        return source, source_audio, mask, total, head, bool(context_path), previous, head, total - 1


class YuanH3SaveShotContext:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"state": ("H3_RELAY_WINDOW_STATE",), "filename_prefix": ("STRING", {"default": "yuan-director/context"})},
                "optional": {"source_audio": ("AUDIO",)}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "save"
    OUTPUT_NODE = True
    CATEGORY = "yton-nodes/H3"

    def save(self, state, filename_prefix, source_audio=None):
        import os
        import torch
        from pathlib import Path
        from safetensors.torch import save_file
        path = shot_context_path(filename_prefix + ".safetensors")
        last = state["windows"][-1]
        if last["padded_tail_frames"]:
            raise ValueError("上下文末尾含填充帧，不能作为下一片段的真实结束状态")
        video, audio = state["latent"]["samples"].tensors
        tensors = {"video": video.cpu().contiguous(), "audio": audio.cpu().contiguous(),
                   "tail_frames": (state["frames"][-39:].clamp(0, 1) * 255).round().to(dtype=torch.uint8).cpu().contiguous()}
        metadata = {"contract": "yuan-h3-shot-context-v1"}
        if source_audio is not None:
            rate = int(source_audio["sample_rate"])
            end = round(len(state["frames"]) * rate / 24)
            tensors["source_audio_tail"] = source_audio["waveform"][..., end-round(39 * rate / 24):end].cpu().contiguous()
            metadata["source_audio_rate"] = str(rate)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        save_file(tensors, str(temporary), metadata=metadata)
        os.replace(temporary, path)
        import folder_paths
        relative = path.relative_to(Path(folder_paths.get_output_directory()).resolve())
        return {"ui": {"latents": [{"filename": relative.name, "subfolder": relative.parent.as_posix() if relative.parent.as_posix() != '.' else '', "type": "output"}]}, "result": (str(path),)}


NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in (
    YuanH3ContextWindowPlan, YuanH3NikoWindowContext,
    YuanH3MultiRefWindowContext, YuanH3ContextAppendWindow, YuanH3ShotInputs, YuanH3SaveShotContext)}
NODE_DISPLAY_NAME_MAPPINGS = {
    "YuanH3ContextWindowPlan": "H3 上下文窗口规划 · 39 帧",
    "YuanH3NikoWindowContext": "H3 Latent 上下文 · Niko 原版",
    "YuanH3MultiRefWindowContext": "H3 Latent 上下文 · MultiRef",
    "YuanH3ContextAppendWindow": "H3 合并窗口 · 保留原始 Latent",
}
