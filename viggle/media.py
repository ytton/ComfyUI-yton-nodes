"""Viggle's four references and frame positions, on the edited 24 fps timeline."""

import copy
import json
from pathlib import Path

from PIL import Image, ImageOps

from ..replacement.anchors import read_frame
from ..replacement.media import input_path, output_size, plan_for as replacement_plan, segment_video
from ..replacement.save import preview


DEFAULT_CONFIG = {
    "video": "", "mode": "reference", "images": [""] * 4, "keyframes": {},
    "original": "替换视频中指定的人物，使用参考图片的人物外貌与服装，动作、镜头和背景沿用原视频。",
    "prompts": {}, "optimized": {}, "shared": False, "auto": False,
    "ratio": "原视频", "resolution": "480p", "image_scale": 1,
    "plan": {"enabled": True, "mode": "普通", "frames": 192, "seconds": 8,
             "overlap": 5, "output": "完整片段", "start": 0, "end": 0, "split": "fixed"},
    "crop": None, "compression": {"fps": 24, "crf": 18, "max_edge": 0,
                                    "width": 0, "height": 0, "resize_method": "pad"},
}


def parse_config(value):
    config = json.loads(value) if isinstance(value, str) else copy.deepcopy(value)
    if config["mode"] not in ("reference", "keyframe") or len(config["images"]) != 4:
        raise ValueError("请选择参考图或关键帧模式，并配置四个图片槽位。")
    if config["plan"]["overlap"] not in (0, 5):
        raise ValueError("Viggle 分段上下文只能选择无上下文或 5 帧。")
    return config


def prepared_config(config):
    value = copy.deepcopy(config)
    if not value["plan"]["enabled"]:
        value["plan"].update(mode="普通", seconds=1e9)
    # Viggle consumes the source canvas itself, so generation dimensions must
    # be applied before its Conditioning node, including non-16:9 source ratios.
    from ..replacement.media import inspect
    width, height = output_size(value, inspect(value["video"]))
    value["compression"].update(width=width, height=height, fps=24, max_edge=0)
    return value


def plan_for(config):
    value = copy.deepcopy(config)
    if not value["plan"]["enabled"]:
        value["plan"].update(mode="普通", seconds=1e9)
    return replacement_plan(value)


def segment(config, index):
    return segment_video(prepared_config(config), index)


def segment_metadata(config, index):
    metadata, plan = plan_for(config)
    if not 0 <= index < len(plan["segments"]):
        raise ValueError("片段索引超出范围。")
    current = plan["segments"][index]
    overlap = max(0, plan["segments"][index - 1]["end"] - current["start"]) if index else 0
    count = current["end"] - current["start"]
    return {"index": index, "source_frames": count, "overlap_frames": overlap,
            "context_frames": plan["context_frames"], "start": current["start"],
            "end": current["end"], "total": len(plan["segments"]), "fps": 24}, metadata, plan


def preview_segment(config, index):
    video, _ = segment(config, index)
    info, metadata, plan = segment_metadata(config, index)
    width, height = output_size(config, metadata)
    return {"video": preview(Path(video.get_stream_source()), "temp"),
            "frames": video.get_frame_count(), "fps": 24, "segment": info,
            "metadata": metadata, "plan": plan, "output_size": {"width": width, "height": height}}


def source_frame(config, index, frame):
    video, _ = segment(config, index)
    if type(frame) is not int or not 0 <= frame < video.get_frame_count():
        raise ValueError("所选帧超出当前片段。")
    path = Path(video.get_stream_source())
    target = path.with_name(f"{path.stem}-frame-{frame}.png")
    if not target.exists():
        read_frame(path, 24, frame).save(target)
    return {"image": preview(target, "temp"), "frame": frame}


def previous_frame(config, index, frame, previous):
    current, _, _ = segment_metadata(config, index)
    if type(frame) is not int or not 0 <= frame < current["overlap_frames"]:
        raise ValueError("当前帧不在与上一段重叠的范围内。")
    prior, _, _ = segment_metadata(config, index - 1)
    count = previous.get_frame_count()
    raw, delivered = prior["source_frames"], prior["source_frames"] - prior["overlap_frames"]
    # Saved results may have already passed through the restore node. Match
    # their actual source-time range, never count back from an H3 padded tail.
    if count == delivered:
        removed = prior["overlap_frames"]
    elif count >= raw:
        removed = 0
    else:
        raise ValueError("上一段生成结果长度与分段计划不一致，请先重新生成上一段。")
    offset = current["start"] + frame - prior["start"] - removed
    if not 0 <= offset < count:
        raise ValueError("上一段结果中没有对应的重叠帧。")
    image = read_frame(previous.get_stream_source(), float(previous.get_frame_rate()), offset)
    return image, offset


def reference_entries(config, index):
    if config["mode"] == "reference":
        return [{"image": name, "slot": i} for i, name in enumerate(config["images"]) if name]
    entries = config["keyframes"].get(str(index), [])
    if len(entries) > 4 or len({item["frame"] for item in entries}) != len(entries):
        raise ValueError("每段最多选择四个不同的关键帧。")
    info, _, _ = segment_metadata(config, index)
    for item in entries:
        if type(item["frame"]) is not int or not 0 <= item["frame"] < info["source_frames"]:
            raise ValueError("关键帧超出当前片段，请重新选择。")
    return [item for item in sorted(entries, key=lambda item: item["frame"]) if item.get("image")]


def references(config, index, previous=None):
    entries = reference_entries(config, index)
    scale = float(config["image_scale"])
    if not 0 < scale <= 4:
        raise ValueError("参考图片缩放需要大于 0 且不超过 4。")
    images = []
    for item in entries:
        if item.get("source") == "previous" and previous is not None:
            image, _ = previous_frame(config, index, item["frame"], previous)
        else:
            with Image.open(input_path(item["image"])) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
        if scale != 1:
            image = image.resize(tuple(max(1, round(side * scale)) for side in image.size), Image.Resampling.LANCZOS)
        images.append(image)
    pins = ", ".join(str(item["frame"]) for item in entries) if config["mode"] == "keyframe" else ""
    return images, pins
