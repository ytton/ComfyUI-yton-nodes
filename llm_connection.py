"""Shared LLM connection used by task nodes that own their instructions and media."""

from dataclasses import dataclass
import base64
import io
import wave

import numpy as np
from PIL import Image

from .prompt_optimizer import completion_text, get_store, request_json, resolve_model


@dataclass(frozen=True)
class LLMConnection:
    model_ref: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096

    def generate(self, prompt, *, system="", images=(), audios=(), media=(), parameters=None):
        provider, model = resolve_model(get_store().read(), self.model_ref)
        options = {"temperature": self.temperature, "max_tokens": self.max_tokens}
        parameters = parameters or {}
        unsupported = parameters.keys() - {"temperature", "max_tokens", "top_p", "seed", "response_format"}
        if unsupported:
            raise ValueError("不支持的 LLM 参数：" + ", ".join(sorted(unsupported)))
        options.update(parameters)
        content = [{"type": "text", "text": prompt}]
        content.extend(media or ())
        for image in images:
            if not isinstance(image, Image.Image):
                raise TypeError("LLM 图片须为 PIL.Image。")
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=90)
            url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": url}})
        for audio in audios:
            if not audio:
                continue
            waveform = audio.get("waveform")
            sample_rate = int(audio.get("sample_rate", 0))
            if waveform is None or sample_rate <= 0:
                raise ValueError("LLM 音频参考需要包含 waveform 和有效采样率。")
            waveform = waveform.detach().float().cpu().numpy()
            if waveform.ndim == 3:
                waveform = waveform[0]
            if waveform.ndim == 1:
                waveform = waveform[None, :]
            if waveform.ndim != 2:
                raise ValueError("LLM 音频参考需要是声道 × 采样点格式。")
            pcm = (np.rint(np.clip(waveform, -1, 1) * 32767).astype("<i2")
                   .transpose(0, 1).copy().tobytes())
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as output:
                output.setnchannels(waveform.shape[0])
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(pcm)
            content.append({"type": "input_audio", "input_audio": {
                "data": base64.b64encode(buffer.getvalue()).decode("ascii"), "format": "wav"}})
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": content})
        response = request_json(provider, "/chat/completions", {
            "model": model, "messages": messages, "stream": False, **options,
        })
        return completion_text(response)
