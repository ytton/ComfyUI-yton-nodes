"""Reference-image and prompt settings for MiniMax H3 Image workflows."""

import math
import os
import re

import numpy as np
import torch
from PIL import Image, ImageOps

from ..prompt_optimizer import OptimizerError, get_store, optimize
from ..prompt_optimizer_media import media_content
from ..prompt_optimizer_skill import load_skill
from .media_loader_node import resolve_media_file


REFERENCE_COUNT = 16
RATIOS = ("auto", "1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16")
AREA_PRESETS = (4, 6, 8, 10, 12, 16, 20)
REFERENCE_TARGETS = (0, 4, 8, 16)
REFERENCE_PATTERN = re.compile(r"@(\d+)(?!\d)")


def selected_files(slots):
    files = []
    for number in range(1, REFERENCE_COUNT + 1):
        name = str(slots.get(f"image_{number}", "")).strip()
        if name and not slots.get(f"disable_image_{number}", False):
            files.append((number, name, resolve_media_file(name)))
    return files


def reference_dimensions(width, height, target_mp):
    if not target_mp or width * height >= target_mp * 1_000_000:
        return width, height
    scale = math.sqrt(target_mp * 1_000_000 / (width * height))
    return math.ceil(width * scale), math.ceil(height * scale)


def validate_files(files, target_mp):
    if target_mp not in REFERENCE_TARGETS:
        raise ValueError("请选择有效的参考图缩放目标")
    for number, name, path in files:
        if os.path.getsize(path) > 64 * 1024 * 1024:
            raise ValueError(f"参考图 {number} 超过 64 MiB：{name}")
        with Image.open(path) as source:
            if source.format not in {"JPEG", "PNG", "WEBP", "HEIF", "HEIC"}:
                raise ValueError(f"参考图 {number} 仅支持 JPG、PNG、WebP、HEIC 或 HEIF：{name}")
            width, height = source.size
            if not (128 <= width <= 8192 and 128 <= height <= 8192 and 0.25 <= width / height <= 4):
                raise ValueError(f"参考图 {number} 的边长或比例超出 H3 Image 限制：{name}")
            scaled = reference_dimensions(width, height, target_mp)
            if not all(128 <= side <= 8192 for side in scaled):
                raise ValueError(f"参考图 {number} 缩放后边长须在 128–8192 像素之间")


def load_images(files, target_mp):
    images = []
    for _, _, path in files:
        with Image.open(path) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            size = reference_dimensions(source.width, source.height, target_mp)
            if size != source.size:
                source = source.resize(size, Image.Resampling.LANCZOS)
            pixels = np.asarray(source, dtype=np.float32) / 255.0
        images.append(torch.from_numpy(pixels).unsqueeze(0))
    return images


def output_dimensions(resolution_mp, aspect_ratio, images):
    if not isinstance(resolution_mp, (int, float)) or not math.isfinite(resolution_mp) or not 4 <= resolution_mp <= 20:
        raise ValueError("分辨率面积须在 4–20 MP 之间")
    if aspect_ratio not in RATIOS:
        raise ValueError("请选择有效的 H3 Image 画面比例")
    if aspect_ratio == "auto":
        ratio = images[0].shape[2] / images[0].shape[1] if images else 1.0
        ratio = min(3.0, max(1 / 3, ratio))
    else:
        width, height = map(int, aspect_ratio.split(":"))
        ratio = width / height
    area = resolution_mp * 1_000_000
    width = round(math.sqrt(area * ratio) / 8) * 8
    height = round(math.sqrt(area / ratio) / 8) * 8
    if width * height > 20_000_000:
        if width >= height:
            width -= 8
        else:
            height -= 8
    return width, height


def resolve_references(prompt, files):
    positions = {slot: index for index, (slot, _, _) in enumerate(files, 1)}

    def replace(match):
        slot = int(match.group(1))
        if slot not in positions:
            raise ValueError(f"@{slot} 对应的参考图槽位为空或已禁用")
        return f"参考图 {positions[slot]}"

    return REFERENCE_PATTERN.sub(replace, prompt)


def optimize_h3_image(data):
    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        raise OptimizerError("请先填写原提示词。")
    try:
        target_mp = float(data.get("reference_target_mp", 4.0))
        files = selected_files(data)
        validate_files(files, target_mp)
        images = load_images(files, target_mp)
        resolved = resolve_references(prompt, files)
    except (ValueError, OSError) as error:
        raise OptimizerError(str(error)) from error
    result = optimize(get_store(), resolved, model_ref=str(data.get("model_ref", "")),
                      media=media_content(image=images), skill=load_skill(str(data.get("skill_name", "h3-image"))))
    return {"text": result["text"]}


class YtonH3ImageConfig:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"default": "", "multiline": True}),
            "optimized_prompt": ("STRING", {"default": "", "multiline": True}),
            "resolution_mp": ("FLOAT", {"default": 16.0, "min": 4.0, "max": 20.0, "step": 0.1}),
            "aspect_ratio": (list(RATIOS), {"default": "16:9"}),
            "reference_target_mp": ("FLOAT", {"default": 4.0, "min": 0.0, "max": 16.0, "step": 4.0}),
            "model_ref": ("STRING", {"default": ""}),
            "skill_name": ("STRING", {"default": "h3-image"}),
            **{f"image_{number}": ("STRING", {"default": ""}) for number in range(1, REFERENCE_COUNT + 1)},
        }, "optional": {
            **{f"disable_image_{number}": ("BOOLEAN", {"default": False}) for number in range(1, REFERENCE_COUNT + 1)},
        }}

    RETURN_TYPES = ("IMAGE", "STRING", "INT", "INT")
    RETURN_NAMES = ("参考图列表", "提示词", "宽度", "高度")
    OUTPUT_IS_LIST = (True, False, False, False)
    FUNCTION = "configure"
    CATEGORY = "yton-nodes/MiniMax H3"
    DESCRIPTION = "最多 16 张参考图。4×4 槽位按顺序输出图片列表；@编号引用对应槽位。提供 4–20 MP 画幅与参考图缩放，提示词可用共享 LLM 和 Skill 优化。"

    @classmethod
    def IS_CHANGED(cls, **inputs):
        files = selected_files(inputs)
        return tuple((number, path, os.stat(path).st_mtime_ns, os.stat(path).st_size) for number, _, path in files)

    @classmethod
    def VALIDATE_INPUTS(cls, **inputs):
        try:
            validate_files(selected_files(inputs), float(inputs.get("reference_target_mp", 4.0)))
        except (ValueError, OSError) as error:
            return str(error)
        return True

    def configure(self, prompt, optimized_prompt, resolution_mp, aspect_ratio, reference_target_mp, model_ref, skill_name, **slots):
        files = selected_files(slots)
        validate_files(files, reference_target_mp)
        images = load_images(files, reference_target_mp)
        width, height = output_dimensions(resolution_mp, aspect_ratio, images)
        text = resolve_references(optimized_prompt.strip() or prompt, files)
        if not text:
            raise ValueError("请填写 H3 Image 提示词")
        return images, text, width, height
