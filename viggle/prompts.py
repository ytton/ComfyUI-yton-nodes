"""Prompt optimization uses the same references and pins as Conditioning."""

import hashlib
import json
from pathlib import Path
import tempfile

import folder_paths

from ..replacement.media import contact_sheet, input_path
from ..replacement.prompts import prompt_slot, source_prompt
from .media import reference_entries, segment_metadata


SYSTEM = Path(__file__).with_name("skill.md").read_text(encoding="utf-8")


def load_skill():
    path = Path(folder_paths.get_user_directory()) / "yton-viggle-skill.md"
    return path.read_text(encoding="utf-8") if path.exists() else SYSTEM


def save_skill(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Skill 不能为空。")
    root = Path(folder_paths.get_user_directory())
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    try:
        temporary.replace(root / "yton-viggle-skill.md")
    finally:
        temporary.unlink(missing_ok=True)
    return {"skill": text, "default_skill": SYSTEM}


def resolve_references(text, config, index):
    entries = reference_entries(config, index)
    for number, entry in reversed(list(enumerate(entries, 1))):
        slot = entry["slot"] + 1 if config["mode"] == "reference" else number
        text = text.replace(f"@图片{slot}", f"<Picture {number}>")
    return text.replace("@视频", "<Video 1>")


def signature(config, index):
    info, _, _ = segment_metadata(config, index)
    entries = reference_entries(config, index)
    files = [input_path(name) for name in [config["video"], *[e["image"] for e in entries]]]
    value = [load_skill(), source_prompt(config, index), config["mode"], entries, info,
             config["crop"], config["ratio"], config["resolution"], config["image_scale"],
             [(str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files]]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def optimize(connection, config, index, video, images, pins):
    if connection is None:
        raise ValueError("请连接 LLM 通用连接器或本地模型连接器。")
    if not images:
        raise ValueError("请先上传至少一张参考图或替换关键帧。")
    mapping = "普通参考图：这些图片提供人物身份与服装，不指定出现帧。"
    if config["mode"] == "keyframe":
        mapping = "关键帧模式：以下图片是编辑后应出现的完整目标帧。\n" + "\n".join(
            f"<Picture {i}> 对应零基帧索引 {frame}，时间 {int(frame) / 24:.3f} 秒。"
            for i, frame in enumerate(pins.split(","), 1))
    _, metadata, _ = segment_metadata(config, index)
    instruction = (f"第 {index + 1} 段，24fps，共 {video.get_frame_count()} 帧。原视频{'有音轨' if metadata['audio'] else '没有音轨'}。\n"
                   f"{mapping}\n用户要求：\n{resolve_references(source_prompt(config, index), config, index)}\n"
                   "第一张拼图仅展示 <Video 1> 的六个时刻，不占用 Picture 编号。其后的图片按输入顺序编号。")
    result = connection.generate(instruction, system=load_skill(), images=[contact_sheet(video), *images])
    if not result.strip():
        raise ValueError("模型返回了空提示词。")
    return result.strip()
