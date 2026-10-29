"""Grouped H3 node using the SelfLift reference-guide continuation path."""

from .omni_context import context_name
from .omni_runtime import YtonH3OmniGenerate
from .omni_selflift_context import YtonH3LoadSelfLiftContext, YtonH3SaveSelfLiftContext
from .omni_selflift_graph import build_selflift_omni_graph


class YtonH3SelfLiftOmniGenerate(YtonH3OmniGenerate):
    DESCRIPTION = (
        "分段式 H3 全模态生成：沿用原节点的单采/二采、Sigma 和小脸修复，"
        "使用 SelfLift 的 21+1 帧画面引导与尾部音频接续，并在输出端做 ColorTransfer 对齐。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        schema["required"]["latent_path"][1]["default"] = "h3_context/SelfLift无缝接续"
        schema["required"]["latent_path"][1]["tooltip"] = (
            "SelfLift 上下文保存目录；与原版 H3 全模态节点使用独立文件契约。"
        )
        schema["required"]["clip_index"][1]["tooltip"] = (
            "第 1 段不读取上下文；第 N 段读取 SelfLift 的第 N−1 段画面与音频尾部。"
        )
        return schema

    @classmethod
    def IS_CHANGED(cls, latent_path, clip_index, context_path="", **kwargs):
        previous = context_path or (context_name(latent_path, clip_index - 1) if clip_index > 1 else "")
        if not previous:
            return "first-clip"
        return YtonH3LoadSelfLiftContext.IS_CHANGED(previous)

    def generate(self, **inputs):
        return build_selflift_omni_graph(**inputs)


NODE_CLASS_MAPPINGS = {
    "YtonH3SelfLiftOmniGenerate": YtonH3SelfLiftOmniGenerate,
    "YtonH3LoadSelfLiftContext": YtonH3LoadSelfLiftContext,
    "YtonH3SaveSelfLiftContext": YtonH3SaveSelfLiftContext,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "YtonH3SelfLiftOmniGenerate": "H3 全模态生成 · SelfLift 无缝接续",
    "YtonH3LoadSelfLiftContext": "H3 读取 SelfLift 无缝上下文",
    "YtonH3SaveSelfLiftContext": "H3 保存 SelfLift 无缝上下文",
}
