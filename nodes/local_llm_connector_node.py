"""Workflow-owned local GGUF settings with the shared task LLM socket."""

from comfy_api.latest import io

from ..llama_optimizer_config import DEFAULT_OPTIONS_JSON, parse_options
from ..local_llm_connection import LocalLLMConnection


class YtonLocalLLMConnector(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="YtonLocalLLMConnector", display_name="LLM 本地模型连接器", category="yton-nodes/AI",
            description="使用本地 llama.cpp GGUF 模型，为人物替换等任务提供文本和多模态推理。模型与采样设置随工作流保存，任务节点提供提示词和 Skill。",
            inputs=[io.String.Input("model_name", default="", socketless=True),
                    io.String.Input("options_json", default=DEFAULT_OPTIONS_JSON, socketless=True)],
            outputs=[io.Custom("YTON_LLM").Output(display_name="LLM")])

    @classmethod
    def execute(cls, model_name, options_json):
        parse_options(options_json)
        if not model_name:
            raise ValueError("请先选择本地 GGUF 模型。")
        return io.NodeOutput(LocalLLMConnection(model_name, options_json))
