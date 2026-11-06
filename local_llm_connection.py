"""Local GGUF connection; tasks supply their own system prompt and media."""

from dataclasses import dataclass
import json

from .llama_optimizer_config import DEFAULT_OPTIONS_JSON, parse_options
from .llama_optimizer_runtime import runtime
from .llm_connection import LLMConnection, chat_messages


@dataclass(frozen=True)
class LocalLLMConnection:
    model_name: str = ""
    options_json: str = DEFAULT_OPTIONS_JSON

    def generate(self, prompt, *, system="", images=(), audios=(), media=(), parameters=None):
        values = json.loads(self.options_json)
        parameters = parameters or {}
        unsupported = parameters.keys() - {"temperature", "max_tokens", "top_p", "seed"}
        if unsupported:
            raise ValueError("本地 LLM 不支持的调用参数：" + ", ".join(sorted(unsupported)))
        values.update(parameters)
        options = parse_options(json.dumps(values))
        messages = chat_messages(prompt, system=system, images=images, audios=audios, media=media)
        has_media = any(item.get("type") != "text" for message in messages
                        if isinstance(message["content"], list) for item in message["content"])
        return runtime.generate(self.model_name, options, messages, has_media=has_media)


def connection_from_config(config):
    kind = config["kind"]
    parameters = {key: value for key, value in config.items() if key != "kind"}
    if kind == "local":
        return LocalLLMConnection(**parameters)
    if kind == "remote":
        return LLMConnection(**parameters)
    raise ValueError("LLM 连接器类型无效。")
