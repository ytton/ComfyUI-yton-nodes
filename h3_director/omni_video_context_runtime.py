"""H3 全模态生成的视频上下文入口。"""

import os

import folder_paths

from .omni_runtime import YtonH3OmniGenerate
from .omni_video_context_graph import build_video_context_graph
from .omni_sampling import FILM_MODEL

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


class YtonH3VideoContextOmniGenerate:
    @classmethod
    def INPUT_TYPES(cls):
        schema = YtonH3OmniGenerate.INPUT_TYPES()
        del schema["required"]["latent_path"]
        del schema["optional"]["context_path"]
        del schema["optional"]["second_sigmas"]
        required = schema["required"]
        del required["first_pass_scale"]
        del required["upscale_model"]
        required["sampling_mode"][1].update(default="二采",
            tooltip="二采固定使用 Film 2×：半尺寸首采、潜空间放大两倍，再进行二采。单采直接按最终宽高生成。")
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
            **required["second_sigma_values"][1], "widgetType": "STRING", "lazy": True,
            "tooltip": "填写二采时间表，或在此控件连接 STRING / SIGMAS。Film 加噪与二采共用该时间表；单采时不执行。",
        })
        schema["optional"]["face_sigmas"] = ("STRING,SIGMAS", {
            "widgetType": "STRING", "default": "", "lazy": True,
            "tooltip": "留空使用修脸步数和降噪；也可填写时间表或在此控件连接 STRING / SIGMAS。关闭修脸时不执行。",
        })
        schema["optional"]["second_model"][1]["tooltip"] = (
            "Film 2× 的二采模型；可接串好 LoRA 的 MODEL。"
        )
        schema["required"]["enable_context"] = ("BOOLEAN", {
            "default": False,
            "tooltip": "仅开启并接入上一段视频时，才提取尾部 22 帧与音频接续；关闭时忽略上一段视频，按独立片段生成。",
        })
        schema["required"]["clip_index"][1]["tooltip"] = (
            "普通模式按序号从源视频截取当前片段；开启上下文并接入上一段视频后，自动增加并裁除 22 帧上下文。"
        )
        schema["optional"]["previous_video"] = ("VIDEO", {
            "lazy": True,
            "tooltip": "可选。接上一段生成的视频，或用加载视频节点读取已有成片；仅在启用上下文时提取尾部画面与音频。独立生成时可留空。",
        })
        for name in ("image", "video", "audio"):
            options = schema["optional"][name][1]
            del options["rawLink"]
            options["lazy"] = True
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
        if inputs["sampling_mode"][0] == "二采":
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
        return build_video_context_graph(**values)


NODE_CLASS_MAPPINGS = {
    "YtonH3VideoContextOmniGenerate": YtonH3VideoContextOmniGenerate,
    "YtonH3VideoTail": YtonH3VideoTail,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "YtonH3VideoContextOmniGenerate": "H3 全模态生成 · 视频上下文",
    "YtonH3VideoTail": "H3 提取视频尾部",
}
