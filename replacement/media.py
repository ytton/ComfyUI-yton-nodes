"""File-backed video preparation; only the requested segment is transcoded."""

from functools import lru_cache
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import threading

import av
import folder_paths
import numpy as np
from PIL import Image, ImageDraw, ImageOps
import torch
from comfy_api.latest import InputImpl

from .plan import make_plan, FPS


def input_path(filename):
    path = Path(folder_paths.get_annotated_filepath(filename)).resolve()
    roots = [Path(p()).resolve() for p in (folder_paths.get_input_directory,
             folder_paths.get_output_directory, folder_paths.get_temp_directory)]
    if not any(path.is_relative_to(root) for root in roots) or not path.is_file():
        raise ValueError("素材不存在或不在 ComfyUI 媒体目录内。")
    return path


@lru_cache(maxsize=1)
def ffmpeg():
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg
    except ImportError:
        raise RuntimeError("请将 FFmpeg 加入 PATH，或安装 imageio-ffmpeg 后重启 ComfyUI。") from None
    return imageio_ffmpeg.get_ffmpeg_exe()


def encode(arguments):
    process = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                              *map(str, arguments)], capture_output=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode:
        raise ValueError("视频处理失败：" + process.stderr.decode("utf-8", errors="replace")[-1800:])


def inspect(filename):
    with av.open(str(input_path(filename))) as container:
        stream = container.streams.video[0]
        duration = float(stream.duration * stream.time_base) if stream.duration is not None else float(container.duration or 0) / av.time_base
        return {"width": stream.width, "height": stream.height, "duration": duration,
                "fps": float(stream.average_rate or FPS), "audio": bool(container.streams.audio)}


def plan_for(config):
    metadata = inspect(config["video"])
    plan = make_plan(config["plan"], metadata["duration"])
    return metadata, plan


def output_size(config, metadata):
    # The same resolution table as the existing H3 resolution control.
    from ..nodes.resolution_node import YtonResolutionSelector
    ratio = config.get("ratio", "原视频")
    crop = config.get("crop") or (0, 0, 1, 1)
    source_ratio = metadata["width"] * crop[2] / (metadata["height"] * crop[3])
    if ratio == "原视频":
        short_edge = int(config.get("resolution", "480p").removesuffix("p"))
        width, height = ((short_edge * source_ratio, short_edge) if source_ratio >= 1
                         else (short_edge, short_edge / source_ratio))
    else:
        width, height, *_ = YtonResolutionSelector().get_resolution(
            "MiniMax H3 (Video)", ratio, config.get("resolution", "480p"))
    return tuple(max(32, round(side / 32) * 32) for side in (width, height))


def reference_size(config, metadata):
    crop = config.get("crop") or (0, 0, 1, 1)
    source_width, source_height = metadata["width"] * crop[2], metadata["height"] * crop[3]
    settings = config["compression"]
    custom_width, custom_height = int(settings.get("width", 0)), int(settings.get("height", 0))
    width = custom_width or (custom_height * source_width / source_height if custom_height else source_width)
    height = custom_height or (custom_width * source_height / source_width if custom_width else source_height)
    if settings.get("resize_method") == "maintain aspect ratio":
        scale = min(width / source_width, height / source_height)
        width, height = source_width * scale, source_height * scale
    edge = int(settings.get("max_edge", 0))
    if edge > 0 and max(width, height) > edge:
        scale = edge / max(width, height)
        width, height = width * scale, height * scale
    return tuple(max(2, round(side / 2) * 2) for side in (width, height))


_encode_lock = threading.Lock()


def segment_video(config, index):
    metadata, plan = plan_for(config)
    if not 0 <= index < len(plan["segments"]):
        raise ValueError(f"当前索引 {index} 超出范围（0–{len(plan['segments']) - 1}）。")
    segment = plan["segments"][index]
    source = input_path(config["video"])
    width, height = reference_size(config, metadata)
    settings = config.get("compression", {})
    fps = FPS if config["plan"]["enabled"] else int(settings.get("fps", FPS))
    if fps <= 0:
        raise ValueError("压缩帧率需要大于 0。")
    filters = []
    crop = config.get("crop")
    if crop:
        x, y, w, h = map(float, crop)
        if not (0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0 and x + w <= 1.00001 and y + h <= 1.00001):
            raise ValueError("画面裁剪范围无效。")
        filters.append(f"crop=trunc(iw*{w}/2)*2:trunc(ih*{h}/2)*2:trunc(iw*{x}/2)*2:trunc(ih*{y}/2)*2")
    resize_method = settings.get("resize_method", "pad")
    if resize_method == "stretch to fit":
        filters.append(f"scale={width}:{height}:flags=lanczos")
    elif resize_method == "crop":
        filters.extend([f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos",
                        f"crop={width}:{height}"])
    elif resize_method in ("pad", "maintain aspect ratio"):
        filters.extend([f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos",
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"])
    else:
        raise ValueError("视频缩放方式无效。")
    filters.extend([f"fps={fps}", "setsar=1"])
    signature = json.dumps([str(source), source.stat().st_mtime_ns, source.stat().st_size,
                            segment, filters, settings], sort_keys=True).encode()
    path = Path(folder_paths.get_temp_directory()) / "yton-replacement" / (hashlib.sha256(signature).hexdigest() + ".mp4")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _encode_lock:
        if not path.exists():
            temporary = path.with_suffix(".encoding.mp4")
            try:
                encode(["-ss", segment["start"] / FPS, "-i", source,
                        "-t", (segment["end"] - segment["start"]) / FPS,
                        "-map", "0:v:0", "-map", "0:a:0?", "-vf", ",".join(filters),
                        "-c:v", "libx264", "-preset", "fast", "-crf", int(settings.get("crf", 18)),
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-af", "aresample=async=1:first_pts=0",
                        "-movflags", "+faststart", temporary])
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return InputImpl.VideoFromFile(str(path)), plan


def reference_images(config):
    scale = float(config.get("image_scale", 1))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("图片缩放比例需要大于 0。")
    result = []
    for filename in config["images"]:
        if not filename:
            continue
        with Image.open(input_path(filename)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            size = tuple(max(1, round(side * scale)) for side in image.size)
            result.append(image.resize(size, Image.Resampling.LANCZOS))
    return result


def image_tensors(images):
    return [torch.from_numpy(np.array(image, dtype=np.float32) / 255).unsqueeze(0) for image in images]


def contact_sheet(video):
    # Seek each point instead of decoding the whole clip into a tensor.
    path = video.get_stream_source()
    with av.open(path) as container:
        stream = container.streams.video[0]
        duration = float(stream.duration * stream.time_base)
        sheet = Image.new("RGB", (960, 600), "#171a20")
        draw = ImageDraw.Draw(sheet)
        for i in range(6):
            second = max(0, duration - 1 / FPS) * i / 5
            container.seek(int(second / stream.time_base), stream=stream, backward=True)
            for frame in container.decode(stream):
                if float(frame.time or 0) + 1 / FPS >= second:
                    image = ImageOps.contain(frame.to_image().convert("RGB"), (316, 270))
                    x, y = (i % 3) * 320, (i // 3) * 300
                    sheet.paste(image, (x + (320 - image.width) // 2, y))
                    draw.text((x + 8, y + 276), f"{i + 1} | {second:.2f}s", fill="white")
                    break
        return sheet
