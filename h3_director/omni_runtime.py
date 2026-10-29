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
    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("length", "trim_frames")
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
        length = 5 + 17 * max(0, math.ceil((target + context_frames[0] - 5) / 17))
        if length > 3592:
            raise ValueError("复刻视频加上上下文后超出H3最大采样帧数3592，请先拆分视频。")
        # Crop the alignment surplus at the head so the delivered tail still
        # matches the full sampler latent saved for the next clip.
        return length, length - target


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
                "tooltip": "仅普通模式有效。续段自动补上画面上下文；按24fps及H3的5+17×N帧就近对齐，实际成片时长会略有差异。"}),
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
                "tooltip": "小脸使用此降噪强度，大脸自动减弱至35%；参考图沿用生成输入，保持人物身份。"}),
            "face_detector": ("STRING", {"default": "bbox\\face_yolov8m.pt"}),
            "face_reverse": ("BOOLEAN", {"default": False, "tooltip": "倒序修脸，贴回后恢复正常播放顺序。"}),
        }, "optional": {
            "image": ("IMAGE", {"rawLink": True}),
            "video": ("VIDEO", {"rawLink": True}),
            "audio": ("AUDIO", {"rawLink": True}),
            "sigmas": ("SIGMAS", {
                "tooltip": "连接后用于主采样，主采样步数、调度器和降噪失效。"}),
            "second_sigmas": ("SIGMAS", {"tooltip": "仅用于二采，优先于二采Sigma文本。"}),
            "context_path": ("STRING", {"default": "", "tooltip": "指定已采用片段的上下文文件；填写后优先于按序号读取上一段，可用于工作台重抽与分支。"}),
            "second_model_loader": ("FAST_MODEL_LOADER", {"rawLink": True, "tooltip": "可选的二采模型加载器；不接时使用主模型。"}),
            "face_model_loader": ("FAST_MODEL_LOADER", {"rawLink": True, "tooltip": "可选的修脸模型加载器；不接时使用主模型。"}),
        }}

    RETURN_TYPES = ("VIDEO", "LATENT", "STRING")
    RETURN_NAMES = ("video", "av_latent", "latent_path")
    FUNCTION = "generate"
    CATEGORY = "yton-nodes/MiniMax H3"
    OUTPUT_NODE = True
    DESCRIPTION = "分段式H3全模态生成：单采或二采，22帧latent尾部注入与锁定，支持逐人小脸修复。每次输出一个新片段及完整上下文文件。"

    @classmethod
    def IS_CHANGED(cls, latent_path, clip_index, context_path="", **kwargs):
        previous = context_path or (context_name(latent_path, clip_index - 1) if clip_index > 1 else "")
        return YtonH3LoadOmniContext.IS_CHANGED(previous) if previous else "first-clip"

    def generate(self, **inputs):
        return build_omni_graph(**inputs)


NODE_CLASS_MAPPINGS = {"YtonH3OmniGenerate": YtonH3OmniGenerate, "YtonH3ReplicaPlan": YtonH3ReplicaPlan}
NODE_DISPLAY_NAME_MAPPINGS = {"YtonH3OmniGenerate": "H3 全模态生成", "YtonH3ReplicaPlan": "H3 复刻时长规划"}
