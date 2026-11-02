"""H3 全模态生成的视频上下文入口。"""

import os

import comfy.samplers
import folder_paths

from .omni_video_context_graph import build_video_context_graph
from .omni_sampling import FILM_MODEL, UPSCALE_MODEL

if "h3_latent_upscalers" not in folder_paths.folder_names_and_paths:
    folder_paths.add_model_folder_path("h3_latent_upscalers", os.path.join(folder_paths.models_dir, "h3_latent_upscalers"))
folder_paths.folder_names_and_paths["h3_latent_upscalers"][1].add(".safetensors")


class YtonH3VideoTail:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO",)}}

    RETURN_TYPES = ("IMAGE", "AUDIO")
    FUNCTION = "extract"
    CATEGORY = "yton-nodes/MiniMax H3/内部"
    DEV_ONLY = True

    def extract(self, video):
        components = video.get_components()
        frames = components.images
        if len(frames) < 22:
            raise ValueError("上一段视频至少需要 22 帧，才能提取完整接续上下文。")
        # 直接取像素与音频切片，保留生成节点传来的视频原始精度。
        audio = components.audio
        if audio is not None:
            fps = video.get_frame_rate()
            sample_rate = audio["sample_rate"]
            start = round((len(frames) - 22) * sample_rate / fps)
            end = round(len(frames) * sample_rate / fps)
            audio = {"waveform": audio["waveform"][..., start:end].clone(), "sample_rate": sample_rate}
        return frames[-22:].clone(), audio


