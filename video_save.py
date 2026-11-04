"""Encode before publishing: a failed destination must not discard a video."""

from datetime import datetime
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
import wave

import av
import folder_paths
import imageio_ffmpeg
import torch
from comfy_api.latest import InputImpl, Types


LOGGER = logging.getLogger(__name__)
CONTAINERS = {"mp4", "mkv", "webm", "mov"}
CODECS = {"auto", "h264", "av1", "prores"}
PRESETS = {"ultrafast", "fast", "medium", "slow"}
DEFAULT_PATH = "视频/{date}/片段-{index}"


def warn(messages, message):
    messages.append(message)
    LOGGER.warning("[yton 保存视频] %s", message)


def encoding_options(container, codec, preset, messages):
    if container not in CONTAINERS or codec not in CODECS or preset not in PRESETS:
        warn(messages, "格式或编码设置无效，改用 MP4 / H.264 / fast。")
        return "mp4", "h264", "fast"
    allowed = {"mp4": {"auto", "h264", "av1"}, "mkv": CODECS,
               "webm": {"auto", "av1"}, "mov": {"auto", "prores"}}
    if codec not in allowed[container]:
        codec = {"webm": "av1", "mov": "prores"}.get(container, "h264")
        warn(messages, f"所选编码与 {container.upper()} 不匹配，改用 {codec}。")
    if codec == "auto":
        codec = {"webm": "av1", "mov": "prores"}.get(container, "h264")
    return container, codec, preset


def path_values(video, started):
    width, height = video.get_dimensions()
    rate = float(video.get_frame_rate())
    # MKV/WebM durations include audio encoder delay; packet count avoids an extra frame in tags.
    with av.open(video.get_stream_source()) as container:
        stream = container.streams.video[0]
        frames = stream.frames or sum(1 for packet in container.demux(stream) if packet.size)
    return {"date": started.strftime("%Y-%m-%d"), "time": started.strftime("%H-%M-%S"),
            "datetime": started.strftime("%Y-%m-%d_%H-%M-%S"),
            "year": started.strftime("%Y"), "month": started.strftime("%m"), "day": started.strftime("%d"),
            "resolution": f"{width}x{height}", "width": str(width), "height": str(height),
            "fps": f"{rate:g}", "frames": str(frames), "duration": f"{frames / rate:.2f}s"}


