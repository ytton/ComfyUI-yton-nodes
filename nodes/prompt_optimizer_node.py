"""Workflow prompt optimization with native media inputs and text output."""

from ..prompt_optimizer import DEFAULT_RULES, get_store, optimize
from ..prompt_optimizer_media import media_content
from ..prompt_optimizer_skill import available_skills, load_skill


class YtonPromptOptimizer:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True, "default": "", "defaultInput": True, "tooltip": "用户提示词；连接文本输入或在节点内填写。"}),
            "rules": ("STRING", {"multiline": True, "default": DEFAULT_RULES, "defaultInput": True, "tooltip": "系统提示词；连接文本输入或在节点内填写。"}),
            "model_ref": ("STRING", {"default": ""}),
            "skill_name": (["", *available_skills()], {"default": "", "tooltip": "选择插件 skills 目录中的多文件 Skill，执行时自动读取完整文本包。"}),
            "enabled": ("BOOLEAN", {"default": True, "label_on": "增强提示词", "label_off": "原文直通", "tooltip": "关闭后直接输出用户提示词，跳过 Skill、媒体处理和模型 API 请求。"}),
        }, "optional": {
            "image": ("IMAGE", {"forceInput": True, "tooltip": "图片列表，可直接连接媒体加载器的 image 输出。"}),
            "audio": ("AUDIO", {"forceInput": True, "tooltip": "音频列表，模型需支持音频理解。"}),
            "video": ("VIDEO", {"forceInput": True, "tooltip": "视频列表，每段均匀抽取最多 12 帧并携带原音轨。"}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("优化后的提示词",)
    FUNCTION = "execute"
    INPUT_IS_LIST = True
    CATEGORY = "yton-nodes/提示词"
    DESCRIPTION = "通过 OpenAI 兼容服务结合图片、音频、视频列表优化提示词。用户与系统提示词均支持连线；右下角齿轮配置共享服务商和模型。"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # The shared provider/default model can change independently of widgets.
        return float("nan")

    def execute(self, prompt, rules, model_ref, skill_name, enabled, image=None, audio=None, video=None):
        if not enabled[0]:
            return {"ui": {"optimized_prompt": [prompt[0]]}, "result": (prompt[0],)}
        result = optimize(get_store(), prompt[0], rules[0], model_ref[0],
                          media=media_content(image, audio, video),
                          skill=load_skill(skill_name[0]))
        return {"ui": {"optimized_prompt": [result["text"]]},
                "result": (result["text"],)}