class H3OmniGenerate:
    SAMPLING_PLAN = "tr"

    @classmethod
    def INPUT_TYPES(cls):
        required = {
            "model": ("MODEL", {"rawLink": True, "tooltip": "H3 主模型，可连接标准模型加载器及 LoRA 加载器的 MODEL 输出。"}),
            "clip": ("CLIP", {"rawLink": True, "tooltip": "H3 文本编码器，连接 CLIP 输出。"}),
            "vae": ("VAE", {"rawLink": True,
                "tooltip": "H3 视频 VAE，用于参考编码、上下文、SelfLift 校正、修脸和最终视频解码。"}),
            "audio_vae": ("VAE", {"rawLink": True, "tooltip": "H3 音频 VAE，用于音频参考编码和最终音频解码。"}),
            "prompt": ("STRING", {"default": "", "multiline": True}),
            "width": ("INT", {"default": 1344, "min": 32, "max": 16384, "step": 32}),
            "height": ("INT", {"default": 768, "min": 32, "max": 16384, "step": 32}),
            "mode": (["普通模式", "复刻模式"], {"default": "普通模式",
                "tooltip": "普通模式使用填写时长；复刻模式按第一个视频的实际时长生成。"}),
            "duration": ("FLOAT", {"default": 5.0, "min": 0.21, "max": 149.66, "step": 0.1,
                "tooltip": "普通模式目标时长。开启自动增加上下文时长时，填写新增内容时长；关闭时，填写包含上下文的片段总时长。"}),
            "ref_image_size": (["match", "max"], {"default": "match"}),
            "sampling_mode": (["单采", "二采"], {"default": "二采",
                "tooltip": "单采直接按最终宽高生成；二采采用此节点对应的升分辨率方案。"}),
            "steps": ("INT", {"default": 4, "min": 1, "max": 1000}),
            "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"default": "euler"}),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"default": "simple"}),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "face_refine": ("BOOLEAN", {"default": False}),
            "face_count": ("INT", {"default": 1, "min": 1, "max": 64}),
            "face_reverse": ("BOOLEAN", {"default": False}),
        }
        schema = {"required": required, "optional": {
            "image": ("IMAGE", {"lazy": True, "tooltip": "可选图片参考；空输出视为未提供。"}),
            "video": ("VIDEO", {"lazy": True, "tooltip": "可选视频参考，完整送入 H3 参考解析。普通模式使用填写时长，复刻模式取第一个视频的时长。"}),
            "audio": ("AUDIO", {"lazy": True, "tooltip": "可选音频参考。"}),
            "sigmas": ("SIGMAS", {"tooltip": "自定义主采时间表；连接后替代主采步数、调度器与降噪。SelfLift 使用同一条完整时间表。"}),
            "second_model": ("MODEL", {"rawLink": True, "tooltip": "可选的高分辨率阶段模型；未接时使用主模型。"}),
            "face_model": ("MODEL", {"rawLink": True, "tooltip": "可选的修脸模型；未接时使用主模型。"}),
        }}
        required["second_sampler"] = (comfy.samplers.KSampler.SAMPLERS, {"default": "euler"})
        required["film_method"] = (["learned model", "nearest-exact", "nearest", "bilinear", "bicubic", "area", "bislerp"], {
            "default": "learned model",
            "tooltip": "默认 learned model 使用 Film 模型；其他选项使用对应的潜空间插值。放大倍率固定为 2×。",
        })
        film_models = folder_paths.get_filename_list("h3_latent_upscalers")
        required["film_model"] = ([FILM_MODEL, *[name for name in film_models if name != FILM_MODEL]], {"default": FILM_MODEL,
            "tooltip": "learned model 使用的 Film 2× 模型，放在 models/h3_latent_upscalers；插值方式不使用此模型。"})
        required["film_audio_denoise"] = ("FLOAT", {
            "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05, "round": False,
            "tooltip": "0 保留首采音频，1 允许二采重新生成音频。当前超分插件将小于 0.5 视为锁定，其余视为完整重做。",
        })
        required["film_noise_resample"] = (["independent", "upscale"], {
            "default": "independent",
            "tooltip": "传给超分插件的 noise_resample。当前插件的两种选项均使用高分辨率独立噪声，切换不会改变结果。",
        })
        required["film_match_stats"] = ("FLOAT", {
            "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05, "round": False,
            "tooltip": "插值放大时，匹配首采潜变量各通道均值与标准差的强度。learned model 会忽略此值。",
        })
        for name in ("width", "height"):
            required[name][1]["tooltip"] = "最终输出尺寸，按 32 像素对齐；Film 2× 要求为 64 的倍数，例如 1920×1088。"
        required["second_sigma_values"] = ("STRING,SIGMAS", {
            "default": "", "widgetType": "STRING", "lazy": True,
            "tooltip": "留空自动生成交错去网格曲线；手填或连接 STRING / SIGMAS 时覆盖自动调度。Film 加噪和二采始终共用同一时间表。",
        })
        required["second_steps"] = ("INT", {
            "default": 4, "min": 1, "max": 100,
            "tooltip": "自动二采的实际步数，默认 4 步；增加步数可给纹理更多细化时间。手填或连线 Sigma 时不使用。",
        })
        required["second_sigma_start"] = ("FLOAT", {
            "default": 0.4, "min": 0.01, "max": 1.0, "step": 0.01, "round": False,
            "tooltip": "实际起始 Sigma，直接控制重绘力度，不受主模型 Sigma Shift 的调度换算影响。建议先试 0.4；网格残留可小幅调高，内容变化过大则调低。0.25–0.45 是作者建议的试验范围。",
        })
        required["second_rho"] = ("FLOAT", {
            "default": 7.0, "min": 0.5, "max": 30.0, "step": 0.5, "round": False,
            "tooltip": "Karras 曲线强度。固定起点与步数，较高值将更多降噪放在前几步；默认 7。曲线末端为 0.01，最后归零。手填或连线 Sigma 时不使用。",
        })
        required["second_sampler"][1]["default"] = "euler"
        required["second_ff_chunks"] = (["沿用模型", "4", "8", "16", "32", "64"], {
            "default": "8",
            "tooltip": "二采的前馈计算分块，默认 8 块以降低长片段显存峰值；显存仍不足可选 16 或 32。仅分批计算同一组 token，不裁切视频、不改变采样步数。选择沿用模型可保留外部模型的分块设置。",
        })
        schema["optional"]["face_sigmas"] = ("STRING,SIGMAS", {
            "widgetType": "STRING", "default": "", "lazy": True,
            "tooltip": "可手填时间表或连接 STRING / SIGMAS；留空使用内部 4 步、降噪 0.4。检测、种子和大小脸倍率由节点内部配置。关闭修脸时不执行。",
        })
        schema["optional"]["second_model"][1]["tooltip"] = (
            "Film 2× 的二采模型；可接串好 LoRA 的 MODEL。"
        )
        schema["required"]["enable_context"] = ("BOOLEAN", {
            "default": False,
            "tooltip": "仅开启并接入上一段视频时，才提取尾部 22 帧与音频接续；关闭时忽略上一段视频，按独立片段生成。",
        })
        required["context_auto_extend"] = ("BOOLEAN", {
            "default": True,
            "tooltip": "开启：在目标时长或参考视频长度上额外增加 22 帧上下文。关闭：输入长度已包含上下文，不再额外增加；仍保留上下文引导，并裁掉前 22 帧。配合编辑器的含上下文片段时关闭。没有上一段视频时不影响长度。尾部仍按 H3 帧数规则补齐并裁除。",
        })
        required["context_noise_strength"] = ("FLOAT", {
            "default": 0.1, "min": 0.0, "max": 1.0, "step": 0.01, "round": False,
            "tooltip": "上一段尾部 22 帧中，前 21 帧的加噪强度；0 不加噪，最后一帧始终保持原样。仅在启用上下文且传入上一段视频时使用。",
        })
        required["context_color_strength"] = ("FLOAT", {
            "default": 0.75, "min": 0.0, "max": 1.0, "step": 0.01, "round": False,
            "tooltip": "本段裁除上下文后，参照上一段末帧匹配整段颜色的强度；0 关闭调色，1 完全应用颜色匹配。仅在启用上下文且传入上一段视频时使用。",
        })
        schema["optional"]["previous_video"] = ("VIDEO", {
            "lazy": True,
            "tooltip": "可选。接上一段生成的视频，或用加载视频节点读取已有成片；仅在启用上下文时提取尾部画面与音频。独立生成时可留空。",
        })
        if cls.SAMPLING_PLAN != "tr":
            for name in tuple(required):
                if name.startswith("film_"):
                    del required[name]
            for name in ("width", "height"):
                required[name][1]["tooltip"] = "最终输出尺寸，按 32 像素对齐，例如 1920×1088。"
            required["first_pass_scale"] = ("FLOAT", {
                "default": 0.5 if cls.SAMPLING_PLAN == "selflift" else 0.625,
                "min": 0.25, "max": 1.0, "step": 0.025,
                "tooltip": "低分辨率阶段相对最终宽高的比例。传统二采按 32 对齐；SelfLift 由采样器计算低分辨率画布。",
            })
            upscalers = folder_paths.get_filename_list("latent_upscale_models")
            required["upscale_model"] = ([UPSCALE_MODEL, *[name for name in upscalers if name != UPSCALE_MODEL]], {
                "default": UPSCALE_MODEL, "tooltip": "3D latent 放大模型，位于 models/latent_upscale_models。",
            })
            schema["optional"]["second_model"][1]["tooltip"] = "可选的高分辨率阶段模型；未接时使用主模型。"
        if cls.SAMPLING_PLAN == "traditional":
            required["second_sampler"][1]["default"] = "sa_solver"
            required["second_sigma_values"][1].update(default="0.631578922, 0.3158, 0",
                tooltip="传统二采时间表；手填或连线覆盖自动调度，留空使用下方 Karras 配置。")
        if cls.SAMPLING_PLAN == "selflift":
            for name in ("second_sampler", "second_sigma_values", "second_steps", "second_sigma_start", "second_rho"):
                del required[name]
            required["sampler_name"] = (["euler"], {"default": "euler",
                "tooltip": "SelfLift 固定标准 Euler；低分与高分阶段共用主采完整 Sigma，不额外追加二采步数。"})
            required["upscale_model"][0].append("none")
            required["selflift_transition_step"] = ("INT", {"default": 2, "min": 1, "max": 999,
                "tooltip": "低分辨率阶段执行的步数；必须小于完整时间表的总步数。默认 4 步时低分 2 步、高分 2 步。"})
            required["selflift_rho"] = ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                "tooltip": "VAE 校正范围。默认 0，使用所选 latent 超分模型；超分选择 none 时必须大于 0。"})
            required["selflift_w_min"] = ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05})
            required["selflift_w_max"] = ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05})
            required["selflift_highres_tiling"] = ("BOOLEAN", {"default": False})
            required["selflift_highres_tiles"] = (["auto", "2", "4", "8"], {"default": "auto"})
        schema["hidden"] = {"dynprompt": "DYNPROMPT", "unique_id": "UNIQUE_ID"}
        return schema

    INPUT_IS_LIST = True
    RETURN_TYPES = ("VIDEO", "LATENT")
    RETURN_NAMES = ("video", "av_latent")
    FUNCTION = "generate"
    CATEGORY = "yton-nodes/MiniMax H3"
    OUTPUT_NODE = True
    DESCRIPTION = (
        "支持独立的全模态生成，上下文默认关闭，上一段视频为可选输入。"
        "启用上下文并传入上一段视频后，提取尾部 22 帧与音频进行接续。前 21 帧加微量噪声，"
        "末帧保持原样；本段生成后裁除重叠帧，并参照上一段末帧对齐颜色。"
        "二采固定使用 Film 2×，首采宽高为最终尺寸的一半；支持单采、自定义 Sigma 和小脸修复。"
    )

    def check_lazy_status(self, enable_context, **inputs):
        media = ("image", "video", "audio") + (("previous_video",) if enable_context[0] else ())
        if inputs["sampling_mode"][0] == "二采" and self.SAMPLING_PLAN != "selflift":
            media += ("second_sigma_values",)
        if inputs["face_refine"][0]:
            media += ("face_sigmas",)
        return [name for name in media if name in inputs
                and not any(item is not None for item in inputs[name])]

    def generate(self, dynprompt, unique_id, **inputs):
        links = dynprompt[0].get_node(unique_id[0])["inputs"]
        values = {}
        for name, items in inputs.items():
            if name in ("image", "video", "audio", "previous_video"):
                if name == "previous_video" and not inputs["enable_context"][0]:
                    continue
                # A connected media-loader socket can still yield an empty list.
                # Inspect its values before passing its original link to the graph.
                if any(item is not None for item in items):
                    values[name] = links[name]
            else:
                values[name] = items[0]
        return build_video_context_graph(sampling_plan=self.SAMPLING_PLAN, **values)


