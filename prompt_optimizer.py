"""Shared OpenAI-compatible prompt optimization and server-side settings."""

import json
import os
import re
from pathlib import Path
import tempfile
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


DEFAULT_RULES = (
    "你是图片与视频生成提示词编辑。保留用户的主体、动作、场景和明确约束，"
    "把零散描述整理成清晰、具体、可执行的提示词。按需要补充构图、光线、"
    "镜头或材质细节，不擅自改变人物身份、剧情或增加无关元素。"
    "沿用用户使用的语言，只输出优化后的提示词正文。"
)

SKILL_RUNTIME_CONTRACT = (
    "Runtime output contract: This is one text-generation API call whose response is sent "
    "directly to the next workflow node. All Skill reference files are already included above. "
    "There are no filesystem, shell, Python or other tools available to call. Apply the Skill's "
    "creative rules and return its final usable prompt directly in the requested language and format, "
    "including JSON when that is the intended final prompt. Perform any reasoning internally. "
    "Do not output a plan, tool calls, shell commands, intermediate drafts, file links or claims "
    "that scripts were executed. Omit explanatory preambles and Markdown code fences. "
    "If the Skill describes saving or compiling files, use its reference material to produce "
    "the final text in this response; no tool-execution turn will follow. "
    "Follow the Skill's final delivery format, not the editable draft format for its compiler. "
    "Return the compiled content itself, not a JSON field wrapping that content. "
    "When the Skill's final deliverable is a plain-text caption, return only that caption text; "
    "when its final deliverable is a structured layout, return that final layout directly."
)


class OptimizerError(ValueError):
    pass


def _string(value, label, required=True):
    if not isinstance(value, str) or (required and not value.strip()):
        raise OptimizerError(f"请填写{label}。")
    return value.strip()


