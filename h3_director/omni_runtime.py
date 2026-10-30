"""A grouped H3 generation node, expanded by ComfyUI into existing nodes."""
import math

import comfy.samplers
import folder_paths

from .omni_graph import build_omni_graph
from .omni_context import context_name, YtonH3LoadOmniContext


class YtonH3ReplicaPlan:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video": ("VIDEO",),
            "context_frames": ("INT", {"default": 0, "min": 0, "max": 56}),
        }}

    INPUT_IS_LIST = True
    RETURN_TYPES = ("INT", "INT", "INT")
    RETURN_NAMES = ("length", "head_trim_frames", "tail_trim_frames")
    FUNCTION = "plan"
    CATEGORY = "yton-nodes/MiniMax H3"
    DESCRIPTION = "全模态复刻模式内部时长规划：只读取第一个视频，补足上下文与H3帧格。"

    def plan(self, video, context_frames):
        if not video or video[0] is None:
            raise ValueError("复刻模式需要传入至少一个视频，时长取第一个视频。")
        duration = float(video[0].get_duration())
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("复刻模式的第一个视频时长无效。")
        target = max(1, math.floor(duration * 24 + 0.5))
        overlap = int(context_frames[0])
        length = 5 + 17 * max(0, math.ceil((target + overlap - 5) / 17))
        if length > 3592:
            raise ValueError("复刻视频加上上下文后超出H3最大采样帧数3592，请先拆分视频。")
        # The context prefix is removed from the head. H3 frame-grid surplus
        # belongs at the tail; removing it from the head would shift the
        # visible source timeline and create a discontinuity at the seam.
        return length, overlap, length - target - overlap


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


