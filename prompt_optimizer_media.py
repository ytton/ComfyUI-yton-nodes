"""Encode native ComfyUI media lists for OpenAI-compatible chat inputs."""

import base64
from io import BytesIO
import wave

import numpy as np
from PIL import Image

from .prompt_optimizer import OptimizerError


VIDEO_FRAMES = 12
IMAGE_MAX_SIDE = 1536


def _text(value):
    return {"type": "text", "text": value}


def _image(frame):
    pixels = frame.detach().cpu().numpy()
    if pixels.ndim != 3 or pixels.shape[-1] not in (1, 3, 4) or not np.isfinite(pixels).all():
        raise OptimizerError("图片输入必须是有效的 ComfyUI IMAGE 张量。")
    pixels = np.rint(np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    if pixels.shape[-1] == 1:
        pixels = pixels[:, :, 0]
    image = Image.fromarray(pixels).convert("RGB")
    image.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}


def _audio(value, label):
    if not isinstance(value, dict) or "waveform" not in value or "sample_rate" not in value:
        raise OptimizerError(f"{label}必须是 ComfyUI AUDIO。")
    waveform = value["waveform"].detach().cpu().numpy()
    rate = value["sample_rate"]
    if (waveform.ndim != 3 or not all(waveform.shape) or not np.isfinite(waveform).all()
            or not isinstance(rate, int) or rate <= 0):
        raise OptimizerError(f"{label}的采样率或音频波形无效。")
    parts = []
    for index, clip in enumerate(waveform, 1):
        buffer = BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(clip.shape[0])
            handle.setsampwidth(2)
            handle.setframerate(rate)
            samples = np.rint(np.clip(clip, -1, 1) * 32767).astype("<i2")
            handle.writeframes(samples.T.copy().tobytes())
        suffix = f" · 批次 {index}" if len(waveform) > 1 else ""
        parts.extend([_text(f"{label}{suffix} · {clip.shape[-1] / rate:.3f} 秒"), {
            "type": "input_audio",
            "input_audio": {"data": base64.b64encode(buffer.getvalue()).decode("ascii"), "format": "wav"},
        }])
    return parts


def media_content(image=None, audio=None, video=None):
    """Consume the whole native list once, preserving media and batch order."""
    parts = []
    picture = 0
    for batch in image or []:
        if batch is None:
            continue
        if getattr(batch, "ndim", 0) != 4:
            raise OptimizerError("图片列表需要 ComfyUI IMAGE 批次。")
        for frame in batch:
            picture += 1
            parts.extend([_text(f"图片 {picture}"), _image(frame)])
    for index, item in enumerate(audio or [], 1):
        if item is not None:
            parts.extend(_audio(item, f"音频 {index}"))
    for index, item in enumerate(video or [], 1):
        if item is None:
            continue
        components = item.get_components()
        frames = components.images
        rate = float(components.frame_rate)
        if len(frames) == 0 or not np.isfinite(rate) or rate <= 0:
            raise OptimizerError(f"视频 {index} 没有有效画面或帧率。")
        indices = np.linspace(0, len(frames) - 1, min(VIDEO_FRAMES, len(frames)), dtype=int)
        parts.append(_text(f"视频 {index} · 时长 {len(frames) / rate:.3f} 秒 · 以下为按时间顺序均匀抽取的画面"))
        for frame_index in indices:
            parts.extend([_text(f"视频 {index} · {frame_index / rate:.3f} 秒"), _image(frames[frame_index])])
        if components.audio is not None:
            parts.extend(_audio(components.audio, f"视频 {index} 原音轨"))
    return parts