def destination(root, template, values, index, extension):
    def replace(match):
        name = match[1]
        if name != "index" and name not in values:
            raise ValueError(f"未知路径标签：{name}")
        return f"{index:05d}" if name == "index" else values[name]

    expanded = re.sub(r"\{([^{}]+)\}", replace, template).replace("\\", "/")
    if not expanded or expanded.startswith("/"):
        raise ValueError("保存路径必须是 output 内的相对路径")
    parts = expanded.split("/")
    for part in parts:
        if (not part or part in {".", ".."} or part.rstrip(" .") != part
                or re.search(r'[<>:"|?*\x00-\x1f{}]', part)
                or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", part.split(".")[0])):
            raise ValueError(f"路径包含无效目录或文件名：{part!r}")
    name = parts[-1]
    if Path(name).suffix.lower().lstrip(".") in CONTAINERS:
        name = Path(name).stem
    if "{index}" not in template:
        name += f"_{index:05d}"
    target = root.joinpath(*parts[:-1], name + "." + extension).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("保存路径超出 output 目录")
    return target


def publish(source, root, template, values, index):
    """Reserve a filename across workers; publish only a complete copy."""
    number = max(1, int(index))
    while True:
        target = destination(root, template, values, number, source.suffix[1:])
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            number += 1
            continue
        pending = target.with_name(target.name + ".part")
        try:
            output = pending.open("xb")
        except FileExistsError:
            number += 1
            continue
        try:
            with output:
                if target.exists():
                    number += 1
                    continue
                with source.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            os.replace(pending, target)
            return target
        finally:
            discard(pending)


def discard(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def valid_video(path):
    with av.open(str(path)) as container:
        next(container.decode(video=0))


def staging_directory(messages, excluded=()):
    locations = [lambda: Path(folder_paths.get_temp_directory()) / "yton-video-save",
                 lambda: Path(folder_paths.get_output_directory()) / "video" / "恢复",
                 lambda: Path(tempfile.gettempdir()) / "ComfyUI-yton-recovery"]
    for location in locations:
        try:
            directory = location()
            if directory.resolve() in excluded:
                continue
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / (uuid.uuid4().hex + ".probe")
            with probe.open("xb"):
                pass
            probe.unlink()
            return directory
        except Exception as error:
            warn(messages, f"临时保存位置不可写：{error}")
    raise OSError("临时目录、输出目录和系统备用目录均已尝试，没有可用保存位置")


def write_audio(audio, path):
    samples = audio["waveform"][0].detach().cpu().clamp(-1, 1)
    pcm = (samples.transpose(0, 1) * 32767).round().to(dtype=torch.int16).numpy()
    with wave.open(str(path), "wb") as output:
        output.setnchannels(samples.shape[0])
        output.setsampwidth(2)
        output.setframerate(int(audio["sample_rate"]))
        output.writeframes(pcm.tobytes())


def transform(path, video, fps, audio, codec, crf, preset):
    """Changing VIDEO fps must resample frames, preserving the original duration."""
    target = path.with_name(path.stem + "-adjusted" + path.suffix)
    audio_path = path.with_suffix(".wav")
    command = [shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe(),
               "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(path)]
    try:
        if audio is not None:
            write_audio(audio, audio_path)
            command += ["-i", str(audio_path)]
        command += ["-map", "0:v:0", "-map", "1:a:0" if audio is not None else "0:a?"]
        if fps > 0 and abs(fps - float(video.get_frame_rate())) > 1e-6:
            encoders = {"h264": "libx264", "av1": "libsvtav1", "prores": "prores_ks"}
            command += ["-vf", f"fps={fps:g}", "-c:v", encoders[codec]]
            if codec != "prores":
                command += ["-crf", str(crf)]
            if codec == "h264":
                command += ["-preset", preset, "-pix_fmt", "yuv420p"]
        else:
            command += ["-c:v", "copy"]
        command += ["-c:a", "libopus" if path.suffix == ".webm" else "aac",
                    "-af", "apad", "-t", str(float(video.get_duration())), "-map_metadata", "0"]
        if path.suffix in {".mp4", ".mov"}:
            command += ["-movflags", "+faststart+use_metadata_tags"]
        command += [str(target)]
        result = subprocess.run(command, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise ValueError(result.stderr.decode("utf-8", errors="replace")[-1500:])
        valid_video(target)
        return target
    except Exception:
        discard(target)
        raise
    finally:
        discard(audio_path)


def save_video(video, template, index, container, codec, fps, crf, preset, audio, metadata, messages):
    started = datetime.now()
    container, codec, preset = encoding_options(container, codec, preset, messages)
    directory = staging_directory(messages)
    identifier = started.strftime("%Y-%m-%d_%H-%M-%S") + "_" + uuid.uuid4().hex[:12]
    staged = directory / (identifier + "." + container)
    try:
        video.save_to(str(staged), format=Types.VideoContainer(container), codec=Types.VideoCodec(codec),
                      crf=crf if codec != "prores" else None, preset=preset if codec == "h264" else None,
                      metadata=metadata)
        valid_video(staged)
    except Exception as error:
        warn(messages, f"所选编码保存失败，尝试通用 MP4 / H.264：{error}")
        discard(staged)
        recovery_video = video
        width, height = video.get_dimensions()
        if width % 2 or height % 2:
            components = video.get_components()
            images = torch.nn.functional.pad(components.images.permute(0, 3, 1, 2),
                                             (0, width % 2, 0, height % 2), mode="replicate").permute(0, 2, 3, 1)
            recovery_video = InputImpl.VideoFromComponents(Types.VideoComponents(
                images=images, audio=components.audio, frame_rate=components.frame_rate))
            warn(messages, f"通用 MP4 要求偶数尺寸，已补齐边缘：{width}×{height} → {width + width % 2}×{height + height % 2}。")
        attempted = {directory.resolve()}
        while True:
            staged = directory / (identifier + "-recovery.mp4")
            try:
                recovery_video.save_to(str(staged), format=Types.VideoContainer.MP4, codec=Types.VideoCodec.H264,
                                       crf=18, preset="fast", bit_depth=8, color_space="sRGB", chroma_subsampling="420")
                valid_video(staged)
                break
            except Exception as recovery_error:
                discard(staged)
                warn(messages, f"位置 {directory} 编码写入失败：{recovery_error}；尝试其他保存位置。")
                directory = staging_directory(messages, attempted)
                attempted.add(directory.resolve())
        codec, crf, preset = "h264", 18, "fast"
    if audio is not None or (fps > 0 and abs(fps - float(video.get_frame_rate())) > 1e-6):
        try:
            adjusted = transform(staged, video, fps, audio, codec, crf, preset)
            discard(staged)
            staged = adjusted
        except Exception as error:
            warn(messages, f"帧率或音频调整失败，保留已编码的视频：{error}")
    saved_video = InputImpl.VideoFromFile(str(staged))
    values = path_values(saved_video, started)
    try:
        target = publish(staged, Path(folder_paths.get_output_directory()), template, values, index)
    except Exception as error:
        warn(messages, f"指定路径 {template!r} 保存失败：{error}；正在改存备用位置。")
        try:
            target = publish(staged, Path(folder_paths.get_output_directory()),
                             "video/恢复/{date}/{time}/视频-{index}", values, 0)
        except Exception as recovery_error:
            target = staged
            warn(messages, f"备用输出目录也不可写：{recovery_error}；已保留临时文件，请及时复制。")
    if target != staged:
        discard(staged)
    LOGGER.info("[yton 保存视频] 实际保存位置：%s", target)
    if messages:
        warn(messages, f"实际保存位置：{target}")
    return target


def preview_result(path):
    for folder_type, directory in (("output", folder_paths.get_output_directory()),
                                   ("temp", folder_paths.get_temp_directory())):
        root = Path(directory).resolve()
        if path.resolve().is_relative_to(root):
            relative = path.resolve().relative_to(root)
            return {"filename": relative.name, "subfolder": relative.parent.as_posix() if relative.parent != Path(".") else "",
                    "type": folder_type}
    return None
