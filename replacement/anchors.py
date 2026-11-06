"""Frame-accurate keyframes on the processed segment, independent of reference images."""

import math
from pathlib import Path

import av
from PIL import Image, ImageOps

from .media import image_tensors, input_path, segment_video
from .save import preview


def segment_info(config, index):
    video, _ = segment_video(config, index)
    path = Path(video.get_stream_source())
    return path, float(video.get_frame_rate()), video.get_frame_count()


def read_frame(path, fps, frame):
    with av.open(str(path) if isinstance(path, (str, Path)) else path) as container:
        stream = container.streams.video[0]
        timestamp = frame / fps
        container.seek(int(timestamp / stream.time_base), stream=stream, backward=True)
        for decoded in container.decode(stream):
            if decoded.time is not None and decoded.time + 0.5 / fps >= timestamp:
                return decoded.to_image().convert("RGB")
    raise ValueError("无法读取所选帧，请重新打开关键帧替换。")


def frame_preview(config, index, frame):
    path, fps, count = segment_info(config, index)
    if not isinstance(frame, int) or not 0 <= frame < count:
        raise ValueError("所选帧超出当前片段范围。")
    image_path = path.with_name(f"{path.stem}-frame-{frame}.png")
    if not image_path.exists():
        read_frame(path, fps, frame).save(image_path)
    return {"image": preview(image_path, "temp"), "frame": frame}


def editor_preview(config, index):
    path, fps, count = segment_info(config, index)
    strip_path = path.with_name(f"{path.stem}-strip.jpg")
    samples = min(12, count)
    if not strip_path.exists():
        strip = Image.new("RGB", (samples * 144, 84), "#15171c")
        for i in range(samples):
            frame = round(i * (count - 1) / max(1, samples - 1))
            image = ImageOps.fit(read_frame(path, fps, frame), (144, 84))
            strip.paste(image, (i * 144, 0))
        strip.save(strip_path, quality=85)
    return {"video": preview(path, "temp"), "strip": preview(strip_path, "temp"),
            "key": path.stem, "fps": fps, "frames": count}


def anchor_images(config, index):
    if not config.get("anchors"):
        return []
    path, fps, count = segment_info(config, index)
    result = []
    for item in sorted(config["anchors"].get(path.stem, []), key=lambda item: item["frame"]):
        if not item.get("image") or item.get("stale"):
            continue
        frame = item["frame"]
        if not isinstance(frame, int) or not 0 <= frame < count:
            raise ValueError("替换帧超出当前片段范围，请重新选帧。")
        with Image.open(input_path(item["image"])) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            result.append({"frame": math.floor(frame * 24 / fps + 0.5), "image": image_tensors([image])[0]})
    return result
