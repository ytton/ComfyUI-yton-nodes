"""The replacement task owns its instructions; the connection owns transport."""

import hashlib
import json
from pathlib import Path
import tempfile

import folder_paths

from .media import contact_sheet, input_path, plan_for


SYSTEM = Path(__file__).with_name("skill.md").read_text(encoding="utf-8")


def load_skill():
    path = Path(folder_paths.get_user_directory()) / "yton-replacement-skill.md"
    return path.read_text(encoding="utf-8") if path.exists() else SYSTEM


def save_skill(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("优化 Skill 不能为空。")
    path = Path(folder_paths.get_user_directory()) / "yton-replacement-skill.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".yton-replacement-skill-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"skill": text, "default_skill": SYSTEM}


def prompt_slot(config, index):
    return "shared" if config["shared"] else str(index)


def source_prompt(config, index):
    slot = prompt_slot(config, index)
    return config["prompts"].get(slot, config["original"])


def resolve_references(text, config):
    for native_index, slot_index in enumerate((i for i, name in enumerate(config["images"], 1) if name), 1):
        text = text.replace(f"@图片{slot_index}", f"<Picture {native_index}>")
    return text.replace("@视频", "<Video 1>")


def signature(config, index):
    files = [input_path(filename) for filename in [config["video"], *config["images"]] if filename]
    _, plan = plan_for(config)
    fps = 24 if config["plan"]["enabled"] else int(config["compression"]["fps"])
    # Encoding dimensions and quality do not change the action described by a prompt.
    values = [load_skill(), source_prompt(config, index), plan, config.get("crop") or [0, 0, 1, 1], fps,
              config.get("image_scale"),
              [(str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files]]
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def optimize(connection, config, index, video, images):
    if connection is None:
        raise ValueError("请连接 LLM 通用连接器或本地模型连接器后再优化提示词。")
    result = connection.generate(
        f"当前片段：{index + 1}。参考图片共 {len(images)} 张。\n用户要求：\n{resolve_references(source_prompt(config, index), config)}",
        system=load_skill(), images=[contact_sheet(video), *images])
    if not result.strip():
        raise ValueError("模型返回了空提示词，请检查模型是否支持图片。")
    return result.strip()
