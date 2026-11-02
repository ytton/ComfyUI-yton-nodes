"""Shared LLM connection used by task nodes that own their instructions and media."""

from dataclasses import dataclass
import base64
import io

from PIL import Image

from .prompt_optimizer import completion_text, get_store, request_json, resolve_model


@dataclass(frozen=True)
class LLMConnection:
    model_ref: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096

    def generate(self, prompt, *, system="", images=(), parameters=None):
        provider, model = resolve_model(get_store().read(), self.model_ref)
        options = {"temperature": self.temperature, "max_tokens": self.max_tokens}
        parameters = parameters or {}
        unsupported = parameters.keys() - {"temperature", "max_tokens", "top_p", "seed", "response_format"}
        if unsupported:
            raise ValueError("不支持的 LLM 参数：" + ", ".join(sorted(unsupported)))
        options.update(parameters)
        content = [{"type": "text", "text": prompt}]
        for image in images:
            if not isinstance(image, Image.Image):
                raise TypeError("LLM 图片须为 PIL.Image。")
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=90)
            url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": url}})
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": content})
        response = request_json(provider, "/chat/completions", {
            "model": model, "messages": messages, "stream": False, **options,
        })
        return completion_text(response)