class YtonH3OmniGenerate:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model_loader": ("FAST_MODEL_LOADER", {"rawLink": True}),
            "prompt": ("STRING", {"default": "", "multiline": True}),
            "width": ("INT", {"default": 1344, "min": 32, "max": 16384, "step": 32}),
            "height": ("INT", {"default": 768, "min": 32, "max": 16384, "step": 32}),
            "mode": (["普通模式", "复刻模式"], {"default": "普通模式",
                "tooltip": "普通模式使用填写的时长；复刻模式忽略填写时长，仅按第一个传入视频决定成片时长，并自动补足上下文。"}),
            "duration": ("FLOAT", {"default": 5.0, "min": 0.21, "max": 149.66, "step": 0.1,
                "tooltip": "仅普通模式有效。节点按24fps计算可见帧，续段自动补22帧上下文并在输出端裁回填写的时长。"}),
            "ref_image_size": (["match", "max"], {"default": "match"}),
            "sampling_mode": (["单采", "二采"], {"default": "单采",
                "tooltip": "单采直接按目标分辨率生成；二采先低分生成、潜空间放大，再进行第二次采样。小脸修复是独立的可选局部处理。"}),
            "steps": ("INT", {"default": 4, "min": 1, "max": 1000,
                "tooltip": "主采样步数；接入主采样 Sigma 后失效。"}),
            "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"default": "euler"}),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"default": "simple"}),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "latent_path": ("STRING", {"default": "h3_context/全能参考"}),
            "clip_index": ("INT", {"default": 1, "min": 1, "max": 9999,
                "tooltip": "第1段不读取上下文；第N段读取N−1，重抽覆盖当前段的 latent。"}),
            "first_pass_scale": ("FLOAT", {"default": 0.625, "min": 0.125, "max": 1.0, "step": 0.025,
                "tooltip": "仅二采有效。主采样宽高相对最终分辨率的比例，按32像素对齐；同一接续链保持一致。"}),
            "upscale_model": (folder_paths.get_filename_list("latent_upscale_models"),
                {"default": "minimax_h3_latent_upscaler_3d_fp16.safetensors"}),
            "second_sampler": (comfy.samplers.KSampler.SAMPLERS, {"default": "sa_solver"}),
            "second_sigma_values": ("STRING", {"default": "0.631578922, 0.3158, 0.0",
                "tooltip": "二采的独立时间表，默认采用1029工作流的两步Sigma；接入二采Sigma插口后失效。"}),
            "face_refine": ("BOOLEAN", {"default": False, "tooltip": "逐人追踪小脸，放大局部采样后贴回；关闭时不执行任何修脸节点。"}),
            "face_count": ("INT", {"default": 1, "min": 1, "max": 64}),
            "face_steps": ("INT", {"default": 4, "min": 1, "max": 1000}),
            "face_denoise": ("FLOAT", {"default": 0.4, "min": 0.0, "max": 1.0, "step": 0.01,
                "tooltip": "修脸调度器的降噪强度；接入修脸 Sigma 后失效。"}),
            "face_large_strength": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.05,
                "tooltip": "大脸相对小脸的降噪倍率。1029 原流程为 1，即大小脸使用相同强度。"}),
            "face_detector": ("STRING", {"default": "bbox\\face_yolov8m.pt"}),
            "face_fallback_detector": ("STRING", {"default": "none",
                "tooltip": "检测不到脸时的人体检测模型；1029 使用 segm\\person_yolov8m-seg.pt。"}),
            "face_seed": ("INT", {"default": 42, "min": 0, "max": 0xffffffffffffffff}),
            "face_reverse": ("BOOLEAN", {"default": False, "tooltip": "倒序修脸，贴回后恢复正常播放顺序。"}),
        }, "optional": {
            "image": ("IMAGE", {"lazy": True, "tooltip": "可选，人物或风格参考图；空输出视为未提供。"}),
            "video": ("VIDEO", {"lazy": True,
                "tooltip": "普通模式接完整源视频，节点按片段序号和时长自动截取；复刻模式接已经准备好的当前片段。"}),
            "audio": ("AUDIO", {"lazy": True, "tooltip": "没有视频输入时使用的独立音频参考；普通模式接源视频后由节点自动使用其音轨。"}),
            "sigmas": ("SIGMAS", {
                "tooltip": "连接后用于主采样，主采样步数、调度器和降噪失效。"}),
            "second_sigmas": ("SIGMAS", {"tooltip": "仅用于二采，优先于二采Sigma文本。"}),
            "face_sigmas": ("SIGMAS", {"rawLink": True,
                "tooltip": "仅用于修脸，接入后替代修脸步数与降噪。1029 使用 0.615, 0。"}),
            "context_path": ("STRING", {"default": "", "tooltip": "指定已采用片段的上下文文件；填写后优先于按序号读取上一段，可用于工作台重抽与分支。"}),
            "second_model": ("MODEL", {"rawLink": True, "tooltip": "可选的二采模型；直接接模型或串好 LoRA 的 MODEL。"}),
            "face_model": ("MODEL", {"rawLink": True, "tooltip": "可选的修脸模型；直接接模型或串好 LoRA 的 MODEL。"}),
        }, "hidden": {"dynprompt": "DYNPROMPT", "unique_id": "UNIQUE_ID"}}

    INPUT_IS_LIST = True
    RETURN_TYPES = ("VIDEO", "LATENT", "STRING")
    RETURN_NAMES = ("video", "av_latent", "latent_path")
    FUNCTION = "generate"
    CATEGORY = "yton-nodes/MiniMax H3"
    OUTPUT_NODE = True
    DESCRIPTION = "分段式H3全模态生成：单采或二采，22帧latent尾部注入与锁定，支持逐人小脸修复。每次输出一个新片段及完整上下文文件。"

    @classmethod
    def IS_CHANGED(cls, latent_path, clip_index, context_path=None, **kwargs):
        previous = context_path[0] if context_path else ""
        previous = previous or (context_name(latent_path[0], clip_index[0] - 1) if clip_index[0] > 1 else "")
        return YtonH3LoadOmniContext.IS_CHANGED(previous) if previous else "first-clip"

    def check_lazy_status(self, **inputs):
        return [name for name in ("image", "video", "audio") if name in inputs
                and not any(item is not None for item in inputs[name])]

    def generate(self, dynprompt, unique_id, **inputs):
        links = dynprompt[0].get_node(unique_id[0])["inputs"]
        values = {}
        for name, items in inputs.items():
            if name in ("image", "video", "audio"):
                if any(item is not None for item in items):
                    values[name] = links[name]
            else:
                values[name] = items[0]
        return build_omni_graph(**values)


NODE_CLASS_MAPPINGS = {"YtonH3OmniGenerate": YtonH3OmniGenerate,
                       "YtonH3ReplicaPlan": YtonH3ReplicaPlan,
                       "YtonH3SegmentPlan": YtonH3SegmentPlan,
                       "YtonH3SegmentTrim": YtonH3SegmentTrim}
NODE_DISPLAY_NAME_MAPPINGS = {"YtonH3OmniGenerate": "H3 全模态生成",
                              "YtonH3ReplicaPlan": "H3 复刻时长规划",
                              "YtonH3SegmentPlan": "H3 分段时长规划",
                              "YtonH3SegmentTrim": "H3 分段头尾裁切"}