class YtonH3VideoContextOmniGenerate(H3OmniGenerate):
    SAMPLING_PLAN = "tr"


class YtonH3SelfLiftOmniGenerate(H3OmniGenerate):
    SAMPLING_PLAN = "selflift"
    DESCRIPTION = "全模态生成与可选视频上下文。SelfLift 共用一条完整 Euler 时间表，从低分辨率升到最终宽高；支持单采与小脸修复。"


class YtonH3TraditionalOmniGenerate(H3OmniGenerate):
    SAMPLING_PLAN = "traditional"
    DESCRIPTION = "全模态生成与可选视频上下文。传统二采先低分辨率生成，3D latent 超分到最终宽高，再独立采样；支持单采与小脸修复。"


NODE_CLASS_MAPPINGS = {
    "YtonH3VideoContextOmniGenerate": YtonH3VideoContextOmniGenerate,
    "YtonH3SelfLiftOmniGenerate": YtonH3SelfLiftOmniGenerate,
    "YtonH3TraditionalOmniGenerate": YtonH3TraditionalOmniGenerate,
    "YtonH3VideoTail": YtonH3VideoTail,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "YtonH3VideoContextOmniGenerate": "H3 全模态生成 · TR",
    "YtonH3SelfLiftOmniGenerate": "H3 全模态生成 · SelfLift",
    "YtonH3TraditionalOmniGenerate": "H3 全模态生成",
    "YtonH3VideoTail": "H3 提取视频尾部",
}
