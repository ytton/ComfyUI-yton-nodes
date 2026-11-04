"""Workflow-owned llama.cpp options and the local GGUF catalogue."""

import json
import math
from pathlib import Path

from .prompt_optimizer import OptimizerError


# Shared by the Python validator and the advanced-settings dialog.
FIELDS = [
    dict(key="n_ctx", label="模型上下文", default=16384, min=512, max=262144, step=1, group="加载"),
    dict(key="max_tokens", label="最大输出 Token", default=2048, min=1, max=131072, step=1, group="采样"),
    dict(key="temperature", label="温度", default=0.7, min=0, max=2, step=0.05, group="采样"),
    dict(key="top_k", label="Top K", default=20, min=0, max=1000, step=1, group="采样"),
    dict(key="top_p", label="Top P", default=0.9, min=0, max=1, step=0.01, group="采样"),
    dict(key="min_p", label="Min P", default=0.05, min=0, max=1, step=0.01, group="采样"),
    dict(key="repeat_penalty", label="重复惩罚", default=1.05, min=0, max=2, step=0.01, group="采样"),
    dict(key="frequency_penalty", label="频率惩罚", default=0.0, min=-2, max=2, step=0.1, group="采样"),
    dict(key="present_penalty", label="存在惩罚", default=0.0, min=-2, max=2, step=0.1, group="采样"),
    dict(key="seed", label="种子（-1 随机）", default=-1, min=-1, max=4294967295, step=1, group="采样"),
    dict(key="thinking", label="思考强度", default="off", choices=[["off", "关闭"], ["low", "低 · 512 Token"], ["medium", "中 · 2048 Token"], ["high", "高 · 8192 Token"], ["custom", "自定义预算"]], group="思考", help="以思考开关和 Token 预算控制；效果取决于模型的思考模板，思考和正文共用最大输出限制。"),
    dict(key="reasoning_budget", label="自定义思考预算（-1 不限）", default=2048, min=-1, max=131072, step=1, group="思考"),
    dict(key="handler", label="对话模板", default="auto", choices=[["auto", "自动 · 使用 GGUF 模板"], ["qwen35", "Qwen3.5 / 3.8"], ["qwen3vl", "Qwen3-VL"], ["mtmd", "通用多模态 MTMD"]], group="加载"),
    dict(key="mmproj", label="多模态投影模型", default="auto", catalogue="mmprojs", group="加载", help="自动匹配 GGUF 同目录唯一的 mmproj；图片、音频与视频输入需要匹配的投影模型和模型支持。"),
    dict(key="n_gpu_layers", label="GPU 层数（-1 全部，0 CPU）", default=-1, min=-1, max=999, step=1, group="加载"),
    dict(key="n_threads", label="CPU 线程数（0 自动）", default=0, min=0, max=512, step=1, group="加载"),
    dict(key="n_batch", label="逻辑批次大小", default=2048, min=32, max=32768, step=1, group="加载"),
    dict(key="n_ubatch", label="物理批次大小", default=512, min=32, max=32768, step=1, group="加载", help="多模态执行时至少使用 2048，并确保逻辑批次不小于物理批次。"),
    dict(key="flash_attn", label="Flash Attention", default=True, group="加载"),
    dict(key="offload_kqv", label="KV 缓存卸载到 GPU", default=True, group="加载"),
    dict(key="kv_cache_type", label="KV 缓存精度", default="f16", choices=[["f16", "F16"], ["q8_0", "Q8_0"], ["q4_0", "Q4_0"]], group="加载"),
    dict(key="image_min_tokens", label="图片最少 Token", default=1024, min=64, max=16384, step=1, group="加载"),
    dict(key="image_max_tokens", label="图片最多 Token", default=2048, min=64, max=16384, step=1, group="加载"),
    dict(key="keep_loaded", label="生成后保留模型", default=False, group="加载", help="开启后复用模型可加快后续增强，但会继续占用显存；关闭时本次执行结束就释放。"),
]
DEFAULT_OPTIONS = {field["key"]: field["default"] for field in FIELDS}
DEFAULT_OPTIONS_JSON = json.dumps(DEFAULT_OPTIONS, ensure_ascii=False, separators=(",", ":"))


