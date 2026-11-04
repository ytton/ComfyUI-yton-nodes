"""A workflow-executed, local GGUF prompt enhancer."""

from ..llama_optimizer_config import DEFAULT_OPTIONS_JSON, parse_options
from ..llama_optimizer_runtime import runtime
from ..prompt_optimizer import build_messages
from ..prompt_optimizer_media import media_content
from ..prompt_optimizer_skill import load_skill
from .prompt_optimizer_node import YtonPromptOptimizer


class YtonLlamaCppOptimizer:
    @classmethod
    def INPUT_TYPES(cls):
        inputs = YtonPromptOptimizer.INPUT_TYPES()
        del inputs["required"]["model_ref"]
        inputs["required"]["model_name"] = ("STRING", {"default": ""})
        inputs["required"]["options_json"] = ("STRING", {"default": DEFAULT_OPTIONS_JSON})
        inputs["required"]["enabled"][1]["tooltip"] = "关闭后原文直通，不读取 Skill、处理媒体或加载本地模型。"
        return inputs

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("优化后的提示词",)
    FUNCTION = "execute"
    INPUT_IS_LIST = True
    CATEGORY = "yton-nodes/提示词"
    DESCRIPTION = "使用本地 llama.cpp GGUF 模型优化提示词；支持 Skill 和参考素材，右下角齿轮设置上下文、采样、思考预算及显存配置。"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def execute(self, prompt, rules, skill_name, enabled, model_name, options_json,
                image=None, audio=None, video=None):
        if not enabled[0]:
            return {"ui": {"optimized_prompt": [prompt[0]]}, "result": (prompt[0],)}
        options = parse_options(options_json[0])
        media = media_content(image, audio, video)
        messages = build_messages(prompt[0], rules[0], media=media, skill=load_skill(skill_name[0]))
        result = runtime.generate(model_name[0], options, messages, has_media=bool(media))
        return {"ui": {"optimized_prompt": [result]}, "result": (result,)}
