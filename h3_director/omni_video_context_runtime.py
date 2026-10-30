"""H3 全模态生成的视频上下文入口。"""

from .omni_runtime import YtonH3OmniGenerate
from .omni_video_context_graph import build_video_context_graph
from .omni_sampling import FILM_MODEL, SAMPLING_PLANS, SELFLIFT, TRADITIONAL


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
        required = schema["required"]
        required["sampling_plan"] = (list(SAMPLING_PLANS), {
            "default": TRADITIONAL,
            "tooltip": "三种方案都把节点宽高作为最终尺寸。传统二采先完成低分首采再放大；SelfLift 在同一时间表内升分；Film 固定 2×。",
        })
        required["film_model"] = ([FILM_MODEL], {"default": FILM_MODEL,
            "tooltip": "Film 2× 专用模型，放在 models/h3_latent_upscalers；与传统 3D/LMS 超分模型分开使用。"})
        required["selflift_transition_step"] = ("INT", {"default": 2, "min": 1, "max": 999,
            "tooltip": "SelfLift 低分阶段的采样步数；必须小于完整 Sigma 时间表的总步数。默认 4 步时间表中低分 2 步、高分 2 步。"})
        required["selflift_rho"] = ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
            "tooltip": "SelfLift 像素/VAE 校正比例。0 只使用潜空间超分，跳过额外 VAE 往返。"})
        required["selflift_highres_tiling"] = ("BOOLEAN", {"default": False,
            "tooltip": "SelfLift 高分阶段启用空间分块，降低显存占用。"})
        required["first_pass_scale"][1]["tooltip"] = (
            "相对最终宽高的首采比例。传统二采可调 0.125～1；SelfLift 可调 0.25～1；Film 固定 0.5，忽略传入比例。"
        )
        for name in ("width", "height"):
            required[name][1]["tooltip"] = "最终输出尺寸，按 32 像素对齐；Film 2× 要求为 64 的倍数，例如 1920×1088。"
        required["second_sigma_values"][1]["tooltip"] = (
            "传统二采和 Film 的二采时间表；接入二采 Sigma 后由连线决定。SelfLift 仅使用主采样的完整时间表。"
        )
        schema["optional"]["second_sigmas"][1].update(lazy=True,
            tooltip="仅传统二采和 Film 有效，优先于二采 Sigma 文本；SelfLift 忽略此输入，使用主采样的完整 Sigma。")
        schema["optional"]["second_model"][1]["tooltip"] = (
            "传统 / Film 的二采模型，或 SelfLift 的高分阶段模型；可接串好 LoRA 的 MODEL。"
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
        "支持单采、传统二采、SelfLift、Film 2×、自定义 Sigma 和小脸修复；宽高统一为最终尺寸。"
    )

    def check_lazy_status(self, enable_context, **inputs):
        media = ("image", "video", "audio") + (("previous_video",) if enable_context[0] else ())
        if inputs["sampling_mode"][0] == "二采" and inputs["sampling_plan"][0] != SELFLIFT:
            media += ("second_sigmas",)
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
