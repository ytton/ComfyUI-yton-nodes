"""The replacement task owns its instructions; the connection owns transport."""

import hashlib
import json
from pathlib import Path
import tempfile

import folder_paths

from .media import contact_sheet, input_path, plan_for


SYSTEM = """你是视频人物替换提示词编写助手。用户提供当前原视频片段的六帧时间顺序拼图，以及依次编号的参考图片。
第一张输入图片是原视频拼图，代表 <Video 1>，不属于 Picture 编号；后面的参考图片从 <Picture 1> 开始。
结合原视频画面、用户要求与参考图，判断各图片是人物、背景还是其他参考；支持多个人物分别替换，不得把所有图片强制当作人物。
保留用户明确指定的替换对应关系。没有给出的身份、声音与不可观察信息不编造。明确描述原片段中可见的主体、动作、环境与构图，再写出对应替换要求。
动作、身体节奏、手势、表情、眼神、唇形与镜头时机严格沿用原视频。角色身份、服装和画风全程稳定；背景是否替换依据用户要求，避免背景拉伸。
只输出可直接用于视频生成的中文提示词，使用 <Video 1> 和 <Picture N> 引用素材，必须包含下面五部分，不能返回说明或代码块：
【主体替换】
【角色外观】
【背景】
【同步要求】
【负面提示】
负面提示应针对本片段的风险，包括身份漂移、比例错误、重影、模糊、过曝、背景透视畸变与动作节奏变化；不得反向否定用户明确要求的构图或特征。"""


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
              config.get("ratio"), config.get("resolution"), config.get("image_scale"),
              [(str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files]]
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def optimize(connection, config, index, video, images):
    if connection is None:
        raise ValueError("请连接【LLM 通用连接器】后再优化提示词。")
    result = connection.generate(
        f"当前片段：{index + 1}。参考图片共 {len(images)} 张。\n用户要求：\n{resolve_references(source_prompt(config, index), config)}",
        system=load_skill(), images=[contact_sheet(video), *images])
    if not result.strip():
        raise ValueError("模型返回了空提示词，请检查模型是否支持图片。")
    return result.strip()
