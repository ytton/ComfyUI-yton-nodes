"""H3 全模态生成的视频上下文入口。"""

from .omni_runtime import YtonH3OmniGenerate
from .omni_video_context_graph import build_video_context_graph


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
        schema["required"]["enable_context"] = ("BOOLEAN", {
            "default": False,
            "tooltip": "仅开启并接入上一段视频时，才提取尾部 22 帧与音频接续；关闭时忽略上一段视频，按独立片段生成。",
        })
        schema["required"]["clip_index"][1]["tooltip"] = (
            "普通模式按序号从源视频截取当前片段；开启上下文并接入上一段视频后，自动增加并裁除 22 帧上下文。"
        )
        schema["optional"]["previous_video"] = ("VIDEO", {
            "rawLink": True,
            "tooltip": "可选。接上一段生成的视频，或用加载视频节点读取已有成片；仅在启用上下文时提取尾部画面与音频。独立生成时可留空。",
        })
        return schema

    RETURN_TYPES = ("VIDEO", "LATENT")
    RETURN_NAMES = ("video", "av_latent")
    FUNCTION = "generate"
    CATEGORY = "yton-nodes/MiniMax H3"
    OUTPUT_NODE = True
    DESCRIPTION = (
        "支持独立的全模态生成，上下文默认关闭，上一段视频为可选输入。"
        "启用上下文并传入上一段视频后，提取尾部 22 帧与音频进行接续。前 21 帧加微量噪声，"
        "末帧保持原样；本段生成后裁除重叠帧，并参照上一段末帧对齐颜色。"
        "支持单采、二采、自定义 Sigma 和小脸修复。"
    )

    def generate(self, **inputs):
        return build_video_context_graph(**inputs)


NODE_CLASS_MAPPINGS = {
    "YtonH3VideoContextOmniGenerate": YtonH3VideoContextOmniGenerate,
    "YtonH3VideoTail": YtonH3VideoTail,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "YtonH3VideoContextOmniGenerate": "H3 全模态生成 · 视频上下文",
    "YtonH3VideoTail": "H3 提取视频尾部",
}
