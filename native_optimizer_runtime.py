"""Use the official Generate Text node with workflow-owned rules and media."""

import json
import math

from comfy_extras.nodes_textgen import TextGenerateV2

from .llama_optimizer_config import FIELDS
from .prompt_optimizer import OptimizerError, build_messages, completion_text
from .prompt_optimizer_media import VIDEO_FRAMES


NATIVE_KEYS = {"max_tokens", "temperature", "top_k", "top_p", "min_p", "repeat_penalty", "present_penalty", "seed"}
NATIVE_FIELDS = [field for field in FIELDS if field["key"] in NATIVE_KEYS] + [
    dict(key="thinking", label="启用思考", default=False, group="思考", help="由接入的模型决定是否支持；思考与正文共用输出长度。"),
]
DEFAULT_NATIVE = {field["key"]: field["default"] for field in NATIVE_FIELDS}
DEFAULT_NATIVE_JSON = json.dumps(DEFAULT_NATIVE, separators=(",", ":"))


def parse_native_options(raw):
    values = json.loads(raw)
    if not isinstance(values, dict) or set(values) != set(DEFAULT_NATIVE):
        raise OptimizerError("原生推理设置字段不完整，请打开齿轮并保存配置。")
    for field in NATIVE_FIELDS:
        value = values[field["key"]]
        if type(field["default"]) is bool:
            valid = type(value) is bool
        else:
            valid = (type(value) in (int, float) and math.isfinite(value)
                     and field["min"] <= value <= field["max"]
                     and (type(field["default"]) is not int or type(value) is int))
        if not valid:
            raise OptimizerError(f"请检查{field['label']}。")
    return values


def native_media(image, audio, video):
    images, audios, descriptions = {}, {}, []
    for batch in image or []:
        if batch is None:
            continue
        for frame in range(batch.shape[0]):
            images[str(len(images))] = batch[frame:frame + 1]
    for item in audio or []:
        if item is not None:
            audios[str(len(audios))] = item
    for index, item in enumerate(video or [], 1):
        if item is None:
            continue
        components = item.get_components()
        frames, rate = components.images, float(components.frame_rate)
        if len(frames) == 0 or not math.isfinite(rate) or rate <= 0:
            raise OptimizerError(f"视频 {index} 没有有效画面或帧率。")
        count = min(VIDEO_FRAMES, len(frames))
        positions = [round(i * (len(frames) - 1) / max(1, count - 1)) for i in range(count)]
        labels = []
        for position in positions:
            images[str(len(images))] = frames[position:position + 1]
            labels.append(f"输入图片 {len(images)} = {position / rate:.3f} 秒")
        descriptions.append(f"视频 {index} 时长 {len(frames) / rate:.3f} 秒，均匀抽帧按时间排列：" + "；".join(labels) + "。")
        if components.audio is not None:
            audios[str(len(audios))] = components.audio
            descriptions.append(f"输入音频 {len(audios)} 为视频 {index} 原音轨。")
    return images, audios, "\n".join(descriptions)


def generate_native(clip, prompt, rules, skill, raw_options, *, image=None, audio=None, video=None):
    if clip is None:
        raise OptimizerError("请连接支持文本生成的 CLIP，或切换到 llama.cpp 并选择 GGUF 模型。")
    options = parse_native_options(raw_options)
    messages = build_messages(prompt, rules, skill=skill)
    system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
    images, audios, description = native_media(image, audio, video)
    user = "\n\n".join(value for value in (description, prompt.strip()) if value)
    sampling = {
        "sampling_mode": "on" if options["temperature"] > 0 else "off",
        "temperature": options["temperature"], "top_k": options["top_k"],
        "top_p": options["top_p"], "min_p": options["min_p"],
        "repetition_penalty": options["repeat_penalty"], "presence_penalty": options["present_penalty"],
        "seed": None if options["seed"] == -1 else options["seed"],
    }
    output = TextGenerateV2.execute(clip, user, options["max_tokens"], sampling,
                                    thinking=options["thinking"], system_prompt=system,
                                    images=images, audios=audios)
    text, reasoning = output.result
    if not text.strip() and reasoning:
        raise OptimizerError("模型只返回了思考，请提高输出长度或关闭思考。")
    return completion_text({"choices": [{"message": {"content": text}}]})