def parse_options(raw):
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        raise OptimizerError("llama.cpp 高级设置不是有效 JSON。") from None
    if not isinstance(values, dict) or set(values) != set(DEFAULT_OPTIONS):
        raise OptimizerError("llama.cpp 高级设置字段不完整，请打开齿轮并保存当前配置。")
    for field in FIELDS:
        value, default = values[field["key"]], field["default"]
        valid = False
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, (int, float)):
            valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                     and math.isfinite(value) and field["min"] <= value <= field["max"]
                     and (not isinstance(default, int) or isinstance(value, int)))
        elif "choices" in field:
            valid = value in [choice[0] for choice in field["choices"]]
        else:
            valid = isinstance(value, str)
        if not valid:
            raise OptimizerError(f"请检查{field['label']}。")
    if values["max_tokens"] >= values["n_ctx"]:
        raise OptimizerError("最大输出 Token 必须小于模型上下文，并给输入留出空间。")
    if values["n_ubatch"] > values["n_batch"]:
        raise OptimizerError("物理批次不能大于逻辑批次。")
    if values["image_min_tokens"] > values["image_max_tokens"]:
        raise OptimizerError("图片最少 Token 不能大于图片最多 Token。")
    if values["kv_cache_type"] != "f16" and not values["flash_attn"]:
        raise OptimizerError("量化 KV 缓存需要启用 Flash Attention。")
    budget = thinking_budget(values)
    if budget >= values["max_tokens"]:
        raise OptimizerError("最大输出 Token 需大于思考预算，才能留出正文空间。")
    return values


def thinking_budget(options):
    return {"off": 0, "low": 512, "medium": 2048, "high": 8192,
            "custom": options["reasoning_budget"]}[options["thinking"]]


def _register_models():
    import folder_paths
    path = str(Path(folder_paths.models_dir) / "LLM")
    # Register our actual model directory without changing other plugins' roots.
    folder_paths.add_model_folder_path("LLM", path)
    folder_paths.folder_names_and_paths["LLM"][1].add(".gguf")
    return folder_paths


def model_catalogue():
    paths = _register_models()
    files = paths.get_filename_list("LLM")
    projectors = [name for name in files if "mmproj" in Path(name).name.lower()]
    return {"models": [name for name in files if name not in projectors],
            "mmprojs": projectors, "fields": FIELDS, "defaults": DEFAULT_OPTIONS}


def resolve_files(model, options, has_media=False):
    paths = _register_models()
    catalogue = model_catalogue()
    if not model or model not in catalogue["models"]:
        raise OptimizerError("请选择可用的 GGUF 模型（ComfyUI/models/LLM）。")
    model_path = paths.get_full_path_or_raise("LLM", model)
    projector = options["mmproj"]
    if projector == "auto":
        siblings = [name for name in catalogue["mmprojs"] if Path(name).parent == Path(model).parent]
        if len(siblings) > 1:
            raise OptimizerError("模型目录有多个 mmproj，请在齿轮设置里明确选择。")
        projector = siblings[0] if siblings else ""
    if projector and projector not in catalogue["mmprojs"]:
        raise OptimizerError("所选 mmproj 不可用，请检查高级设置。")
    if has_media and not projector:
        raise OptimizerError("参考素材输入需要匹配的 mmproj，请在高级设置中选择。")
    if options["handler"] != "auto" and not projector:
        raise OptimizerError("所选多模态模板需要 mmproj；纯文本 GGUF 请使用自动模板。")
    return model_path, paths.get_full_path_or_raise("LLM", projector) if projector else None