def validate_provider(value, existing=None):
    if not isinstance(value, dict):
        raise OptimizerError("服务商配置格式错误。")
    provider_id = _string(value.get("id"), "服务商 ID")
    name = _string(value.get("name"), "服务商名称")
    base_url = _string(value.get("baseUrl"), "服务地址").rstrip("/")
    parsed = urlsplit(base_url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise OptimizerError("服务地址需为 HTTP(S) URL，且不包含账号、查询参数或片段。")
    models = value.get("models", [])
    if not isinstance(models, list):
        raise OptimizerError("模型列表格式错误。")
    models = [_string(model, "模型 ID") for model in models]
    if len(set(models)) != len(models):
        raise OptimizerError("模型 ID 不能重复。")
    key = _string(value.get("apiKey", ""), "API Key", required=False)
    if not key and not value.get("clearApiKey"):
        key = (existing or {}).get("apiKey", "")
    if "\n" in key or "\r" in key:
        raise OptimizerError("API Key 不能包含换行。")
    return {"id": provider_id, "name": name, "baseUrl": base_url,
            "apiKey": key, "models": models, "enabled": bool(value.get("enabled", True))}


class ConfigStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            if not self.path.exists():
                return {"providers": [], "defaultModel": ""}
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise OptimizerError("无法读取 AI 配置，请检查 user/yton-ai.json。") from error

    def public(self):
        data = self.read()
        return {"providers": [{**{key: value for key, value in provider.items() if key != "apiKey"},
                                "apiKeyConfigured": bool(provider.get("apiKey"))}
                               for provider in data["providers"]],
                "defaultModel": data["defaultModel"]}

    def save(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("providers"), list):
            raise OptimizerError("AI 配置格式错误。")
        with self.lock:
            previous = {provider["id"]: provider for provider in self.read()["providers"]}
            providers = [validate_provider(item, previous.get(item.get("id")) if isinstance(item, dict) else None)
                         for item in data["providers"]]
            if len({provider["id"] for provider in providers}) != len(providers):
                raise OptimizerError("服务商 ID 不能重复。")
            default = data.get("defaultModel", "")
            valid_models = {model_reference(provider["id"], model)
                            for provider in providers if provider["enabled"] for model in provider["models"]}
            if not isinstance(default, str) or (default and default not in valid_models):
                raise OptimizerError("默认模型必须来自已启用的服务商。")
            if valid_models and not default:
                raise OptimizerError("请选择一个默认模型。")
            config = {"providers": providers, "defaultModel": default}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                                 prefix=".yton-ai-", delete=False) as handle:
                    temporary = handle.name
                    json.dump(config, handle, ensure_ascii=False, indent=2)
                os.replace(temporary, self.path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            return self.public()

    def draft_provider(self, value):
        previous = next((provider for provider in self.read()["providers"]
                         if provider["id"] == value.get("id")), None)
        return validate_provider(value, previous)


def model_reference(provider_id, model_id):
    return json.dumps([provider_id, model_id], ensure_ascii=False, separators=(",", ":"))


def resolve_model(config, reference):
    try:
        selection = json.loads(reference or config["defaultModel"])
        if not isinstance(selection, list) or len(selection) != 2 or not all(isinstance(item, str) for item in selection):
            raise ValueError
        provider_id, model_id = selection
    except (ValueError, TypeError):
        raise OptimizerError("请点击节点右下角齿轮，配置服务商并选择默认模型。") from None
    provider = next((item for item in config["providers"] if item["id"] == provider_id), None)
    if not provider or not provider["enabled"] or model_id not in provider["models"]:
        raise OptimizerError("所选模型不可用，请检查服务商是否启用及模型列表。")
    return provider, model_id


def _safe_message(message, provider):
    message = str(message)
    if provider.get("apiKey"):
        message = message.replace(provider["apiKey"], "[已隐藏]")
    return message[:500]


def request_json(provider, endpoint, payload=None, timeout=120):
    headers = {"Accept": "application/json"}
    if provider["apiKey"]:
        headers["Authorization"] = f"Bearer {provider['apiKey']}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(provider["baseUrl"] + endpoint, data=body, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        message = "请求被服务商拒绝"
        try:
            upstream = json.loads(error.read().decode("utf-8"))
            detail = upstream.get("error", {})
            message = detail.get("message", message) if isinstance(detail, dict) else detail
        except (ValueError, UnicodeError, AttributeError):
            pass
        raise OptimizerError(f"服务商返回 HTTP {error.code}：{_safe_message(message, provider)}") from None
    except (TimeoutError, URLError, OSError):
        raise OptimizerError("无法连接服务商或请求超时，请检查服务地址、网络和 API Key。") from None
    except (ValueError, UnicodeError):
        raise OptimizerError("服务商未返回有效 JSON，请检查服务地址是否包含正确的 API 前缀。") from None
    if not isinstance(data, dict):
        raise OptimizerError("服务商返回的数据格式错误。")
    return data


def discover_models(provider):
    data = request_json(provider, "/models", timeout=20)
    if not isinstance(data.get("data"), list):
        raise OptimizerError("模型列表响应缺少 data 数组；可手动填写模型 ID。")
    return sorted({item["id"] for item in data["data"]
                   if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()})


def build_messages(prompt, rules=DEFAULT_RULES, *, media=None, skill=""):
    prompt = _string(prompt, "用户提示词", required=False)
    rules = _string(rules, "系统提示词", required=False)
    if not prompt and not rules and not skill:
        raise OptimizerError("系统提示词、用户提示词或 Skill 至少提供一项。")
    media = media or []
    content = prompt
    if media:
        content = ([{"type": "text", "text": prompt}] if prompt else []) + media
    system = "\n\n".join(value for value in (skill, rules, SKILL_RUNTIME_CONTRACT if skill else "") if value)
    messages = [{"role": "system", "content": system}] if system else []
    if content:
        messages.append({"role": "user", "content": content})
    return messages


def optimize(store, prompt, rules=DEFAULT_RULES, model_ref="", *, media=None, skill=""):
    messages = build_messages(prompt, rules, media=media, skill=skill)
    provider, model = resolve_model(store.read(), model_ref)
    data = request_json(provider, "/chat/completions", {
        "model": model,
        "messages": messages,
        "stream": False,
    })
    return {"text": completion_text(data)}


def completion_text(data):
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise OptimizerError("服务商响应缺少 choices，未获取到优化结果。")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise OptimizerError("模型输出达到长度上限，结果不完整；请缩短输入或调整服务商的输出限制。")
    message = choice.get("message") or {}
    if choice.get("finish_reason") in ("tool_calls", "function_call") or (
            isinstance(message, dict) and (message.get("tool_calls") or message.get("function_call"))):
        raise OptimizerError("模型返回了工具调用，未生成可用提示词；本节点只接受最终提示词正文。")
    result = message.get("content") if isinstance(message, dict) else None
    if not isinstance(result, str) or not result.strip():
        raise OptimizerError("模型未返回提示词正文，请检查模型是否支持文本对话或调整优化规则。")
    result = result.strip()
    if re.search(r"<[^>]*(?:DSML|tool_call|function_call)[^>]*>", result, re.IGNORECASE):
        raise OptimizerError("模型输出了工具调用标记，未生成可用提示词；请检查系统提示词或所选模型。")
    fenced = re.fullmatch(r"```(?:text|json)?[ \t]*\n(.*?)\n```", result, re.DOTALL)
    if fenced:
        result = fenced[1].strip()
        if not result:
            raise OptimizerError("模型返回了空提示词。")
    return result


_store = None


def get_store():
    global _store
    if _store is None:
        import folder_paths
        _store = ConfigStore(Path(folder_paths.get_user_directory()) / "yton-ai.json")
    return _store
